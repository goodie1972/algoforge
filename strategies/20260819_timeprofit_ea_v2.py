"""
TimeProfit EA v2 — H2 趋势 + M5 入场 + 整数关口箱体（入场确认增强版）
====================================================================
来源: https://github.com/caoruihua/sanqing-ea-mt5
原始 MQL5 strategy (TimeProfitEA.mq5)，v2 升级入场逻辑：
- Pullback 回弹入场增加 M5 EMA10 触碰确认（bar.low <= m5Ema 做多）
- Breakout 突破入场要求前一根收盘在关口内（previousBar.close <= upperLevel）
- 其余参数与 v1_original 保持一致

数据源: 全部指标从 DataFactory TA-Lib 读取
"""
import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v2"
STRATEGY_MAGIC = 880203
STRATEGY_LEGACY_MAGICS: list[int] = [880202]
STRATEGY_CHANGELOG = [
    {"version": "v1_original", "magic": 880202, "date": "2026-08-02",
     "desc": "初始移植：caoruihua/sanqing-ea-mt5 TimeProfitEA"},
    {"version": "v2", "magic": 880203, "date": "2026-08-19",
     "desc": "入场增强：Pullback 回弹加 M5 EMA10 触碰确认，Breakout 突破加前一根收盘在关内判断"},
]


