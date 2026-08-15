"""
M30 Stoch 均值回归 (v11 A5 纯震荡)
====================================
T0: Stoch 9-3-3 K/D 交叉 + EMA21 + BB 宽度 ≤1.0
  入场: K<20 + 金叉 + close<EMA21 → BUY
        K>80 + 死叉 + close>EMA21 → SELL
  出场: Stoch 反向交叉 + misalign 检测 + ATR 硬止损
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 660901
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 660901, "date": "2026-06-21", "desc": "初始上线: v11 A5 Stoch+EMA21+BB 纯震荡"},
]


class MeanReversionM30Strategy(BaseStrategy):
    """M30 Stoch 均值回归 (T0 v11 A5 纯震荡)"""

    name = "stoch_m30"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)

        self.ma_period = 21
        self.sl_atr = 1.0
        self.adx_range_threshold = 30
        self.bb_slope_threshold = 0.01

        self._pos_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None

        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

    def refresh_data(self, count: int = 350):
        self._cached_atr_key = 0
        self._cached_atr_values = None
        super().refresh_data(count)

    # ─────────────── Indicator helpers ───────────────

    def _calc_ema(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period: return None
        k = 2.0 / (period + 1)
        ema = closes[0]
        for p in closes[1:]:
            ema = (p - ema) * k + ema
        return ema

    def _calc_bb(self) -> Optional[dict]:
        closes = self.get_close_prices()
        if len(closes) < 20: return None
        recent = closes[-20:]
        sma = sum(recent) / 20
        variance = sum((c - sma) ** 2 for c in recent) / 20
        std = math.sqrt(variance)
        return {"sma": sma, "upper": sma + 2.5 * std, "lower": sma - 2.5 * std,
                "width": 5.0 * std / sma if sma > 0 else 0}

    def _calc_stoch(self) -> Optional[dict]:
        candles = self.candles
        if len(candles) < 16: return None
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        n = len(closes)
        kp, sp, dp = 9, 3, 3
        raw_k = []
        for i in range(kp - 1, n):
            hi = max(highs[i - kp + 1:i + 1])
            lo = min(lows[i - kp + 1:i + 1])
            raw_k.append(50.0 if hi == lo else (closes[i] - lo) / (hi - lo) * 100)
        if len(raw_k) < sp + dp + 1: return None
        smooth_k = [sum(raw_k[i - sp + 1:i + 1]) / sp for i in range(sp - 1, len(raw_k))]
        if len(smooth_k) < dp + 1: return None
        return {
            "curr_k": smooth_k[-1], "prev_k": smooth_k[-2],
            "curr_d": sum(smooth_k[-dp:]) / dp,
            "prev_d": sum(smooth_k[-(dp + 1):-1]) / dp,
        }

    def _calc_atr_values(self, period: int = 20) -> Optional[list[float]]:
        cache_key = len(self.candles)
        if self._cached_atr_key == cache_key and self._cached_atr_values is not None:
            return self._cached_atr_values
        candles = self.candles
        if len(candles) < period + 2: return None
        tr_values = []
        for i in range(1, len(candles)):
            h = candles[i].high
            l_ = candles[i].low
            pc = candles[i - 1].close
            tr = max(h - l_, abs(h - pc), abs(l_ - pc))
            tr_values.append(tr)
        if len(tr_values) < period: return None
        atr_list = [sum(tr_values[:period]) / period]
        for i in range(period, len(tr_values)):
            atr_list.append((atr_list[-1] * (period - 1) + tr_values[i]) / period)
        self._cached_atr_values = atr_list
        self._cached_atr_key = cache_key
        return atr_list

    def _calc_atr(self, period: int = 20) -> Optional[float]:
        vals = self._calc_atr_values(period)
        return vals[-1] if vals and len(vals) > 0 else None

    def _calc_adx(self) -> Optional[dict]:
        candles = self.candles
        if len(candles) < 16: return None
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        try:
            import numpy as np
            import talib
            h = np.array(highs, dtype=float)
            l_ = np.array(lows, dtype=float)
            c = np.array(closes, dtype=float)
            adx_a = talib.ADX(h, l_, c, timeperiod=14)
            pdi_a = talib.PLUS_DI(h, l_, c, timeperiod=14)
            ndi_a = talib.MINUS_DI(h, l_, c, timeperiod=14)
            if any(np.isnan(x[-1]) for x in (adx_a, pdi_a, ndi_a)):
                return None
            return {"adx": float(adx_a[-1]), "pdi": float(pdi_a[-1]), "ndi": float(ndi_a[-1])}
        except ImportError:
            return self._calc_adx_wilder(highs, lows, closes)
        except Exception:
            return None

    def _calc_adx_wilder(self, highs: list, lows: list, closes: list, period: int = 14) -> Optional[dict]:
        n = len(highs)
        if n < period + 2: return None
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
        if len(tr_list) < period: return None
        atr_v = sum(tr_list[:period]) / period
        pdi_v = sum(plus_dm[:period]) / period
        ndi_v = sum(minus_dm[:period]) / period
        if atr_v <= 0: return None
        pdi_v = pdi_v / atr_v * 100
        ndi_v = ndi_v / atr_v * 100
        atr_s, pdi_s, ndi_s = [atr_v], [pdi_v], [ndi_v]
        for i in range(period, len(tr_list)):
            atr_s.append((atr_s[-1] * (period - 1) + tr_list[i]) / period)
            if atr_s[-1] > 0:
                pdi_s.append((pdi_s[-1] * (period - 1) + plus_dm[i] / atr_s[-1] * 100) / period)
                ndi_s.append((ndi_s[-1] * (period - 1) + minus_dm[i] / atr_s[-1] * 100) / period)
            else:
                pdi_s.append(pdi_s[-1])
                ndi_s.append(ndi_s[-1])
        dx = [abs(pdi_s[i] - ndi_s[i]) / max(pdi_s[i] + ndi_s[i], 0.001) * 100 for i in range(len(atr_s))]
        adx = [sum(dx[:period]) / period]
        for i in range(period, len(dx)):
            adx.append((adx[-1] * (period - 1) + dx[i]) / period)
        return {"adx": adx[-1], "pdi": pdi_s[-1], "ndi": ndi_s[-1]}

    def _bb_rising_ok(self, k_curr: float, k_prev: float) -> bool:
        closes = self.get_close_prices()
        if len(closes) < 21: return True
        sma20_prev = sum(closes[-21:-1]) / 20
        bb = self._calc_bb()
        if bb is None: return True
        bb_mid_slope = bb["sma"] - sma20_prev
        return (bb_mid_slope > self.bb_slope_threshold) == (k_curr > k_prev)

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 100:
            return None

        closes = self.get_close_prices()
        close = closes[-1]

        bb = self._calc_bb()
        if bb is None: return None

        stoch = self._calc_stoch()
        if stoch is None: return None

        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0: return None

        adx_data = self._calc_adx()
        if adx_data is None: return None

        ma_val = self._calc_ema(closes, self.ma_period)
        if ma_val is None: return None

        adx = adx_data['adx']
        k_curr = stoch["curr_k"]
        k_prev = stoch["prev_k"]
        d_curr = stoch["curr_d"]
        d_prev = stoch["prev_d"]

        cross_up_now = (k_curr > d_curr) and (k_prev <= d_prev)
        cross_down_now = (k_curr < d_curr) and (k_prev >= d_prev)
        is_ranging = adx < self.adx_range_threshold

        signal = None
        long_score, short_score = 0, 0
        long_factors, short_factors = [], []

        if is_ranging and bb["width"] <= 1.0:
            if (k_curr < 20) and cross_up_now and (close < ma_val):
                signal = OrderType.BUY
                long_score = 3
                long_factors = [f"K={k_curr:.0f}", "CROSS-UP"]
            elif (k_curr > 80) and cross_down_now and (close > ma_val):
                signal = OrderType.SELL
                short_score = 3
                short_factors = [f"K={k_curr:.0f}", "CROSS-DN"]

        iv = {
            "close": round(close, 2), "atr": round(atr_val, 2),
            "adx": round(adx, 1), "bb_width": round(bb["width"], 4),
            "k": round(k_curr, 1), "d": round(d_curr, 1),
            "ema21": round(ma_val, 2), "ranging": is_ranging,
        }

        logger.info(
            f"[{self.name}] K={k_curr:.1f} D={d_curr:.1f} "
            f"{'CROSS-UP' if cross_up_now else 'CROSS-DN' if cross_down_now else '--'} "
            f"ADX={adx:.1f} BB-W={bb['width']:.3f} "
            f"信号={'BUY' if signal == OrderType.BUY else 'SELL' if signal == OrderType.SELL else '无'}"
        )

        return (signal, long_score, short_score, long_factors, short_factors, iv)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        dist = atr_val * self.sl_atr
        if direction == OrderType.BUY:
            return round(entry_price - dist, 2), round(entry_price + dist * 50, 2)
        else:
            return round(entry_price + dist, 2), max(round(entry_price - dist * 50, 2), 0)

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._pos_data:
            self._pos_data[ticket] = {"entry_price": position.open_price}

        td = self._pos_data[ticket]
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return False

        closes = self.get_close_prices()
        close = closes[-1] if closes else (bid if is_buy else ask)
        ma_val = self._calc_ema(closes, self.ma_period)
        stoch = self._calc_stoch()
        entry_price = td["entry_price"]
        pnl_pts = (close - entry_price) if is_buy else (entry_price - close)

        # 硬止损
        if pnl_pts < -atr_val * self.sl_atr:
            del self._pos_data[ticket]; return True

        # Stoch 反向交叉出场
        if stoch and ma_val:
            k_curr = stoch["curr_k"]; k_prev = stoch["prev_k"]
            d_curr = stoch["curr_d"]; d_prev = stoch["prev_d"]
            cross_up = (k_curr > d_curr) and (k_prev <= d_prev)
            cross_down = (k_curr < d_curr) and (k_prev >= d_prev)

            if is_buy and cross_down and close >= ma_val:
                if k_curr >= 80 or not self._bb_rising_ok(k_curr, k_prev):
                    del self._pos_data[ticket]; return True
            if not is_buy and cross_up and close <= ma_val:
                if k_curr <= 20 or not self._bb_rising_ok(k_curr, k_prev):
                    del self._pos_data[ticket]; return True

        return False
