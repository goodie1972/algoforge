"""
SanQing EA — H1 实盘策略
======================
- EMA9/21 趋势 + ATR14 评分系统
- 6因子评分 ≥5 触发 BUY/SELL
- ATR动态追踪止损出场
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class SanQingH1Strategy(BaseStrategy):
    """SanQing EA — H1 EMA9/21 + ATR14 评分系统"""

    name = "sanqing_h1"

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

        # Entry params
        self.score_threshold = 5

        # Exit params — 双重止盈：利润回撤25% + ATR移动止盈 + 硬止损
        self.p_trailing_atr = 1.0   # 回调超过 1 ATR 即止盈（原为 4.0）
        self.p_hard_atr = 2.0    # 硬止损 ATR×2（原为 2.5）
        self.profit_drawdown_pct = 0.25  # 利润回撤 25% 止盈

    def refresh_data(self, count: int = 200):
        self._cached_atr_key = 0
        self._cached_atr_values = None
        super().refresh_data(count)

    # ─────────────── Indicator helpers ───────────────

    def _calc_ema(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period:
            return None
        k = 2.0 / (period + 1)
        ema = closes[0]
        for p in closes[1:]:
            ema = (p - ema) * k + ema
        return ema

    def _calc_sma(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period:
            return None
        return sum(closes[-period:]) / period

    def _calc_atr_values(self, period: int = 14) -> Optional[list[float]]:
        cache_key = len(self.candles)
        if self._cached_atr_key == cache_key and self._cached_atr_values is not None:
            return self._cached_atr_values

        candles = self.candles
        if len(candles) < period + 2:
            return None
        tr_values = []
        for i in range(1, len(candles)):
            h, l, pc = candles[i].high, candles[i].low, candles[i - 1].close
            tr_values.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(tr_values) < period:
            return None
        atr_list = [sum(tr_values[:period]) / period]
        for i in range(period, len(tr_values)):
            atr_list.append((atr_list[-1] * (period - 1) + tr_values[i]) / period)
        self._cached_atr_values = atr_list
        self._cached_atr_key = cache_key
        return atr_list

    def _calc_atr(self, period: int = 14) -> Optional[float]:
        vals = self._calc_atr_values(period)
        return vals[-1] if vals else None

    def _get_opens(self) -> list[float]:
        return [c.open for c in self.candles]

    def _get_highs(self) -> list[float]:
        return [c.high for c in self.candles]

    def _get_lows(self) -> list[float]:
        return [c.low for c in self.candles]

    def _get_volumes(self) -> list[float]:
        return [c.volume for c in self.candles]

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[OrderType]:
        candles = self.candles
        if len(candles) < 60:
            return None

        closes = self.get_close_prices()
        highs = self._get_highs()
        lows = self._get_lows()
        opens_ = self._get_opens()
        volumes = self._get_volumes()

        close = closes[-1]
        high = highs[-1]
        low = lows[-1]
        volume = volumes[-1] if len(volumes) > 0 else 0

        # EMA9/21
        ema9 = self._calc_ema(closes, 9)
        ema21 = self._calc_ema(closes, 21)
        if ema9 is None or ema21 is None:
            return None
        ema9_p = self._calc_ema(closes[:-1], 9)
        ema21_p = self._calc_ema(closes[:-1], 21)

        uptrend = ema9 > ema21
        downtrend = ema9 < ema21
        cross_up = ema9_p is not None and ema21_p is not None and ema9_p <= ema21_p and ema9 > ema21
        cross_dn = ema9_p is not None and ema21_p is not None and ema9_p >= ema21_p and ema9 < ema21

        # ATR
        atr_val = self._calc_atr(14)
        if atr_val is None or atr_val <= 0:
            return None

        # Body analysis
        body = abs(close - opens_[-1])
        candle_range = high - low
        body_atr_ratio = body / atr_val if atr_val > 0 else 0

        # Body median ratio
        n = len(closes)
        recent_bodies = [abs(closes[j] - opens_[j]) for j in range(max(0, n - 21), n)]
        body_median = sorted(recent_bodies)[len(recent_bodies) // 2] if recent_bodies else 1
        body_median_ratio = body / body_median if body_median > 0 else 0
        prev_bodies = [abs(closes[j] - opens_[j]) for j in range(max(0, n - 6), n - 1)]
        prev_body_max = max(prev_bodies) if prev_bodies else 1

        # Volume average
        avg_vol = sum(volumes[max(0, n - 21):n]) / min(20, n) if n >= 5 else 0

        # ── BUY scoring ──
        buy_score = 0
        if uptrend:
            buy_score += 2
        elif cross_up:
            buy_score += 1
        if low <= ema9 * 1.002 and close > ema9:
            buy_score += 2
        if body_atr_ratio > 1.0:
            buy_score += 1
        if avg_vol > 0 and volume > avg_vol * 1.3:
            buy_score += 1
        if (body_median_ratio >= 1.5 and body / prev_body_max >= 1.5
                and candle_range > 0 and body / candle_range >= 0.5):
            buy_score += 2

        # ── SELL scoring ──
        sell_score = 0
        if downtrend:
            sell_score += 2
        elif cross_dn:
            sell_score += 1
        if high >= ema9 * 0.998 and close < ema9:
            sell_score += 2
        if body_atr_ratio > 1.0:
            sell_score += 1
        if avg_vol > 0 and volume > avg_vol * 1.3:
            sell_score += 1
        if (body_median_ratio >= 1.5 and body / prev_body_max >= 1.5
                and candle_range > 0 and body / candle_range >= 0.5):
            sell_score += 2

        logger.info(
            f"[{self.name}] 评分: BUY={buy_score} SELL={sell_score} "
            f"Price={close:.2f} EMA9={ema9:.2f} EMA21={ema21:.2f} ATR={atr_val:.2f}"
        )

        if buy_score >= self.score_threshold:
            return OrderType.BUY
        if sell_score >= self.score_threshold:
            return OrderType.SELL
        return None

    # ─────────────── Trend-aware exit multipliers ───────────────

    def _get_trend(self) -> str:
        """EMA9/21 trend: 'UP' / 'DOWN' / 'NEUTRAL'"""
        closes = self.get_close_prices()
        ema9 = self._calc_ema(closes, 9)
        ema21 = self._calc_ema(closes, 21)
        if ema9 is None or ema21 is None:
            return 'NEUTRAL'
        return 'UP' if ema9 > ema21 else 'DOWN'

    def _get_exit_multipliers(self, is_buy: bool) -> tuple[float, float]:
        trend = self._get_trend()
        if trend == 'UP':
            return (1.5, 3.0) if is_buy else (1.0, 2.0)
        elif trend == 'DOWN':
            return (1.0, 2.0) if is_buy else (1.5, 3.0)
        else:
            return (1.2, 2.5)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self._calc_atr(14)
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        _, hard_mult = self._get_exit_multipliers(direction == OrderType.BUY)
        dist = atr_val * hard_mult
        if direction == OrderType.BUY:
            return round(entry_price - dist, 2), round(entry_price + dist * 50, 2)
        else:
            return round(entry_price + dist, 2), round(entry_price - dist * 50, 2)

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """双重止盈：利润回撤止盈 + ATR移动止盈 + 硬止损"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
                "peak_profit": 0.0,
            }

        td = self._trail_data[ticket]
        atr_val = self._calc_atr(14)
        if atr_val is None or atr_val <= 0:
            return False

        trail_mult, hard_mult = self._get_exit_multipliers(is_buy)

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            drawdown = td["highest"] - bid
            loss = td["entry"] - bid
            current_profit = bid - td["entry"]
            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)

            # ① 利润回撤止盈
            if td["peak_profit"] > atr_val * 0.5:
                profit_ratio = current_profit / td["peak_profit"]
                if profit_ratio < (1 - self.profit_drawdown_pct):
                    logger.info(
                        f"[{self.name}] BUY ProfitStop ticket={ticket} "
                        f"profit ${current_profit:.2f} peak ${td['peak_profit']:.2f}"
                    )
                    del self._trail_data[ticket]
                    return True

            # ② ATR 移动止盈
            if drawdown > atr_val * trail_mult:
                logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} drawdown={drawdown:.2f} trail={trail_mult}")
                del self._trail_data[ticket]
                return True

            # ③ 硬止损
            if loss > atr_val * hard_mult:
                logger.info(f"[{self.name}] BUY HardStop ticket={ticket} loss={loss:.2f} hard={hard_mult}")
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            rally = ask - td["lowest"]
            loss = ask - td["entry"]
            current_profit = td["entry"] - ask
            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)

            # ① 利润回撤止盈
            if td["peak_profit"] > atr_val * 0.5:
                profit_ratio = current_profit / td["peak_profit"]
                if profit_ratio < (1 - self.profit_drawdown_pct):
                    logger.info(
                        f"[{self.name}] SELL ProfitStop ticket={ticket} "
                        f"profit ${current_profit:.2f} peak ${td['peak_profit']:.2f}"
                    )
                    del self._trail_data[ticket]
                    return True

            # ② ATR 移动止盈
            if rally > atr_val * trail_mult:
                logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} rally={rally:.2f} trail={trail_mult}")
                del self._trail_data[ticket]
                return True

            # ③ 硬止损
            if loss > atr_val * hard_mult:
                logger.info(f"[{self.name}] SELL HardStop ticket={ticket} loss={loss:.2f} hard={hard_mult}")
                del self._trail_data[ticket]
                return True

        return False
