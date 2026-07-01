"""
策略基类 - 所有策略继承此类
"""

import abc
import logging
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, Position, OrderType
import config.settings as _settings
from core.runtime_config import RuntimeConfig as _RuntimeConfig

logger = logging.getLogger(__name__)


class BaseStrategy(abc.ABC):
    """策略基类"""

    name = "base"

    # 旧版 magic 列表：引擎在追踪持仓时会同时识别这些 magic，视为本策略的单子
    # 用于版本升级后自动接管旧 magic 的持仓，避免产生孤儿单
    legacy_magics: list[int] = []

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        self.bridge = bridge
        self.symbol = _settings.SYMBOL
        self.magic = magic or _settings.MAGIC_NUMBER
        self.timeframe = timeframe or _settings.TIMEFRAME
        self.candles: list[Candle] = []
        self._trail_sl: dict[int, float] = {}
        # 最近一次信号详情（供引擎写入 DB）
        self._last_signal: Optional[dict] = None
        self._m30_candles: list[Candle] = []
        self._h1_candles: list[Candle] = []
        self._h4_candles: list[Candle] = []

        # K-line filter parameters (from RuntimeConfig → runtime_config.json, hot-reloadable)
        _coord = _RuntimeConfig().get_coordinator_config()
        self.position_gate_enabled: bool = _coord.get('position_gate_enabled', True)
        self.position_gate_lookback: int = _coord.get('position_gate_lookback', 60)
        self.position_gate_m30_lookback: int = _coord.get('position_gate_m30_lookback', 40)
        self.position_gate_bottom: float = _coord.get('position_gate_bottom', 0.10)
        self.position_gate_top: float = _coord.get('position_gate_top', 0.90)
        self.rally_drop_enabled: bool = _coord.get('rally_drop_enabled', True)
        self.rally_drop_lookback: int = _coord.get('rally_drop_lookback', 30)
        self.rally_drop_threshold: float = _coord.get('rally_drop_threshold', 1.5)
        self.di_gate_skip_threshold: float = _coord.get('di_gate_skip_threshold', 20)
        self.rally_drop_adx_skip: float = _coord.get('rally_drop_adx_skip', 25)
        self.profit_drawdown_enabled: bool = _coord.get('profit_drawdown_enabled', True)
        self.profit_drawdown_pct: float = _coord.get('profit_drawdown_pct', 0.25)
        self.profit_drawdown_min_peak_atr: float = _coord.get('profit_drawdown_min_peak_atr', 0.5)

        # News-Bias 阻塞开关（每次信号动态读取 config_service，覆盖优先）
        self.block_long_when_bias_bearish: bool = _settings.BLOCK_LONG_WHEN_BIAS_BEARISH
        self.block_short_when_bias_bullish: bool = _settings.BLOCK_SHORT_WHEN_BIAS_BULLISH

    @property
    def all_magics(self) -> set[int]:
        """返回本策略所有 magic 号（主magic + 旧版legacy magic）"""
        return {self.magic} | set(self.legacy_magics)

    def refresh_data(self, count: int = 200):
        """刷新K线数据，转为时间顺序（旧→新）"""
        raw = self.bridge.get_candles(self.symbol, self.timeframe, count)
        self.candles = list(reversed(raw))

    def get_close_prices(self) -> list[float]:
        """获取收盘价序列"""
        return [c.close for c in self.candles]

    def _apply_kline_filters(self, result: tuple):
        """统一 K 线过滤器（保留供外部调用，引擎层使用 calc_gate_state）"""
        return result

    def calc_gate_state(self, direction: Optional[str], price: float,
                        adx_data: Optional[dict] = None) -> dict:
        """计算门禁状态：位置门禁 + 急跌惩罚 + News-Bias。
        无论是否有信号都计算，用于引擎层统一拦截。
        返回: {"blocked": bool, "reason": str, "details": dict}"""
        state = {"blocked": False, "reason": "", "details": {}}

        # 统一加载 M30 数据（位置门禁 + 急跌急涨共用，避免重复查库）
        self._load_m30_data()

        # ── ① 位置门禁 + DI 跳过 ──
        if self.position_gate_enabled and direction:
            di_diff = 0
            if adx_data and adx_data.get("pdi") is not None:
                di_diff = abs(adx_data["pdi"] - adx_data["ndi"])
            else:
                # 数据库回退：用已加载的 M30 计算 DI diff
                if self._m30_candles:
                    m30_db = self._calc_m30_adx(14)
                    if m30_db:
                        di_diff = abs(m30_db["pdi"] - m30_db["ndi"])
            state["details"]["di_diff"] = round(di_diff, 1)

            if di_diff > self.di_gate_skip_threshold:
                state["details"]["pos_gate"] = f"DI跳过(diff={di_diff:.0f})"
            else:
                # 用 M30 40 根算位置（抗 spike 区间膨胀）
                m30_use = self._m30_candles
                if m30_use and len(m30_use) >= 2:
                    m30_lookback = min(self.position_gate_m30_lookback, len(m30_use))
                    hi = max(c.high for c in m30_use[-m30_lookback:])
                    lo = min(c.low for c in m30_use[-m30_lookback:])
                    pos = (price - lo) / (hi - lo) if hi > lo else 0.5
                    state["details"]["pos"] = round(pos, 3)
                    if direction == "SELL" and pos < self.position_gate_bottom:
                        state["blocked"] = True
                        state["reason"] = f"位置门禁: 底部 {pos:.1%}"
                        state["details"]["pos_gate"] = f"禁SELL({pos:.1%})"
                    elif direction == "BUY" and pos > self.position_gate_top:
                        state["blocked"] = True
                        state["reason"] = f"位置门禁: 顶部 {pos:.1%}"
                        state["details"]["pos_gate"] = f"禁BUY({pos:.1%})"
                    else:
                        state["details"]["pos_gate"] = f"正常({pos:.1%})"

        # ── ② 急跌急涨惩罚 ──
        if self.rally_drop_enabled and direction and not state["blocked"]:
            if self._m30_candles:
                rd_lookback = min(self.rally_drop_lookback, len(self._m30_candles))
                if rd_lookback >= 2:
                    # 优先用传入的 adx_data（实时桥接数据），回退到 SQLite
                    if adx_data and adx_data.get("adx"):
                        m30_adx = adx_data["adx"]
                    else:
                        m30_db = self._calc_m30_adx(14)
                        m30_adx = m30_db["adx"] if m30_db else None
                    state["details"]["m30_adx"] = round(m30_adx, 1) if m30_adx else 0
                    if m30_adx and m30_adx > self.rally_drop_adx_skip:
                        state["details"]["rally_drop"] = f"ADX跳过({m30_adx:.0f})"
                    else:
                        m30_close = self._m30_candles[-1].close
                        rd_hi = max(c.high for c in self._m30_candles[-rd_lookback:])
                        rd_lo = min(c.low for c in self._m30_candles[-rd_lookback:])
                        drop_pct = (rd_hi - m30_close) / rd_hi * 100
                        rally_pct = (m30_close - rd_lo) / rd_lo * 100
                        if direction == "SELL" and drop_pct > self.rally_drop_threshold:
                            state["blocked"] = True
                            state["reason"] = f"急跌惩罚: 回落 {drop_pct:.1f}%"
                            state["details"]["rally_drop"] = f"禁SELL({drop_pct:.1f}%)"
                        elif direction == "BUY" and rally_pct > self.rally_drop_threshold:
                            state["blocked"] = True
                            state["reason"] = f"急涨惩罚: 上涨 {rally_pct:.1f}%"
                            state["details"]["rally_drop"] = f"禁BUY({rally_pct:.1f}%)"
                        else:
                            state["details"]["rally_drop"] = "正常"

        # ── ③ News-Bias 阻塞 ──
        if not state["blocked"] and direction:
            try:
                _cfg = _RuntimeConfig()
                _block_long = _cfg.get("block_long_when_bias_bearish")
                _block_short = _cfg.get("block_short_when_bias_bullish")
            except Exception:
                _block_long = self.block_long_when_bias_bearish
                _block_short = self.block_short_when_bias_bullish
            if _block_long or _block_short:
                try:
                    from core import bias_state
                    bias_dir = bias_state.get()
                except Exception:
                    bias_dir = None
                if bias_dir == "bearish" and _block_long and direction == "BUY":
                    state["blocked"] = True
                    state["reason"] = "News-Bias 偏空，禁BUY"
                    state["details"]["bias"] = "bearish-block-BUY"
                elif bias_dir == "bullish" and _block_short and direction == "SELL":
                    state["blocked"] = True
                    state["reason"] = "News-Bias 偏多，禁SELL"
                    state["details"]["bias"] = "bullish-block-SELL"
                else:
                    state["details"]["bias"] = bias_dir or "neutral"

        return state

    def _load_m30_data(self):
        """加载 M30 K 线数据 — 优先 SQLite，回退到桥接直接获取"""
        try:
            from data.database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
            ).fetchall()
            conn.close()
            if rows:
                self._m30_candles = [
                    Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                    for r in rows
                ]
                return
        except Exception as e:
            logger.warning(f"[{self.name}] M30 DB load failed: {e}")

        # DB 无数据 → 直接从桥接获取
        try:
            raw = self.bridge.get_candles(self.symbol, "M30", 60)
            if raw:
                self._m30_candles = list(reversed(raw))
                logger.info(f"[{self.name}] M30 loaded from bridge: {len(self._m30_candles)} candles")
                return
        except Exception as e:
            logger.warning(f"[{self.name}] M30 bridge load failed: {e}")

        self._m30_candles = []

    def _load_h1_data(self):
        """加载 H1 K 线数据 — 优先 SQLite，回退到桥接直接获取"""
        try:
            from data.database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='H1' ORDER BY timestamp"
            ).fetchall()
            conn.close()
            if rows:
                self._h1_candles = [
                    Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                    for r in rows
                ]
                return
        except Exception as e:
            logger.warning(f"[{self.name}] H1 DB load failed: {e}")

        # DB 无数据 → 直接从桥接获取
        try:
            raw = self.bridge.get_candles(self.symbol, "H1", 60)
            if raw:
                self._h1_candles = list(reversed(raw))
                logger.info(f"[{self.name}] H1 loaded from bridge: {len(self._h1_candles)} candles")
                return
        except Exception as e:
            logger.warning(f"[{self.name}] H1 bridge load failed: {e}")

        self._h1_candles = []

    def _load_h4_data(self):
        """加载 H4 K 线数据 — 优先 SQLite，回退到桥接直接获取"""
        try:
            from data.database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='H4' ORDER BY timestamp"
            ).fetchall()
            conn.close()
            if rows:
                self._h4_candles = [
                    Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                    for r in rows
                ]
                return
        except Exception as e:
            logger.warning(f"[{self.name}] H4 DB load failed: {e}")

        try:
            raw = self.bridge.get_candles(self.symbol, "H4", 60)
            if raw:
                self._h4_candles = list(reversed(raw))
                logger.info(f"[{self.name}] H4 loaded from bridge: {len(self._h4_candles)} candles")
                return
        except Exception as e:
            logger.warning(f"[{self.name}] H4 bridge load failed: {e}")

        self._h4_candles = []

    def _get_h4_trend(self, period: int = 50) -> str:
        """H4 MAperiod趋势判断，返回 'UP' / 'DOWN' / 'NEUTRAL'"""
        if len(self._h4_candles) < period:
            return 'NEUTRAL'
        closes = [c.close for c in self._h4_candles]
        ma = sum(closes[-period:]) / period
        return 'UP' if closes[-1] > ma else 'DOWN'

    def _get_h1_trend(self, period: int = 20) -> str:
        """H1 MA2period趋势判断，返回 'UP' / 'DOWN' / 'NEUTRAL'"""
        if len(self._h1_candles) < period:
            return 'NEUTRAL'
        closes = [c.close for c in self._h1_candles]
        ma = sum(closes[-period:]) / period
        return 'UP' if closes[-1] > ma else 'DOWN'

    @staticmethod
    def calc_atr_wilder(candles: list, period: int = 14) -> Optional[float]:
        """标准 Wilder ATR。首根 SMA(TR,period)，后续 RMA 递推。
        candles 按时间旧→新排列。"""
        if not candles or len(candles) < period + 2:
            return None
        tr_values = []
        for i in range(1, len(candles)):
            h = candles[i].high
            l_ = candles[i].low
            pc = candles[i - 1].close
            tr = max(h - l_, abs(h - pc), abs(l_ - pc))
            tr_values.append(tr)
        if len(tr_values) < period:
            return None
        atr_v = sum(tr_values[:period]) / period
        alpha = 1.0 / period
        for v in tr_values[period:]:
            atr_v = atr_v + alpha * (v - atr_v)
        return atr_v

    @staticmethod
    def calc_adx_wilder(candles: list, period: int = 14) -> Optional[dict]:
        """标准 Wilder ADX/+DI/-DI（0-100 量纲）。

        标准 DMI：先对 +DM/-DM/TR 分别做 Wilder RMA 平滑，
        再 +DI = 100*RMA(+DM)/RMA(TR)，-DI 同理，DX = |+DI-−DI|/(+DI+−DI)*100，ADX = RMA(DX)。
        candles 按时间旧→新排列。返回 {adx, pdi, ndi} 或 None。
        """
        if not candles or len(candles) < period + 2:
            return None
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        n = len(highs)
        tr_list, plus_dm, minus_dm = [], [], []
        for i in range(1, n):
            h, l_, pc = highs[i], lows[i], closes[i - 1]
            ph, pl = highs[i - 1], lows[i - 1]
            tr = max(h - l_, abs(h - pc), abs(l_ - pc))
            up = h - ph
            down = pl - l_
            plus_dm.append(up if (up > down and up > 0) else 0)
            minus_dm.append(down if (down > up and down > 0) else 0)
            tr_list.append(tr)
        if len(tr_list) < period:
            return None

        def rma(values: list, n: int) -> list:
            alpha = 1.0 / n
            result = [sum(values[:n]) / n]
            for v in values[n:]:
                result.append(result[-1] + alpha * (v - result[-1]))
            return result

        atr_s = rma(tr_list, period)
        sdp = rma(plus_dm, period)   # 平滑 +DM
        sdm = rma(minus_dm, period)  # 平滑 -DM
        pdi_s = [100 * sdp[i] / atr_s[i] if atr_s[i] > 0 else 0.0 for i in range(len(atr_s))]
        ndi_s = [100 * sdm[i] / atr_s[i] if atr_s[i] > 0 else 0.0 for i in range(len(atr_s))]
        dx = [abs(pdi_s[i] - ndi_s[i]) / max(pdi_s[i] + ndi_s[i], 0.001) * 100
              for i in range(len(atr_s))]
        if len(dx) < period:
            return None
        adx = rma(dx, period)
        return {"adx": adx[-1], "pdi": pdi_s[-1], "ndi": ndi_s[-1]}

    def _calc_m30_adx(self, period: int = 14) -> Optional[dict]:
        """用 M30 K 线计算 ADX/DI（供门禁数据库回退使用），返回 {adx, pdi, ndi}（0-100 量纲）"""
        return self.calc_adx_wilder(self._m30_candles, period)

    @abc.abstractmethod
    def generate_signal(self):
        """
        生成交易信号。
        返回: tuple[Optional[OrderType], int, int, list, list, dict]
          - signal: BUY / SELL / None
          - score_long: 多头评分
          - score_short: 空头评分
          - factors_long: 多头因子列表
          - factors_short: 空头因子列表
          - indicator_values: 指标值字典（可 JSON 序列化）
        """
        ...

    def on_tick(self) -> Optional[str]:
        """
        主循环调用：检查信号并返回操作描述
        返回: 操作描述字符串，或 None
        """
        self.refresh_data()
        if len(self.candles) < 10:
            logger.warning(f"[{self.name}] K线数据不足: {len(self.candles)}")
            return None

        result = self.generate_signal()
        # 统一 K 线过滤器（位置门禁 + 急跌急涨惩罚）
        if isinstance(result, tuple):
            result = self._apply_kline_filters(result)
        signal = result[0] if isinstance(result, tuple) else result

        # 存储信号详情（供引擎写入数据库）
        if isinstance(result, tuple):
            self._last_signal = {
                "signal": signal.value if signal else None,
                "score_long": result[1],
                "score_short": result[2],
                "factors_long": result[3],
                "factors_short": result[4],
                "indicator_values": result[5],
            }
            # 如果有额外项（confidence 等）
            if len(result) > 6:
                self._last_signal["confidence"] = result[6]
        else:
            # 向后兼容：旧策略只返回 OrderType
            self._last_signal = {
                "signal": signal.value if signal else None,
                "score_long": 0, "score_short": 0,
                "factors_long": [], "factors_short": [],
                "indicator_values": {},
            }

        if signal:
            return f"信号: {signal.value}"
        return None

    def get_adx_data(self) -> Optional[dict]:
        """获取本策略的 ADX 数据（含 +DI/-DI），供引擎门禁使用"""
        return None  # 子类覆盖

    def reload_config(self):
        """热重载配置参数，子类覆盖（不覆盖 magic/timeframe，它们由 STRATEGY_POOL 管理）"""
        self.symbol = _settings.SYMBOL

        # 热重载 K 线过滤器参数（从 RuntimeConfig 读取，dashboard 保存优先）
        _coord = _RuntimeConfig().get_coordinator_config()
        self.position_gate_enabled = _coord.get('position_gate_enabled', True)
        self.position_gate_lookback = _coord.get('position_gate_lookback', 60)
        self.position_gate_m30_lookback = _coord.get('position_gate_m30_lookback', 40)
        self.position_gate_bottom = _coord.get('position_gate_bottom', 0.10)
        self.position_gate_top = _coord.get('position_gate_top', 0.90)
        self.rally_drop_enabled = _coord.get('rally_drop_enabled', True)
        self.rally_drop_lookback = _coord.get('rally_drop_lookback', 30)
        self.rally_drop_threshold = _coord.get('rally_drop_threshold', 1.5)
        self.di_gate_skip_threshold = _coord.get('di_gate_skip_threshold', 20)
        self.rally_drop_adx_skip = _coord.get('rally_drop_adx_skip', 25)
        self.profit_drawdown_enabled = _coord.get('profit_drawdown_enabled', True)
        self.profit_drawdown_pct = _coord.get('profit_drawdown_pct', 0.25)
        self.profit_drawdown_min_peak_atr = _coord.get('profit_drawdown_min_peak_atr', 0.5)

    def _check_breakeven_exit(self, td: dict, current_profit: float, atr_val: float,
                               entry: float, is_buy: bool) -> bool:
        """保本出场：价格走过 ≥0.3×ATR 盈利后回到成本附近时平仓，防盈利变亏损。
        子类在 check_ema20_exit 中 peak_profit 更新后调用。"""
        if atr_val <= 0 or entry <= 0:
            return False
        # 最大有利偏移（MFE）
        mfe = (td.get("highest", entry) - entry) if is_buy else (entry - td.get("lowest", entry))
        if mfe < atr_val * 0.3:
            return False  # 没走过足够盈利，不激活保本
        # 回到成本 ±0.05×ATR 以内（仅在盈利时触发，亏损时让硬止损兜底）
        return 0 <= current_profit <= atr_val * 0.05

    def filter_positions(self, positions: list[Position]) -> dict:
        """统计当前品种的多空持仓"""
        longs = [p for p in positions if p.order_type in ("OP_BUY", "BUY")]
        shorts = [p for p in positions if p.order_type in ("OP_SELL", "SELL")]
        return {"longs": longs, "shorts": shorts, "total": len(positions)}
