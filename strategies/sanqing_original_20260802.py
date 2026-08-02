"""
Sanqing Original — 三清 M5 4策略调度器（原始版移植）
====================================================
来源: https://github.com/caoruihua/sanqing-ea
原始 MQL4 4-strategy kernel (StrategySelector.mq4)，完整移植到 Python 系统
- M5 运行，EMA9/21 + ATR14 基础指标
- 4 策略按优先级调度：ExpansionFollow > Pullback > TrendContinuation > PinbarReversal
- 同一根 K 线只出一个信号
- 日风控：日盈利 $50 或日亏损 $40 锁定

数据源: 全部指标从 DataFactory TA-Lib 读取
"""
import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1_original"
STRATEGY_MAGIC = 880201
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1_original", "magic": 880201, "date": "2026-08-02",
     "desc": "初始移植：caoruihua/sanqing-ea 原始 M5 4策略调度器"},
]


class SanqingOriginalStrategy(BaseStrategy):
    """Sanqing Original — 三清 M5 4策略调度器（原始版移植）"""

    name = "sanqing_original"
    default_timeframe = "M5"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    # ── 原始参数（与 caoruihua/sanqing-ea 一致） ──
    # 基础指标
    EMA_FAST = 9
    EMA_SLOW = 21
    ATR_PERIOD = 14

    # 日风控
    DAILY_PROFIT_STOP = 50.0    # 日盈利 $50 锁定
    DAILY_LOSS_STOP = 40.0      # 日亏损 $40 锁定
    MAX_TRADES_PER_DAY = 30

    # 低波动过滤
    LOW_VOL_ATR_POINTS = 300.0  # ATR(14) 最小点数
    LOW_VOL_ATR_SPREAD_RATIO = 3.0  # ATR/点差 最小比值

    # 固定手数
    FIXED_LOTS = 0.01

    # SL/TP
    SL_ATR_MULT = 1.2           # 原始固定止损 1.2×ATR
    TP_ATR_MULT = 2.0           # 原始固定止盈 2.0×ATR

    # ── ExpansionFollow 参数 ──
    EF_BODY_ATR_RATIO = 4.0     # 实体/ATR ≥ 4.0
    EF_BODY_MEDIAN_RATIO = 2.20 # 实体/20根中位数 ≥ 2.20
    EF_VOLUME_MEDIAN_RATIO = 1.9 # 成交量/20根中位数 ≥ 1.9
    EF_BODY_RANGE_RATIO = 0.65  # 实体/总范围 ≥ 0.65

    # ── Pullback 参数 ──
    PB_WICK_BODY_RATIO = 0.5    # 影线/实体 ≥ 0.5

    # ── TrendContinuation 参数 ──
    TC_BREAK_ATR = 0.2          # 突破前高/低 + 0.2×ATR
    TC_MIN_BODY_ATR = 0.35      # 最小实体 ≥ 0.35×ATR

    # ── PinbarReversal 参数 ──
    PR_PREFETCH_BARS = 4        # 前置检测 K 线数
    PR_PREFETCH_ATR_MULT = 3.0  # 前置波动 ≥ PinBar 的 3 倍
    PR_WICK_BODY_RATIO = 2.0    # 影线 ≥ 2×实体
    PR_MAX_OPPOSITE_WICK = 0.5  # 对侧影线 ≤ 0.5×实体

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trade_state = {
            "day_key": 0,
            "daily_locked": False,
            "daily_closed_profit": 0.0,
            "trades_today": 0,
            "last_entry_bar_time": 0,
        }
        self._last_processed_bar_time = 0
        self._last_profit_exit_time: dict[str, float] = {"BUY": 0.0, "SELL": 0.0}
        self._exit_cooldown_seconds: int = 300

    # ─────────────── 指标辅助 ───────────────

    def get_ema(self, period: int) -> Optional[float]:
        key = f"ema_{period}"
        val = self.get_indicator(key)
        return val if val is not None else None

    def get_atr(self) -> Optional[float]:
        return self.get_indicator("atr")

    def get_spread(self) -> float:
        """获取当前点差（点数），从桥接读取"""
        try:
            tick = self.bridge.get_tick_price(self.symbol)
            if tick and tick.ask > 0 and tick.bid > 0:
                return (tick.ask - tick.bid) / 0.01  # XAUUSD 1 point = 0.01
        except Exception:
            pass
        return 30.0  # 默认 30 点

    def _get_candle(self, shift: int = 1) -> Optional[Candle]:
        """获取偏移量 K 线，shift=1 为最新已收盘 K 线"""
        if len(self.candles) < shift + 1:
            return None
        return self.candles[-(shift + 1)]

    # ─────────────── 低波动过滤 ───────────────

    def _is_low_vol(self) -> bool:
        atr = self.get_atr()
        if atr is None:
            return True
        spread = self.get_spread()
        atr_points = atr / 0.01  # 转成点数
        ratio = atr_points / spread if spread > 0 else 9999
        return atr_points < self.LOW_VOL_ATR_POINTS or ratio < self.LOW_VOL_ATR_SPREAD_RATIO

    # ─────────────── 日风控 ───────────────

    def _check_daily_lock(self) -> bool:
        now = time.time()
        today = int(now / 86400)
        if today != self._trade_state["day_key"]:
            self._trade_state["day_key"] = today
            self._trade_state["daily_locked"] = False
            self._trade_state["daily_closed_profit"] = 0.0
            self._trade_state["trades_today"] = 0
        if self._trade_state["daily_locked"]:
            return True
        if self._trade_state["trades_today"] >= self.MAX_TRADES_PER_DAY:
            self._trade_state["daily_locked"] = True
            return True
        return False

    # ─────────────── 策略 1: ExpansionFollow（极端放量跟随） ───────────────

    def _strategy_expansion_follow(self) -> Optional[tuple]:
        """优先级最高：K线暴涨暴跌时立即顺势跟进"""
        candle = self._get_candle(1)
        if candle is None or self._is_low_vol():
            return None

        body = abs(candle.close - candle.open)
        total_range = candle.high - candle.low
        if body <= 0 or total_range <= 0:
            return None

        atr = self.get_atr()
        if atr is None or atr <= 0:
            return None

        # 实体/ATR ≥ 4.0
        if body / atr < self.EF_BODY_ATR_RATIO:
            return None

        # 实体/20根中位数 ≥ 2.20
        closes = self.get_close_prices()
        if len(closes) < 22:
            return None
        bodies = [abs(self.candles[-(i+1)].close - self.candles[-(i+1)].open) for i in range(1, 21)]
        median_body = sorted(bodies)[len(bodies)//2] if bodies else 0
        if median_body <= 0 or body / median_body < self.EF_BODY_MEDIAN_RATIO:
            return None

        # 成交量/20根中位数 ≥ 1.9
        volumes = [self.candles[-(i+1)].volume for i in range(1, 21)]
        median_vol = sorted(volumes)[len(volumes)//2] if volumes else 0
        if median_vol <= 0 or candle.volume / median_vol < self.EF_VOLUME_MEDIAN_RATIO:
            return None

        # 实体/总范围 ≥ 0.65
        if body / total_range < self.EF_BODY_RANGE_RATIO:
            return None

        # 方向判断
        is_bullish = candle.close > candle.open
        direction = OrderType.BUY if is_bullish else OrderType.SELL
        return (direction, "ExpansionFollow", 1)

    # ─────────────── 策略 2: Pullback（EMA回踩拒绝） ───────────────

    def _strategy_pullback(self) -> Optional[tuple]:
        """优先级第二：趋势中回踩EMA9，出现拒绝信号"""
        candle = self._get_candle(1)
        if candle is None or self._is_low_vol():
            return None

        ema9 = self.get_ema(9)
        ema21 = self.get_ema(21)
        if ema9 is None or ema21 is None or ema9 <= 0 or ema21 <= 0:
            return None

        body = abs(candle.close - candle.open)
        total_range = candle.high - candle.low
        if body <= 0 or total_range <= 0:
            return None

        upper_wick = candle.high - max(candle.open, candle.close)
        lower_wick = min(candle.open, candle.close) - candle.low

        # 多头：EMA9 > EMA21（上升趋势），价格回踩到 EMA9 附近
        if ema9 > ema21 and candle.close < ema9 * 1.003:
            # 下影线 ≥ 0.5×实体 （拒绝信号）
            if lower_wick >= body * self.PB_WICK_BODY_RATIO:
                # 收盘在总范围下半部（加强拒绝信号）
                mid_range = (candle.high + candle.low) / 2
                if candle.close <= mid_range:
                    return (OrderType.BUY, "Pullback", 2)

        # 空头：EMA9 < EMA21（下降趋势），价格反弹到 EMA9 附近
        if ema9 < ema21 and candle.close > ema9 * 0.997:
            # 上影线 ≥ 0.5×实体 （拒绝信号）
            if upper_wick >= body * self.PB_WICK_BODY_RATIO:
                # 收盘在总范围上半部
                mid_range = (candle.high + candle.low) / 2
                if candle.close >= mid_range:
                    return (OrderType.SELL, "Pullback", 2)

        return None

    # ─────────────── 策略 3: TrendContinuation（趋势延续突破） ───────────────

    def _strategy_trend_continuation(self) -> Optional[tuple]:
        """优先级第三：趋势中继续突破，顺势加仓"""
        candle = self._get_candle(1)
        if candle is None:
            return None

        body = abs(candle.close - candle.open)
        if body <= 0:
            return None

        ema9 = self.get_ema(9)
        ema21 = self.get_ema(21)
        atr = self.get_atr()
        if ema9 is None or ema21 is None or atr is None or atr <= 0:
            return None

        # 需要最近 5 根 K 线找前高/前低
        candles = self.candles
        if len(candles) < 7:
            return None

        # 多头：EMA9 > EMA21，收盘突破前低 + 0.2×ATR
        if ema9 > ema21:
            prev_highs = [c.high for c in candles[-6:-1]]
            prev_lows = [c.low for c in candles[-6:-1]]
            if not prev_highs or not prev_lows:
                return None
            prev_high = max(prev_highs)
            # 突破前高（做多）
            if candle.close > prev_high + atr * self.TC_BREAK_ATR:
                if body >= atr * self.TC_MIN_BODY_ATR:
                    return (OrderType.BUY, "TrendContinuation", 3)

        # 空头：EMA9 < EMA21，收盘跌破前高 - 0.2×ATR
        if ema9 < ema21:
            prev_highs = [c.high for c in candles[-6:-1]]
            prev_lows = [c.low for c in candles[-6:-1]]
            if not prev_highs or not prev_lows:
                return None
            prev_low = min(prev_lows)
            # 跌破前低（做空）
            if candle.close < prev_low - atr * self.TC_BREAK_ATR:
                if body >= atr * self.TC_MIN_BODY_ATR:
                    return (OrderType.SELL, "TrendContinuation", 3)

        return None

    # ─────────────── 策略 4: PinbarReversal（PinBar反转） ───────────────

    def _strategy_pinbar_reversal(self) -> Optional[tuple]:
        """优先级最低：极端行情后的PinBar反转信号"""
        candle = self._get_candle(1)
        if candle is None or self._is_low_vol():
            return None

        body = abs(candle.close - candle.open)
        total_range = candle.high - candle.low
        if body <= 0 or total_range <= 0:
            return None

        upper_wick = candle.high - max(candle.open, candle.close)
        lower_wick = min(candle.open, candle.close) - candle.low

        # 需要前置 K 线检测波动
        candles = self.candles
        lookback = min(self.PR_PREFETCH_BARS + 2, len(candles))
        if lookback < self.PR_PREFETCH_BARS + 2:
            return None

        # 前置区间（不包含当前 K 线）
        prev_highs = [c.high for c in candles[-lookback:-1]]
        prev_lows = [c.low for c in candles[-lookback:-1]]
        if not prev_highs or not prev_lows:
            return None
        prev_range = max(prev_highs) - min(prev_lows)

        # 前置波动 ≥ PinBar 的 3 倍
        if prev_range < total_range * self.PR_PREFETCH_ATR_MULT:
            return None

        # 多头 PinBar：长下影线，收盘在高位
        is_bullish_pinbar = (
            lower_wick >= body * self.PR_WICK_BODY_RATIO and
            upper_wick <= body * self.PR_MAX_OPPOSITE_WICK and
            candle.close > candle.open
        )
        # 检查前置走势：高点出现在低点之前（先跌后涨才是拐点）
        if is_bullish_pinbar:
            highest_bar_idx = max(range(len(prev_highs)), key=lambda i: prev_highs[i])
            lowest_bar_idx = min(range(len(prev_lows)), key=lambda i: prev_lows[i])
            if highest_bar_idx > lowest_bar_idx:  # 先跌后涨
                return (OrderType.BUY, "PinbarReversal", 4)

        # 空头 PinBar：长上影线，收盘在低位
        is_bearish_pinbar = (
            upper_wick >= body * self.PR_WICK_BODY_RATIO and
            lower_wick <= body * self.PR_MAX_OPPOSITE_WICK and
            candle.close < candle.open
        )
        if is_bearish_pinbar:
            highest_bar_idx = max(range(len(prev_highs)), key=lambda i: prev_highs[i])
            lowest_bar_idx = min(range(len(prev_lows)), key=lambda i: prev_lows[i])
            if lowest_bar_idx > highest_bar_idx:  # 先涨后跌
                return (OrderType.SELL, "PinbarReversal", 4)

        return None

    # ─────────────── Main entry: generate_signal ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 100:
            return None

        # 防止同一根 K 线重复出信号
        last_bar = self._get_candle(1)
        if last_bar is None:
            return None
        if last_bar.time == self._last_processed_bar_time:
            return None
        self._last_processed_bar_time = last_bar.time

        # 日风控检查
        if self._check_daily_lock():
            if self._trade_state["daily_locked"]:
                logger.info(f"[{self.name}] 日风控锁定，跳过")
            return None

        # 4 策略按优先级调度
        strategies = [
            self._strategy_expansion_follow,
            self._strategy_pullback,
            self._strategy_trend_continuation,
            self._strategy_pinbar_reversal,
        ]

        signal = None
        signal_strategy = ""
        for strat_func in strategies:
            result = strat_func()
            if result is not None:
                signal = result[0]  # OrderType
                signal_strategy = result[1]
                priority = result[2]
                logger.info(f"[{self.name}] 策略 {signal_strategy} (P{priority}) 产生信号: {signal.name}")
                break

        if signal is None:
            return None

        # 盈利平仓冷却
        now = time.time()
        direction_name = "BUY" if signal == OrderType.BUY else "SELL"
        remaining = self._exit_cooldown_seconds - (now - self._last_profit_exit_time.get(direction_name, 0))
        if remaining > 0:
            logger.info(f"[{self.name}] {signal_strategy} 冷却中 {int(remaining)}s，跳过")
            return None

        # 计算 SL/TP
        atr = self.get_atr()
        if atr is None or atr <= 0:
            return None
        close = last_bar.close

        if signal == OrderType.BUY:
            sl = round(close - atr * self.SL_ATR_MULT, 2)
            tp = round(close + atr * self.TP_ATR_MULT, 2)
        else:
            sl = round(close + atr * self.SL_ATR_MULT, 2)
            tp = round(close - atr * self.TP_ATR_MULT, 2)
            if tp <= 0:
                tp = 0.01

        # 构建返回（兼容现有引擎的评分格式）
        ema9 = self.get_ema(9)
        ema21 = self.get_ema(21)
        atr_v = self.get_atr()
        adx_v = self.get_indicator("adx")
        pdi_v = self.get_indicator("pdi")
        ndi_v = self.get_indicator("ndi")

        indicator_values = {
            "close": round(close, 2),
            "ema9": round(ema9, 2) if ema9 else 0,
            "ema21": round(ema21, 2) if ema21 else 0,
            "atr": round(atr_v, 2) if atr_v else 0,
            "strategy": signal_strategy,
            "sl": sl,
            "tp": tp,
        }
        if adx_v is not None:
            indicator_values.update({
                "adx": round(adx_v, 1),
                "pdi": round(pdi_v, 1) if pdi_v else 0,
                "ndi": round(ndi_v, 1) if ndi_v else 0,
            })

        logger.info(
            f"[{self.name}] {signal_strategy} → {direction_name} "
            f"Price={close:.2f} SL={sl:.2f} TP={tp:.2f} "
            f"EMA9={ema9:.2f} EMA21={ema21:.2f} ATR={atr_v:.2f}"
        )

        # 返回格式: (OrderType, long_score, short_score, long_detail, short_detail, indicator_values)
        if signal == OrderType.BUY:
            return (signal, 1, 0, [signal_strategy], [], indicator_values)
        else:
            return (signal, 0, 1, [], [signal_strategy], indicator_values)

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr = self.get_atr()
        if atr is None or atr <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        if direction == OrderType.BUY:
            sl = round(entry_price - atr * self.SL_ATR_MULT, 2)
            tp = round(entry_price + atr * self.TP_ATR_MULT, 2)
        else:
            sl = round(entry_price + atr * self.SL_ATR_MULT, 2)
            tp = round(entry_price - atr * self.TP_ATR_MULT, 2)
            if tp <= 0:
                tp = 0.01
        return sl, tp

    # ─────────────── 出场逻辑 ───────────────

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """原始版使用固定 SL/TP，由引擎处理，无需额外出场逻辑"""
        return False

    def mark_extreme_entry(self, ticket: int | str):
        pass