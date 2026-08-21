"""
TimeProfit EA — H2趋-trend + M5Entry + 整数关口箱体（原始版移植）
============================================================
来源: https://github.com/caoruihua/sanqing-ea-mt5
原始 MQL5 strategy (TimeProfitEA.mq5)，完整移植到 Python 系统
- H2 趋-trend判断（EMA10/30）+ M5 Entryconfirm（EMA10）
- 100 美金整数关口箱体（Pullback 回弹 / Breakout 突破）
- ATR 3.0× 止损，整数关口前 3 美金take profit
- 10 min交易cooldown

data源: all指标从 DataFactory TA-Lib read
"""
import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1_original"
STRATEGY_MAGIC = 880202
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1_original", "magic": 880202, "date": "2026-08-02",
     "desc": "初始移植：caoruihua/sanqing-ea-mt5 TimeProfitEA"},
]


class TimeProfitEAStrategy(BaseStrategy):
    """TimeProfit EA — H2趋-trend + M5Entry + 整数关口箱体（原始版移植）"""

    name = "timeprofit_ea"
    default_timeframe = "M5"
    TIMEFRAME = "M5"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    # ── 趋-trendparam（H2 级别） ──
    TREND_FAST_EMA = 10
    TREND_SLOW_EMA = 30
    MIN_TREND_GAP_DOLLARS = 1.0   # min趋-trend EMA 间距（美元）

    # ── M5 Entryparam ──
    M5_ENTRY_EMA = 10
    REQUIRE_CANDLE_DIRECTION = True   # 需要 M5 K线方向 and 趋-trend一致
    USE_PULLBACK_ENTRY = True         # 整数关口内回弹Entry
    USE_BREAKOUT_ENTRY = True         # 整数关口突破追单
    PULLBACK_DISTANCE = 70.0          # 回弹区域距离关口边缘（美元）

    # ── 整数关口param ──
    LEVEL_STEP = 100.0                # 整数关口interval（美元）
    NO_TRADE_DISTANCE = 4.0           # 关口附近禁入距离（美元）
    TP_BUFFER = 3.0                   # 关口前take profit距离（美元）
    MIN_TP_DISTANCE = 10.0            # mintake profit距离（美元）

    # ── ATR risk ──
    ATR_PERIOD = 14
    ATR_STOP_MULT = 3.0               # 止损 = ATR × 3.0
    MIN_STOP_DISTANCE = 5.0           # min止损距离（美元）

    # ── 交易param ──
    FIXED_LOTS = 0.01
    COOLDOWN_MINUTES = 10             # close后cooldown时间
    MAX_SLIPPAGE = 30

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._last_close_time = 0
        self._had_open_position = False
        self._last_profit_exit_time: dict[str, float] = {"BUY": 0.0, "SELL": 0.0}
        self._exit_cooldown_seconds: int = 300

    # ─────────────── 辅助函数 ───────────────

    def get_ema(self, period: int) -> Optional[float]:
        key = f"ema_{period}"
        val = self.get_indicator(key)
        return val if val is not None else None

    def get_atr(self) -> Optional[float]:
        return self.get_indicator("atr")

    def _get_candle(self, shift: int = 1) -> Optional[Candle]:
        if len(self.candles) < shift + 1:
            return None
        return self.candles[-(shift + 1)]

    def _round_to_level(self, price: float, step: float = 100.0) -> float:
        """四舍五入到最近 整数关口"""
        return round(price / step) * step

    def _get_levels(self, price: float) -> tuple[float, float]:
        """get最近 上下整数关口"""
        # XAUUSD 价格如 2350.50，关口为 2300, 2400, 2500...
        base = round(price / self.LEVEL_STEP) * self.LEVEL_STEP
        lower = base - self.LEVEL_STEP if base > price else base
        upper = base + self.LEVEL_STEP if base < price else base
        if lower >= upper:
            upper = lower + self.LEVEL_STEP
        return lower, upper

    def _get_trend_ema(self) -> Optional[float]:
        """get H2 级别  EMA 值"""
        # 由于 DataFactory default按strategy timeframe 缓存，我们复用 M5   EMA
        # 在 H2 级别上，EMA10/30 ≈ M5 上  EMA 120/360
        # 使用 H2 缓存（如果可用）
        try:
            from services.data_factory import get_cache
            h2_cache = get_cache("H2")
            if h2_cache and "ema_10" in h2_cache:
                return h2_cache.get("ema_10")
        except Exception:
            pass
        # 回退：M5 EMA 120 近似 H2 EMA 10
        return self.get_ema(120)

    # ─────────────── 趋-trend判断（H2 级别） ───────────────

    def _check_trend(self) -> tuple[Optional[str], float, float]:
        """check H2 趋-trend方向，return (direction, fast_ema, slow_ema)"""
        # attempt从 H2 缓存read EMA
        try:
            from services.data_factory import get_cache
            h2 = get_cache("H2")
            if h2:
                ema_fast = h2.get("ema_10")
                ema_slow = h2.get("ema_30")
                if ema_fast is not None and ema_slow is not None and ema_fast > 0 and ema_slow > 0:
                    gap = abs(ema_fast - ema_slow)
                    if gap >= self.MIN_TREND_GAP_DOLLARS:
                        trend = "UP" if ema_fast > ema_slow else "DOWN"
                        return trend, ema_fast, ema_slow
                    return "NEUTRAL", ema_fast, ema_slow
        except Exception:
            pass

        # 回退：用 M5 EMA 120/360 近似 H2 EMA 10/30
        ema_fast = self.get_ema(120)
        ema_slow = self.get_ema(300)
        if ema_fast is not None and ema_slow is not None and ema_fast > 0 and ema_slow > 0:
            gap = abs(ema_fast - ema_slow)
            if gap >= self.MIN_TREND_GAP_DOLLARS:
                trend = "UP" if ema_fast > ema_slow else "DOWN"
                return trend, ema_fast, ema_slow
            return "NEUTRAL", ema_fast, ema_slow

        return None, 0, 0

    # ─────────────── cooldowncheck ───────────────

    def _is_cooldown_active(self) -> bool:
        now = time.time()
        remaining = self.COOLDOWN_MINUTES * 60 - (now - self._last_close_time)
        if remaining > 0:
            logger.info(f"[{self.name}] cooldown, remaining {int(remaining)}s")
            return True
        return False

    # ─────────────── Entry逻辑 ───────────────

    def _check_pullback_entry(self, direction: str, price: float, lower_level: float, upper_level: float) -> bool:
        """整数关口内回弹Entry"""
        if direction == "UP":
            # 多头：价格从上方关口回弹到下方关口附近
            entry_zone = lower_level + self.PULLBACK_DISTANCE
            return lower_level + self.NO_TRADE_DISTANCE < price < entry_zone
        else:
            # 空头：价格从下方关口rebound到上方关口附近
            entry_zone = upper_level - self.PULLBACK_DISTANCE
            return entry_zone < price < upper_level - self.NO_TRADE_DISTANCE

    def _check_breakout_entry(self, direction: str, price: float, lower_level: float, upper_level: float) -> bool:
        """整数关口突破追单"""
        if direction == "UP":
            # 多头：突破上方关口
            return price > upper_level + self.NO_TRADE_DISTANCE
        else:
            # 空头：跌破下方关口
            return price < lower_level - self.NO_TRADE_DISTANCE

    def _check_candle_direction(self, direction: str) -> bool:
        """check M5 K 线方向是否 and 趋-trend一致"""
        candle = self._get_candle(1)
        if candle is None:
            return False
        if direction == "UP":
            return candle.close > candle.open
        else:
            return candle.close < candle.open

    # ─────────────── Main entry ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 100:
            return None

        # cooldowncheck
        if self._is_cooldown_active():
            return None

        # 盈利closecooldown
        now = time.time()
        for direction in ["BUY", "SELL"]:
            remaining = self._exit_cooldown_seconds - (now - self._last_profit_exit_time.get(direction, 0))
            if remaining > 0:
                logger.info(f"[{self.name}] {direction} cooldown  {int(remaining)}s，skip")
                return None

        # check趋-trend
        trend, ema_fast, ema_slow = self._check_trend()
        if trend is None or trend == "NEUTRAL":
            logger.info(f"[{self.name}] counter-trend invalid, skip")
            return None

        # getcurrent价格
        last_candle = self._get_candle(0)
        if last_candle is None:
            return None
        price = last_candle.close

        # get整数关口
        lower_level, upper_level = self._get_levels(price)
        logger.info(f"[{self.name}] counter-trend={trend} price={price:.2f} key={lower_level:.0f}/{upper_level:.0f}")

        # check价格是否在禁入区
        if abs(price - lower_level) < self.NO_TRADE_DISTANCE or abs(price - upper_level) < self.NO_TRADE_DISTANCE:
            logger.info(f"[{self.name}] price in key no-entry zone, skip")
            return None

        # check K 线方向是否 and 趋-trend一致
        if self.REQUIRE_CANDLE_DIRECTION:
            if not self._check_candle_direction(trend):
                logger.info(f"[{self.name}] M5 candle dir and counter-trend mismatch, skip")
                return None

        # Entry逻辑
        signal_comment = ""
        signal_direction: Optional[OrderType] = None

        if trend == "UP":
            # 回弹Entry
            if self.USE_PULLBACK_ENTRY and self._check_pullback_entry("UP", price, lower_level, upper_level):
                signal_direction = OrderType.BUY
                signal_comment = "Pullback-Long"
            # 突破Entry
            elif self.USE_BREAKOUT_ENTRY and self._check_breakout_entry("UP", price, lower_level, upper_level):
                signal_direction = OrderType.BUY
                signal_comment = "Breakout-Long"
        else:  # DOWN
            if self.USE_PULLBACK_ENTRY and self._check_pullback_entry("DOWN", price, lower_level, upper_level):
                signal_direction = OrderType.SELL
                signal_comment = "Pullback-Short"
            elif self.USE_BREAKOUT_ENTRY and self._check_breakout_entry("DOWN", price, lower_level, upper_level):
                signal_direction = OrderType.SELL
                signal_comment = "Breakout-Short"

        if signal_direction is None:
            return None

        # calc SL/TP
        atr = self.get_atr()
        if atr is None or atr <= 0:
            return None

        sl_distance = max(atr * self.ATR_STOP_MULT, self.MIN_STOP_DISTANCE)
        # TP = 最近整数关口 - TP_BUFFER（Entry方向 reverse关口）
        if signal_direction == OrderType.BUY:
            tp_target = upper_level - self.TP_BUFFER
            sl = round(price - sl_distance, 2)
            tp = round(tp_target, 2)
        else:
            tp_target = lower_level + self.TP_BUFFER
            sl = round(price + sl_distance, 2)
            tp = round(tp_target, 2)

        tp_distance = abs(tp - price)
        if tp_distance < self.MIN_TP_DISTANCE:
            logger.info(f"[{self.name}] take profit distance {tp_distance:.2f} < min {self.MIN_TP_DISTANCE}，skip")
            return None

        # buildreturn
        indicator_values = {
            "close": round(price, 2),
            "trend": trend,
            "ema_fast": round(ema_fast, 2) if ema_fast else 0,
            "ema_slow": round(ema_slow, 2) if ema_slow else 0,
            "atr": round(atr, 2),
            "lower_level": round(lower_level, 2),
            "upper_level": round(upper_level, 2),
            "sl": sl,
            "tp": tp,
            "entry_type": signal_comment,
        }

        adx_v = self.get_indicator("adx")
        if adx_v is not None:
            indicator_values["adx"] = round(adx_v, 1)

        direction_name = "BUY" if signal_direction == OrderType.BUY else "SELL"
        logger.info(
            f"[{self.name}] {signal_comment} → {direction_name} "
            f"Price={price:.2f} SL={sl:.2f} TP={tp:.2f} "
            f"趋-trend={trend} 关口={lower_level:.0f}/{upper_level:.0f}"
        )

        # return格式: (OrderType, long_score, short_score, long_detail, short_detail, indicator_values)
        if signal_direction == OrderType.BUY:
            return (signal_direction, 1, 0, [signal_comment], [], indicator_values)
        else:
            return (signal_direction, 0, 1, [], [signal_comment], indicator_values)

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr = self.get_atr()
        if atr is None or atr <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        sl_distance = max(atr * self.ATR_STOP_MULT, self.MIN_STOP_DISTANCE)
        price = entry_price
        lower_level, upper_level = self._get_levels(price)

        if direction == OrderType.BUY:
            sl = round(price - sl_distance, 2)
            tp = round(upper_level - self.TP_BUFFER, 2)
        else:
            sl = round(price + sl_distance, 2)
            tp = round(lower_level + self.TP_BUFFER, 2)
            if tp <= 0:
                tp = 0.01
        return sl, tp

    # ─────────────── 出场逻辑 ───────────────

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """由engine candles据固定 SL/TP process出场"""
        return False

    def mark_extreme_entry(self, ticket: int | str):
        pass