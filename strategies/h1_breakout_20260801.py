"""
H1 突破趋势策略 — v1.0
入场: 价格突破过去20根H1的区间 + ADX>25 确认趋势
出场: EMA20 追踪 + ATR 动态止损
数据源: 全部指标从 DataFactory TA-Lib 读取
"""
import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1.0"
STRATEGY_MAGIC = 880301
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1.0", "magic": 880301, "date": "2026-08-01",
     "desc": "H1区间突破: 突破20周期区间+ADX>25确认; EMA20追踪+ATR止损"},
]


class H1BreakoutStrategy(BaseStrategy):
    """H1 突破趋势策略"""

    name = "h1_breakout"
    display = "H1 突破趋势策略 — 区间突破+ADX确认"
    MAGIC = 880301
    default_timeframe = "H1"

    def __init__(self, bridge: MT4BridgeBase, **kwargs):
        super().__init__(bridge, **kwargs)
        self._trail_data: dict = {}
        self.timeframe = self.timeframe or "H1"

        # Entry params
        self.breakout_lookback = 20       # 区间回溯周期
        self.adx_threshold = 25           # ADX > 25 确认趋势
        self.atr_sl_mult = 1.5            # 止损 ATR 倍数
        self.atr_tp_mult = 3.0            # 止盈 ATR 倍数

        # Exit params (ADX 自适应)
        self.p_trail_chop = 1.0           # 震荡: 窄追踪
        self.p_trail_normal = 1.5         # 中等: 正常追踪
        self.p_trail_trend = 2.0          # 强趋势: 宽追踪
        self.p_profit_chop = 1.5          # 震荡: 窄止盈
        self.p_profit_normal = 2.5        # 中等: 正常止盈
        self.p_profit_trend = 3.5         # 强趋势: 宽止盈
        self.p_hard_atr = 1.5             # 硬止损 ATR 倍数

        # 同向保护
        self._min_hold_seconds = 600      # 最小持仓时间 10 分钟

    # ─────────────── 信号生成 ───────────────

    def generate_signal(self):
        candles = self.candles
        if len(candles) < self.breakout_lookback + 5:
            return (None, 0, 0, [], [], {})

        close = candles[-1].close
        high = candles[-1].high
        low = candles[-1].low

        # 区间计算
        lookback = self.breakout_lookback
        zone_high = max(c.high for c in candles[-lookback-1:-1])
        zone_low = min(c.low for c in candles[-lookback-1:-1])

        # 指标
        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        ema20 = self.get_indicator("ema_21")
        ema9 = self.get_indicator("ema_9")
        atr_val = self.get_indicator("atr")

        buy_score = 0
        sell_score = 0
        long_factors = []
        short_factors = []
        iv = {}

        # ── BUY 条件 ──
        # (1) 价格突破区间上沿
        if close > zone_high:
            long_factors.append("BREAKOUT-HIGH")
            buy_score += 4

        # (2) ADX > 25 确认趋势
        if adx is not None and adx > self.adx_threshold:
            long_factors.append(f"ADX-{adx:.0f}")
            buy_score += 3

        # (3) PDI > NDI 多头方向
        if pdi is not None and ndi is not None and pdi > ndi:
            long_factors.append("DI-BULL")
            buy_score += 2

        # (4) 价格在 EMA9 上方（短期趋势向上）
        if ema9 is not None and close > ema9:
            long_factors.append("EMA9-UP")
            buy_score += 1

        # (5) 价格在 EMA20 上方（中期趋势向上）
        if ema20 is not None and close > ema20:
            long_factors.append("EMA20-UP")
            buy_score += 1

        # ── SELL 条件 ──
        # (1) 价格突破区间下沿
        if close < zone_low:
            short_factors.append("BREAKOUT-LOW")
            sell_score += 4

        # (2) ADX > 25 确认趋势
        if adx is not None and adx > self.adx_threshold:
            short_factors.append(f"ADX-{adx:.0f}")
            sell_score += 3

        # (3) NDI > PDI 空头方向
        if pdi is not None and ndi is not None and ndi > pdi:
            short_factors.append("DI-BEAR")
            sell_score += 2

        # (4) 价格在 EMA9 下方（短期趋势向下）
        if ema9 is not None and close < ema9:
            short_factors.append("EMA9-DOWN")
            sell_score += 1

        # (5) 价格在 EMA20 下方（中期趋势向下）
        if ema20 is not None and close < ema20:
            short_factors.append("EMA20-DOWN")
            sell_score += 1

        # ── 位置门禁 ──
        lookback_60 = min(60, len(candles))
        recent_high = max(c.high for c in candles[-lookback_60:])
        recent_low = min(c.low for c in candles[-lookback_60:])
        price_position = (close - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5

        threshold = 6
        if price_position < 0.10 and sell_score >= threshold:
            short_factors.append("BOTTOM-GATE")
            sell_score = 0
        elif price_position > 0.90 and buy_score >= threshold:
            long_factors.append("TOP-GATE")
            buy_score = 0

        iv = {
            "close": round(close, 2),
            "zone_high": round(zone_high, 2),
            "zone_low": round(zone_low, 2),
            "adx": round(adx, 1) if adx else 0,
            "pdi": round(pdi, 1) if pdi else 0,
            "ndi": round(ndi, 1) if ndi else 0,
            "ema9": round(ema9, 2) if ema9 else 0,
            "ema20": round(ema20, 2) if ema20 else 0,
            "atr": round(atr_val, 2) if atr_val else 0,
            "price_position": round(price_position, 3),
        }

        signal = None
        if buy_score >= threshold:
            signal = OrderType.BUY
        elif sell_score >= threshold:
            signal = OrderType.SELL
        return (signal, buy_score, sell_score, long_factors, short_factors, iv)

    # ─────────────── SL/TP ───────────────

    def _get_adx_multipliers(self) -> tuple[float, float]:
        """ADX 自适应：返回 (trail_atr, profit_atr)"""
        adx = self.get_indicator("adx")
        if adx is None or adx <= 25:
            return self.p_trail_chop, self.p_profit_chop
        if adx > 35:
            return self.p_trail_trend, self.p_profit_trend
        return self.p_trail_normal, self.p_profit_normal

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        is_buy = direction == OrderType.BUY
        sl_dist = atr_val * self.p_hard_atr
        _, tp_mult = self._get_adx_multipliers()
        tp_dist = atr_val * tp_mult
        if is_buy:
            return round(entry_price - sl_dist, 2), round(entry_price + tp_dist, 2)
        else:
            tp = round(entry_price - tp_dist, 2)
            if tp <= 0:
                tp = 0
            return round(entry_price + sl_dist, 2), tp

    # ─────────────── 出场 ───────────────

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        self.refresh_data()

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "entry": position.open_price,
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "peak_profit": 0.0,
                "entry_ts": time.time(),
            }

        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return False

        trail_mult, _ = self._get_adx_multipliers()
        pnl_pts = (bid - td["entry"]) if is_buy else (td["entry"] - ask)
        loss_pts = (td["entry"] - bid) if is_buy else (ask - td["entry"])

        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        di_aligned = (is_buy and pdi is not None and ndi is not None and pdi > ndi) or \
                     (not is_buy and pdi is not None and ndi is not None and ndi > pdi)

        if is_buy:
            td["highest"] = max(td["highest"], bid)
        else:
            td["lowest"] = min(td["lowest"], ask)

        # (1) 硬止损
        if loss_pts > atr_val * self.p_hard_atr:
            logger.info(f"[{self.name}] HardStop ticket={ticket} loss={loss_pts:.2f}")
            del self._trail_data[ticket]
            return True

        # (2) 追踪止损（EMA20 追踪）
        ema20 = self.get_indicator("ema_21")
        if ema20 is not None:
            if is_buy and bid < ema20:
                logger.info(f"[{self.name}] TrailStop EMA20 ticket={ticket}")
                del self._trail_data[ticket]
                return True
            elif not is_buy and ask > ema20:
                logger.info(f"[{self.name}] TrailStop EMA20 ticket={ticket}")
                del self._trail_data[ticket]
                return True

        # (3) 利润回撤保护
        if pnl_pts > 0:
            td["peak_profit"] = max(td["peak_profit"], pnl_pts)
            if time.time() - td["entry_ts"] > self._min_hold_seconds:
                drawdown = (td["peak_profit"] - pnl_pts) / td["peak_profit"] if td["peak_profit"] > 0 else 0
                if drawdown > 0.50 and not di_aligned:
                    logger.info(f"[{self.name}] ProfitDrawdown ticket={ticket} drawdown={drawdown:.0%}")
                    del self._trail_data[ticket]
                    return True

        # (4) DI 翻转出场
        if pdi is not None and ndi is not None and time.time() - td["entry_ts"] > 300:
            current_candle = len(self.candles)
            last_flip_candle = td.get("_di_flip_candle", 0)
            di_flip_detected = (is_buy and ndi > pdi) or (not is_buy and pdi > ndi)
            if di_flip_detected:
                if last_flip_candle == 0:
                    td["_di_flip_candle"] = current_candle
                elif current_candle > last_flip_candle:
                    logger.info(f"[{self.name}] DI-Flip exit ticket={ticket}")
                    del self._trail_data[ticket]
                    return True

        return False