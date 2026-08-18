"""
strategy基类 - 所有strategy继承此类
"""

import abc
import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, Position, OrderType
import config.settings as _settings
from core.runtime_config import RuntimeConfig as _RuntimeConfig

logger = logging.getLogger(__name__)


class BaseStrategy(abc.ABC):
    """strategy基类"""

    name = "base"

    # 旧版 magic 列表：engine在trailingPositions时会同时识别这些 magic，视为本strategy 单子
    # 用于version升级后auto接管旧 magic  Positions，避免产生孤儿单
    legacy_magics: list[int] = []

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        self.bridge = bridge
        self.symbol = _settings.SYMBOL
        self.magic = magic or _settings.MAGIC_NUMBER
        self.timeframe = timeframe or _settings.TIMEFRAME
        self.candles: list[Candle] = []
        self._trail_sl: dict[int, float] = {}
        # 最近一次Signal详情（供enginewrite DB）
        self._last_signal: Optional[dict] = None
        # 最近一次出场详情（exit_type/peak_profit 等，供enginewrite trades 表）
        self._last_exit_detail: Optional[dict] = None
        # 保本出场时间戳（按方向record，用于出场cooldown）
        self._last_profit_exit_time: dict[str, float] = {"BUY": 0.0, "SELL": 0.0}
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

        # News-Bias 阻塞开关（从 RuntimeConfig read，支持热load）
        self.block_long_when_bias_bearish: bool = _RuntimeConfig().get('block_long_when_bias_bearish') or False
        self.block_short_when_bias_bullish: bool = _RuntimeConfig().get('block_short_when_bias_bullish') or False

        # 保本出场延迟（s）：Entry后 N s内不激活保本，让硬止损兜底
        # 子类可在 __init__  覆盖此值，例如 M30 两w期 = 3600
        self.breakeven_delay_seconds: int = 0

    @property
    def all_magics(self) -> set[int]:
        """return本strategy所有 magic 号（主magic + 旧版legacy magic）"""
        return {self.magic} | set(self.legacy_magics)

    def refresh_data(self, count: int = 200):
        """从data工厂缓存read K 线data + 预calc指标"""
        try:
            from services.data_factory import get_cache
            cached = get_cache(self.timeframe)
            # check缓存 既有 candle 又有指标（rsi 做探针）
            if cached and "candles" in cached and "rsi" in cached:
                self.candles = cached.get("candles", [])
                self._cached_indicators = cached
                return
        except Exception:
            pass
        # fallback：从桥接get candle + 本地calc指标
        raw = self.bridge.get_candles(self.symbol, self.timeframe, count)
        self.candles = list(reversed(raw)) if raw else []
        if self.candles:
            try:
                from services.data_factory import _ta_only_indicators
                _ta = _ta_only_indicators(self.candles, self.timeframe)
                self._cached_indicators = _ta.get(self.candles[-1].time, {}) if _ta else {}
            except Exception:
                self._cached_indicators = {}

    def get_close_prices(self) -> list[float]:
        """get收盘价序列"""
        return [c.close for c in self.candles]

    def get_indicator(self, name: str):
        """从data工厂缓存read预calc指标"""
        if hasattr(self, '_cached_indicators') and self._cached_indicators:
            return self._cached_indicators.get(name)
        return None

    def _apply_kline_filters(self, result: tuple):
        """统一 K 线filter器（保留供外部调用，engine层使用 calc_gate_state）"""
        return result

    def calc_gate_state(self, direction: Optional[str], price: float,
                        adx_data: Optional[dict] = None) -> dict:
        """calcGate状态：positionGate + 急跌惩罚 + News-Bias。
        无论是否有Signal都calc，用于engine层统一拦截。
        return: {"blocked": bool, "reason": str, "details": dict}"""
        state = {"blocked": False, "reason": "", "details": {}}

        # 统一load M30 data（positionGate + 急跌急涨共用，避免重复查库）
        self._load_m30_data()

        # ── ① positionGate + DI skip ──
        if self.position_gate_enabled and direction:
            di_diff = 0
            if adx_data and adx_data.get("pdi") is not None:
                di_diff = abs(adx_data["pdi"] - adx_data["ndi"])
            else:
                # 从 DataFactory 缓存读取 DI 值
                pdi_v = self.get_indicator("pdi")
                ndi_v = self.get_indicator("ndi")
                if pdi_v is not None and ndi_v is not None:
                    di_diff = abs(pdi_v - ndi_v)
            state["details"]["di_diff"] = round(di_diff, 1)

            if di_diff > self.di_gate_skip_threshold:
                state["details"]["pos_gate"] = f"DIskip(diff={di_diff:.0f})"
            else:
                # 用 M30 40  candles算position（抗 spike range膨胀）
                m30_use = self._m30_candles
                if m30_use and len(m30_use) >= 2:
                    m30_lookback = min(self.position_gate_m30_lookback, len(m30_use))
                    hi = max(c.high for c in m30_use[-m30_lookback:])
                    lo = min(c.low for c in m30_use[-m30_lookback:])
                    pos = (price - lo) / (hi - lo) if hi > lo else 0.5
                    state["details"]["pos"] = round(pos, 3)
                    if direction == "SELL" and pos < self.position_gate_bottom:
                        state["blocked"] = True
                        state["reason"] = f"positionGate: bottom {pos:.1%}"
                        state["details"]["pos_gate"] = f"NO SELL({pos:.1%})"
                    elif direction == "BUY" and pos > self.position_gate_top:
                        state["blocked"] = True
                        state["reason"] = f"positionGate: top {pos:.1%}"
                        state["details"]["pos_gate"] = f"NO BUY({pos:.1%})"
                    else:
                        state["details"]["pos_gate"] = f"正常({pos:.1%})"

        # ── ② 急跌急涨惩罚 ──
        if self.rally_drop_enabled and direction and not state["blocked"]:
            if self._m30_candles:
                rd_lookback = min(self.rally_drop_lookback, len(self._m30_candles))
                if rd_lookback >= 2:
                    # 优先用传入  adx_data（实时桥接data），回退到 DataFactory 缓存
                    if adx_data and adx_data.get("adx"):
                        m30_adx = adx_data["adx"]
                    else:
                        m30_adx = self.get_indicator("adx")
                    state["details"]["m30_adx"] = round(m30_adx, 1) if m30_adx else 0
                    if m30_adx and m30_adx > self.rally_drop_adx_skip:
                        state["details"]["rally_drop"] = f"ADXskip({m30_adx:.0f})"
                    else:
                        m30_close = self._m30_candles[-1].close
                        rd_hi = max(c.high for c in self._m30_candles[-rd_lookback:])
                        rd_lo = min(c.low for c in self._m30_candles[-rd_lookback:])
                        drop_pct = (rd_hi - m30_close) / rd_hi * 100
                        rally_pct = (m30_close - rd_lo) / rd_lo * 100
                        if direction == "SELL" and drop_pct > self.rally_drop_threshold:
                            state["blocked"] = True
                            state["reason"] = f"急跌惩罚: 回落 {drop_pct:.1f}%"
                            state["details"]["rally_drop"] = f"NO SELL({drop_pct:.1f}%)"
                        elif direction == "BUY" and rally_pct > self.rally_drop_threshold:
                            state["blocked"] = True
                            state["reason"] = f"急涨惩罚: 上涨 {rally_pct:.1f}%"
                            state["details"]["rally_drop"] = f"NO BUY({rally_pct:.1f}%)"
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
                    state["reason"] = "News-Bias 偏空，NO BUY"
                    state["details"]["bias"] = "bearish-block-BUY"
                elif bias_dir == "bullish" and _block_short and direction == "SELL":
                    state["blocked"] = True
                    state["reason"] = "News-Bias 偏多，NO SELL"
                    state["details"]["bias"] = "bullish-block-SELL"
                else:
                    state["details"]["bias"] = bias_dir or "neutral"

        return state

    def _load_m30_data(self):
        """load M30 K 线data — 优先 SQLite，回退到桥接直接get"""
        try:
            from data.database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp DESC LIMIT 500"
            ).fetchall()
            conn.close()
            if rows:
                rows = list(reversed(rows))
                self._m30_candles = [
                    Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                    for r in rows
                ]
                return
        except Exception as e:
            logger.warning(f"[{self.name}] M30 DB load failed: {e}")

        # DB 无data → 直接从桥接get
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
        """load H1 K 线data — 优先 SQLite，回退到桥接直接get"""
        try:
            from data.database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='H1' ORDER BY timestamp DESC LIMIT 500"
            ).fetchall()
            conn.close()
            if rows:
                rows = list(reversed(rows))
                self._h1_candles = [
                    Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                    for r in rows
                ]
                return
        except Exception as e:
            logger.warning(f"[{self.name}] H1 DB load failed: {e}")

        # DB 无data → 直接从桥接get
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
        """load H4 K 线data — 优先 SQLite，回退到桥接直接get"""
        try:
            from data.database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='H4' ORDER BY timestamp DESC LIMIT 500"
            ).fetchall()
            conn.close()
            if rows:
                rows = list(reversed(rows))
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
        """H4 MAperiod趋-trend判断，return 'UP' / 'DOWN' / 'NEUTRAL'"""
        if len(self._h4_candles) < period:
            return 'NEUTRAL'
        closes = [c.close for c in self._h4_candles]
        ma = sum(closes[-period:]) / period
        return 'UP' if closes[-1] > ma else 'DOWN'

    def _get_h1_trend(self, period: int = 20) -> str:
        """H1 MA2period趋-trend判断，return 'UP' / 'DOWN' / 'NEUTRAL'"""
        if len(self._h1_candles) < period:
            return 'NEUTRAL'
        closes = [c.close for c in self._h1_candles]
        ma = sum(closes[-period:]) / period
        return 'UP' if closes[-1] > ma else 'DOWN'

    def _steep_ma_direction(self, period: int = 14, lookback: int = 5) -> str:
        """MA 陡峭度filter：calc EMA 斜率判断趋-trend强度
        period: EMA w期
        lookback: 斜率calc跨度（K线数）
        return 'UP' / 'DOWN' / 'NEUTRAL'
        """
        closes = self.get_close_prices()
        if closes is None or len(closes) < period + lookback:
            return 'NEUTRAL'
        try:
            import talib
            import numpy as np
            arr = np.array(closes, dtype=float)
            ema = talib.EMA(arr, timeperiod=period)
            if len(ema) < lookback + 1 or np.isnan(ema[-1]) or np.isnan(ema[-lookback-1]):
                return 'NEUTRAL'
            slope = (ema[-1] - ema[-lookback-1]) / ema[-lookback-1]
            if slope > 0.002:  # 0.2% 斜率threshold
                return 'UP'
            elif slope < -0.002:
                return 'DOWN'
            return 'NEUTRAL'
        except Exception:
            return 'NEUTRAL'

    @abc.abstractmethod
    def generate_signal(self):
        """
        generate交易Signal。
        return: tuple[Optional[OrderType], int, int, list, list, dict]
          - signal: BUY / SELL / None
          - score_long: 多头Score
          - score_short: 空头Score
          - factors_long: 多头因子列表
          - factors_short: 空头因子列表
          - indicator_values: 指标值字典（可 JSON serialize）
        """
        ...

    def on_tick(self) -> Optional[str]:
        """
        主循环调用：checkSignal并returnop描述
        return: op描述字符串，或 None
        """
        self.refresh_data()
        if len(self.candles) < 10:
            logger.warning(f"[{self.name}] Candle data insufficient: {len(self.candles)}")
            return None

        result = self.generate_signal()
        # 统一 K 线filter器（positionGate + 急跌急涨惩罚）
        if isinstance(result, tuple):
            result = self._apply_kline_filters(result)
        signal = result[0] if isinstance(result, tuple) else result

        # 存储Signal详情（供enginewritedata库）
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
            # 向后兼容：旧strategy只return OrderType
            self._last_signal = {
                "signal": signal.value if signal else None,
                "score_long": 0, "score_short": 0,
                "factors_long": [], "factors_short": [],
                "indicator_values": {},
            }

        if signal:
            return f"Signal: {signal.value}"
        return None

    def get_adx_data(self) -> Optional[dict]:
        """get本strategy  ADX data（含 +DI/-DI），供engineGate使用"""
        return None  # 子类覆盖

    def reload_config(self):
        """热重载configparam，子类覆盖（不覆盖 magic/timeframe，它们由 STRATEGY_POOL 管理）"""
        self.symbol = _settings.SYMBOL

        # 热重载 K 线filter器param（从 RuntimeConfig read，dashboard save优先）
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
        """保本出场：价格走过 ≥0.3×ATR 盈利后回到成本附近时close，防盈利变loss。
        子类在 check_ema20_exit   peak_profit update后调用。
        支持延迟激活：breakeven_delay_seconds > 0 时，Entry后该时间内不触发保本。"""
        if atr_val <= 0 or entry <= 0:
            return False
        # 时间Gate：Entry后 breakeven_delay_seconds s内不激活保本
        entry_time = td.get("entry_time", 0)
        if self.breakeven_delay_seconds > 0 and entry_time > 0:
            elapsed = time.time() - entry_time
            if elapsed < self.breakeven_delay_seconds:
                return False
        # max有利偏移（MFE）
        mfe = (td.get("highest", entry) - entry) if is_buy else (entry - td.get("lowest", entry))
        if mfe < atr_val * 0.3:
            return False  # 没走过足够盈利，不激活保本
        # 回到成本 ±0.05×ATR 以内（仅在盈利时触发，loss时让硬止损兜底）
        return 0 <= current_profit <= atr_val * 0.05

    def _run_exit_policy(self, td: dict, is_buy: bool, current_price: float,
                         atr_val: float, trail_mult: float, hard_mult: float,
                         pdd: float = None, update_peak_guard: bool = False,
                         **kwargs) -> tuple[bool, Optional[str], dict]:
        """通用出场策略执行器——提取 12+ 策略中重复的 check_ema20_exit 核心逻辑。

        执行顺序:
          1. 更新 peak (highest/lowest)
          2. 更新 peak_profit（可选 guard: abs(current_profit) < atr*10）
          3. 保本出场 (_check_breakeven_exit)
          4. profit_drawdown（盈利回撤保护）
          5. trail_stop（ATR 追踪止损）
          6. hard_stop（硬止损，仅 loss 阶段兜底）

        参数:
            td: 仓位跟踪数据 dict（子类维护，含 entry/highest/lowest/peak_profit）
            is_buy: True=多头, False=空头
            current_price: 当前价（bid for BUY, ask for SELL）
            atr_val: ATR 值
            trail_mult: ATR trailing 倍数
            hard_mult: 硬止损 ATR 倍数
            pdd: profit drawdown 百分比（None 用 self.profit_drawdown_pct 默认）
            update_peak_guard: True 时仅 abs(current_profit) < atr*10 才更新 peak_profit
            **kwargs: 额外数据（如 exit_type 前缀，供子类扩展日志用）

        return:
            (should_exit: bool, exit_type: Optional[str], exit_detail: dict)
            should_exit=True 表示应平仓，exit_type 为类型名（供子类写日志和 _last_exit_detail）
        """
        if pdd is None:
            pdd = self.profit_drawdown_pct

        entry = td["entry"]

        # ── 1. 更新 peak ──
        if is_buy:
            td["highest"] = max(td["highest"], current_price)
            current_profit = current_price - entry
            loss = entry - current_price
        else:
            td["lowest"] = min(td["lowest"], current_price)
            current_profit = entry - current_price
            loss = current_price - entry

        # ── 2. 更新 peak_profit ──
        if update_peak_guard:
            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)
        else:
            td["peak_profit"] = max(td["peak_profit"], current_profit)

        # ── 3. 保本出场 ──
        if self._check_breakeven_exit(td, current_profit, atr_val, entry, is_buy):
            return (True, "breakeven", {"profit": round(current_profit, 2)})

        # ── 4. profit_drawdown ──
        if current_profit > 0 and self.profit_drawdown_enabled:
            if td["peak_profit"] > atr_val * self.profit_drawdown_min_peak_atr:
                profit_ratio = current_profit / td["peak_profit"]
                if profit_ratio < (1 - pdd):
                    return (True, "profit_drawdown", {
                        "peak_profit": round(td["peak_profit"], 2),
                        "current_profit": round(current_profit, 2),
                        "atr": round(atr_val, 2),
                    })

        # ── 5. trail_stop ──
        if is_buy:
            drawdown = td["highest"] - current_price
            if drawdown > atr_val * trail_mult:
                return (True, "trail_stop", {
                    "drawdown": round(drawdown, 2), "atr": round(atr_val, 2),
                    "trail_mult": trail_mult,
                })
        else:
            rally = current_price - td["lowest"]
            if rally > atr_val * trail_mult:
                return (True, "trail_stop", {
                    "rally": round(rally, 2), "atr": round(atr_val, 2),
                    "trail_mult": trail_mult,
                })

        # ── 6. hard_stop ──
        if current_profit <= 0 and loss > atr_val * hard_mult:
            return (True, "hard_stop", {
                "loss": round(loss, 2), "atr": round(atr_val, 2),
                "hard_mult": hard_mult,
            })

        return (False, None, {})

    def filter_positions(self, positions: list[Position]) -> dict:
        """statscurrent品种 多空Positions"""
        longs = [p for p in positions if p.order_type in ("OP_BUY", "BUY")]
        shorts = [p for p in positions if p.order_type in ("OP_SELL", "SELL")]
        return {"longs": longs, "shorts": shorts, "total": len(positions)}