class TimeProfitEAStrategy(BaseStrategy):
    """TimeProfit EA v2 — H2 趋势 + M5 入场 + 整数关口箱体（入场确认增强版）"""

    name = "timeprofit_ea"
    default_timeframe = "M5"
    TIMEFRAME = "M5"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    # ── 趋势参数（H2 级别） ──
    TREND_FAST_EMA = 10
    TREND_SLOW_EMA = 30
    MIN_TREND_GAP_DOLLARS = 1.0   # 最小趋势 EMA 间距（美元）

    # ── M5 入场参数 ──
    M5_ENTRY_EMA = 10
    M5_ENTRY_EMA_CONFIRM = True   # v2: 回弹入场需价格触碰 M5 EMA10
    REQUIRE_CANDLE_DIRECTION = True   # 需要 M5 K线方向与趋势一致
    USE_PULLBACK_ENTRY = True         # 整数关口内回弹入场
    USE_BREAKOUT_ENTRY = True         # 整数关口突破追单
    PULLBACK_DISTANCE = 70.0          # 回弹区域距离关口边缘（美元）

    # ── 整数关口参数 ──
    LEVEL_STEP = 100.0                # 整数关口间隔（美元）
    NO_TRADE_DISTANCE = 4.0           # 关口附近禁入距离（美元）
    TP_BUFFER = 3.0                   # 关口前止盈距离（美元）
    MIN_TP_DISTANCE = 10.0            # 最小止盈距离（美元）

    # ── ATR 风控 ──
    ATR_PERIOD = 14
    ATR_STOP_MULT = 3.0               # 止损 = ATR × 3.0
    MIN_STOP_DISTANCE = 5.0           # 最小止损距离（美元）

    # ── 交易参数 ──
    FIXED_LOTS = 0.01
    COOLDOWN_MINUTES = 10             # 平仓后冷却时间
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
        """四舍五入到最近整数关口"""
        return round(price / step) * step

    def _get_levels(self, price: float) -> tuple[float, float]:
        """获取最近上下整数关口"""
        base = round(price / self.LEVEL_STEP) * self.LEVEL_STEP
        lower = base - self.LEVEL_STEP if base > price else base
        upper = base + self.LEVEL_STEP if base < price else base
        if lower >= upper:
            upper = lower + self.LEVEL_STEP
        return lower, upper

    def _get_trend_ema(self) -> Optional[float]:
        """获取 H2 级别 EMA 值"""
        try:
            from services.data_factory import get_cache
            h2_cache = get_cache("H2")
            if h2_cache and "ema_10" in h2_cache:
                return h2_cache.get("ema_10")
        except Exception:
            pass
        # 回退：M5 EMA 120 近似 H2 EMA 10
        return self.get_ema(120)

    # ─────────────── 趋势判断（H2 级别） ───────────────

    def _check_trend(self) -> tuple[Optional[str], float, float]:
        """检查 H2 趋势方向，返回 (direction, fast_ema, slow_ema)"""
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

    # ─────────────── 冷却检查 ───────────────

    def _is_cooldown_active(self) -> bool:
        now = time.time()
        remaining = self.COOLDOWN_MINUTES * 60 - (now - self._last_close_time)
        if remaining > 0:
            logger.info(f"[{self.name}] 冷却中，剩余 {int(remaining)}s")
            return True
        return False

    # ─────────────── 入场逻辑（v2 增强版） ───────────────

    def _check_pullback_entry(self, direction: str, price: float,
                              lower_level: float, upper_level: float) -> bool:
        """整数关口内回弹入场（v2: 增加 M5 EMA10 触碰确认）"""
        if direction == "UP":
            # 多头：价格从上方关口回弹到下方关口附近
            entry_zone = lower_level + self.PULLBACK_DISTANCE
            in_zone = lower_level + self.NO_TRADE_DISTANCE < price < entry_zone
            if not in_zone:
                return False
            # v2: 检查 M5 最低价是否触碰 M5 EMA10（回踩确认）
            if self.M5_ENTRY_EMA_CONFIRM:
                m5_ema = self.get_ema(self.M5_ENTRY_EMA)
                if m5_ema is not None:
                    candle = self._get_candle(1)
                    if candle is not None and candle.low > m5_ema:
                        logger.debug(f"[{self.name}] Pullback 多头未确认：最低价 {candle.low:.2f} 未触碰 M5 EMA{m5_ema:.2f}")
                        return False
            return True
        else:
            # 空头：价格从下方关口反弹到上方关口附近
            entry_zone = upper_level - self.PULLBACK_DISTANCE
            in_zone = entry_zone < price < upper_level - self.NO_TRADE_DISTANCE
            if not in_zone:
                return False
            # v2: 检查 M5 最高价是否触碰 M5 EMA10（反弹确认）
            if self.M5_ENTRY_EMA_CONFIRM:
                m5_ema = self.get_ema(self.M5_ENTRY_EMA)
                if m5_ema is not None:
                    candle = self._get_candle(1)
                    if candle is not None and candle.high < m5_ema:
                        logger.debug(f"[{self.name}] Pullback 空头未确认：最高价 {candle.high:.2f} 未触碰 M5 EMA{m5_ema:.2f}")
                        return False
            return True

    def _check_breakout_entry(self, direction: str, price: float,
                              lower_level: float, upper_level: float) -> bool:
        """整数关口突破追单（v2: 增加前一根收盘在关内判断）"""
        if direction == "UP":
            # 多头：突破上方关口
            if not (price > upper_level + self.NO_TRADE_DISTANCE):
                return False
            # v2: 前一根收盘应在关口内（真突破检测）
            prev_candle = self._get_candle(1)
            if prev_candle is not None and prev_candle.close > upper_level:
                logger.debug(f"[{self.name}] Breakout 多头未确认：前一根收盘 {prev_candle.close:.2f} 已在关口 {upper_level:.0f} 外")
                return False
            return True
        else:
            # 空头：跌破下方关口
            if not (price < lower_level - self.NO_TRADE_DISTANCE):
                return False
            # v2: 前一根收盘应在关口内
            prev_candle = self._get_candle(1)
            if prev_candle is not None and prev_candle.close < lower_level:
                logger.debug(f"[{self.name}] Breakout 空头未确认：前一根收盘 {prev_candle.close:.2f} 已在关口 {lower_level:.0f} 外")
                return False
            return True

    def _check_candle_direction(self, direction: str) -> bool:
        """检查 M5 K 线方向是否与趋势一致"""
        candle = self._get_candle(1)
        if candle is None:
            return False
        if direction == "UP":
            return candle.close > candle.open
        else:
            return candle.close < candle.open

    # ─────────────── 主入场 ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 100:
            return None

        # 冷却检查
        if self._is_cooldown_active():
            return None

        # 盈利平仓冷却
        now = time.time()
        for direction in ["BUY", "SELL"]:
            remaining = self._exit_cooldown_seconds - (now - self._last_profit_exit_time.get(direction, 0))
            if remaining > 0:
                logger.info(f"[{self.name}] {direction} 方向冷却 {int(remaining)}s，跳过")
                return None

        # 检查趋势
        trend, ema_fast, ema_slow = self._check_trend()
        if trend is None or trend == "NEUTRAL":
            logger.info(f"[{self.name}] 趋势不明显，跳过")
            return None

        # 获取当前价格
        last_candle = self._get_candle(0)
        if last_candle is None:
            return None
        price = last_candle.close

        # 获取整数关口
        lower_level, upper_level = self._get_levels(price)
        logger.info(f"[{self.name}] 趋势={trend} 价格={price:.2f} 关口={lower_level:.0f}/{upper_level:.0f}")

        # 检查价格是否在禁入区
        if abs(price - lower_level) < self.NO_TRADE_DISTANCE or abs(price - upper_level) < self.NO_TRADE_DISTANCE:
            logger.info(f"[{self.name}] 价格在关口禁入区，跳过")
            return None

        # 检查 K 线方向是否与趋势一致
        if self.REQUIRE_CANDLE_DIRECTION:
            if not self._check_candle_direction(trend):
                logger.info(f"[{self.name}] M5 K 线方向与趋势不一致，跳过")
                return None

        # 入场逻辑
        signal_comment = ""
        if trend == "UP":
            if self.USE_PULLBACK_ENTRY and self._check_pullback_entry("UP", price, lower_level, upper_level):
                signal_comment = f"TP_PULLBACK {price:.2f} [{lower_level:.0f}-{upper_level:.0f}]"
                logger.info(f"[{self.name}] 信号回弹做多: {signal_comment}")
                return (OrderType.BUY, 1, 0, ["PULLBACK-LONG"], [], {})
            if self.USE_BREAKOUT_ENTRY and self._check_breakout_entry("UP", price, lower_level, upper_level):
                signal_comment = f"TP_BREAKOUT {price:.2f} UP {upper_level:.0f}"
                logger.info(f"[{self.name}] 信号突破做多: {signal_comment}")
                return (OrderType.BUY, 1, 0, ["BREAKOUT-LONG"], [], {})
        else:
            if self.USE_PULLBACK_ENTRY and self._check_pullback_entry("DOWN", price, lower_level, upper_level):
                signal_comment = f"TP_PULLBACK {price:.2f} [{lower_level:.0f}-{upper_level:.0f}]"
                logger.info(f"[{self.name}] 信号回弹做空: {signal_comment}")
                return (OrderType.SELL, 0, 1, [], ["PULLBACK-SHORT"], {})
            if self.USE_BREAKOUT_ENTRY and self._check_breakout_entry("DOWN", price, lower_level, upper_level):
                signal_comment = f"TP_BREAKOUT {price:.2f} DN {lower_level:.0f}"
                logger.info(f"[{self.name}] 信号突破做空: {signal_comment}")
                return (OrderType.SELL, 0, 1, [], ["BREAKOUT-SHORT"], {})

        logger.debug(f"[{self.name}] 趋势 {trend} 但未触发入场条件")
        return None

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: str, entry_price: float, atr_val: float,
                          position_type: str = "entry") -> tuple[float, float]:
        """基于 ATR 和整数关口设置 SL/TP"""
        # SL: ATR 倍数
        stop_dist = max(atr_val * self.ATR_STOP_MULT, self.MIN_STOP_DISTANCE)
        if direction == "BUY":
            sl = entry_price - stop_dist
        else:
            sl = entry_price + stop_dist

        # TP: 下一个整数关口前 3 美元
        if direction == "BUY":
            tp_level = self._round_to_level(entry_price, self.LEVEL_STEP)
            if tp_level <= entry_price:
                tp_level += self.LEVEL_STEP
            tp = tp_level - self.TP_BUFFER
            if tp - entry_price < self.MIN_TP_DISTANCE:
                tp_level += self.LEVEL_STEP
                tp = tp_level - self.TP_BUFFER
        else:
            tp_level = self._round_to_level(entry_price, self.LEVEL_STEP)
            if tp_level >= entry_price:
                tp_level -= self.LEVEL_STEP
            tp = tp_level + self.TP_BUFFER
            if entry_price - tp < self.MIN_TP_DISTANCE:
                tp_level -= self.LEVEL_STEP
                tp = tp_level + self.TP_BUFFER

        if sl <= 0 or tp <= 0:
            return 0.01, 0.01
        return sl, tp

    # ─────────────── 出场逻辑 ───────────────

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """由引擎依据固定 SL/TP 处理出场"""
        return False

    def mark_extreme_entry(self, ticket: int | str):
        pass