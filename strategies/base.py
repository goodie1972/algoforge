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

        # K-line filter parameters (from RuntimeConfig → runtime_config.json, hot-reloadable)
        _coord = _RuntimeConfig().get_coordinator_config()
        self.position_gate_enabled: bool = _coord.get('position_gate_enabled', True)
        self.position_gate_lookback: int = _coord.get('position_gate_lookback', 60)
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

        # ── ① 位置门禁 + DI 跳过 ──
        if self.position_gate_enabled and direction:
            di_diff = 0
            if adx_data and adx_data.get("pdi") is not None:
                di_diff = abs(adx_data["pdi"] - adx_data["ndi"])
            else:
                # 数据库回退：加载 M30 计算 DI diff
                self._load_m30_data()
                if self._m30_candles:
                    m30_db = self._calc_m30_adx(14)
                    if m30_db:
                        di_diff = abs(m30_db["pdi"] - m30_db["ndi"])
            state["details"]["di_diff"] = round(di_diff, 1)

            if di_diff > self.di_gate_skip_threshold:
                state["details"]["pos_gate"] = f"DI跳过(diff={di_diff:.0f})"
            else:
                lookback = min(self.position_gate_lookback, len(self.candles))
                if lookback >= 2:
                    hi = max(c.high for c in self.candles[-lookback:])
                    lo = min(c.low for c in self.candles[-lookback:])
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
            self._load_m30_data()
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
        """加载 M30 K 线数据从本地 SQLite（供 H1 策略做急跌急涨检测）"""
        try:
            from data.database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
            ).fetchall()
            conn.close()
            self._m30_candles = [
                Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"[{self.name}] M30 data load failed: {e}")
            self._m30_candles = []

    def _calc_m30_adx(self, period: int = 14) -> Optional[dict]:
        """用 M30 K 线计算 ADX/DI（供门禁数据库回退使用），返回 {adx, pdi, ndi}"""
        c = self._m30_candles
        if not c or len(c) < period + 1:
            return None
        tr = [max(c[i].high - c[i].low,
                   abs(c[i].high - c[i-1].close),
                   abs(c[i].low - c[i-1].close)) for i in range(1, len(c))]
        up = [c[i].high - c[i-1].high for i in range(1, len(c))]
        dn = [c[i-1].low - c[i].low for i in range(1, len(c))]
        plus_dm = [u if u > d and u > 0 else 0 for u, d in zip(up, dn)]
        minus_dm = [d if d > u and d > 0 else 0 for u, d in zip(up, dn)]

        def rma(values: list, n: int) -> list:
            alpha = 1.0 / n
            result = [sum(values[:n]) / n]
            for v in values[n:]:
                result.append(result[-1] + alpha * (v - result[-1]))
            return result

        atr = rma(tr, period)
        pdi = rma(plus_dm, period)
        ndi = rma(minus_dm, period)
        dx = [abs(p - n) / (p + n) * 100 if (p + n) > 0 else 0
              for p, n in zip(pdi, ndi)]
        adx = rma(dx, period)
        if not adx:
            return None
        return {"adx": adx[-1], "pdi": pdi[-1], "ndi": ndi[-1]}

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

    def filter_positions(self, positions: list[Position]) -> dict:
        """统计当前品种的多空持仓"""
        longs = [p for p in positions if p.order_type in ("OP_BUY", "BUY")]
        shorts = [p for p in positions if p.order_type in ("OP_SELL", "SELL")]
        return {"longs": longs, "shorts": shorts, "total": len(positions)}
