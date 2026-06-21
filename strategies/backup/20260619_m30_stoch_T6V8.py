"""
M30 Stoch BB 双模策略 T6V8 — 震荡+趋势叠加 (趋势需Stoch交叉确认)
================================================================
- 震荡模式 (ADX<30 + BB≤1.0): Stoch 9-3-3 金叉/死叉 + EMA21
- 趋势模式 (ADX≥30 + DI主导 + Stoch金叉/死叉): EMA21方向对齐
- 出场: ATR 动态追踪止损 (Trailing Stop + Hard Stop)
- 双向交易 (Long / Short)
"""

import logging
import math
import time
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 660908
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 660908, "date": "2026-06-19", "desc": "初始版本: T6V8 双模 — 震荡Stoch+EMA21, 趋势DI+Stoch交叉+EMA21, ATR追踪止损"},
]


class M30StochT6V8Strategy(BaseStrategy):
    """M30 Stoch BB 双模策略 T6V8 — 震荡+趋势叠加 (趋势需Stoch交叉确认)"""

    name = "M30_stoch_T6V8"
    legacy_magics = []

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None

        # ── 震荡参数 ──
        self.stoch_k = 9
        self.stoch_d = 3
        self.stoch_slowing = 3
        self.bb_period = 20
        self.bb_std = 2.5
        self.ma_period = 21
        self.adx_range_threshold = 30
        self.bb_width_max = 1.0

        # ── 趋势参数 ──
        self.adx_trend_threshold = 30
        self.di_threshold = 10

        # ── 出场参数 ──
        self.p_trailing_atr = 1.5
        self.p_hard_atr = 2.0

        # 新闻事件风控
        self.tight_exit_mode: bool = False

        # 冷却
        self._last_profit_exit_time: dict[str, float] = {"BUY": 0.0, "SELL": 0.0}
        self._exit_cooldown_seconds: int = 1800

        # ATR/ADX cache
        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

    def refresh_data(self, count: int = 350):
        self._cached_atr_key = 0
        self._cached_atr_values = None
        super().refresh_data(count)

    # ═══════════════ Indicator helpers ═══════════════

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

    def _calc_stoch(self) -> Optional[dict]:
        """Stoch 9-3-3: return {curr_k, prev_k, curr_d, prev_d}"""
        closes = self.get_close_prices()
        highs = [c.high for c in self.candles]
        lows = [c.low for c in self.candles]
        n = len(closes)
        k_period = self.stoch_k
        if n < k_period + self.stoch_d + self.stoch_slowing + 3:
            return None

        raw_k = []
        for i in range(n - k_period - self.stoch_slowing - 1, n):
            hi = max(highs[i - k_period + 1:i + 1])
            lo = min(lows[i - k_period + 1:i + 1])
            rng = hi - lo
            raw = 50.0 if rng == 0 else (closes[i] - lo) / rng * 100
            raw_k.append(raw)

        smoothed = []
        for i in range(len(raw_k) - self.stoch_slowing + 1):
            smoothed.append(sum(raw_k[i:i + self.stoch_slowing]) / self.stoch_slowing)

        d_values = []
        for i in range(len(smoothed) - self.stoch_d + 1):
            d_values.append(sum(smoothed[i:i + self.stoch_d]) / self.stoch_d)

        curr_k = smoothed[-1]
        prev_k = smoothed[-2]
        curr_d = d_values[-1]
        prev_d = d_values[-2]
        return {
            "curr_k": curr_k, "prev_k": prev_k,
            "curr_d": curr_d, "prev_d": prev_d,
        }

    def _calc_bb(self) -> Optional[dict]:
        closes = self.get_close_prices()
        if len(closes) < self.bb_period:
            return None
        recent = closes[-self.bb_period:]
        sma = sum(recent) / self.bb_period
        variance = sum((c - sma) ** 2 for c in recent) / self.bb_period
        std = math.sqrt(variance)
        width = (sma + self.bb_std * std - (sma - self.bb_std * std)) / sma if sma > 0 else 0
        return {"sma": sma, "width": width}

    def _calc_adx(self) -> Optional[dict]:
        """ADX + DI via TA-Lib or pure Python"""
        highs = [c.high for c in self.candles]
        lows = [c.low for c in self.candles]
        closes = self.get_close_prices()
        period = 14
        if len(highs) < period + 2:
            return None
        try:
            import numpy as np
            import talib
            h = np.array(highs, dtype=float)
            l = np.array(lows, dtype=float)
            c = np.array(closes, dtype=float)
            adx_arr = talib.ADX(h, l, c, timeperiod=period)
            pdi_arr = talib.PLUS_DI(h, l, c, timeperiod=period)
            ndi_arr = talib.MINUS_DI(h, l, c, timeperiod=period)
            if (adx_arr[-1] is None or pdi_arr[-1] is None or ndi_arr[-1] is None or
                math.isnan(adx_arr[-1]) or math.isnan(pdi_arr[-1]) or math.isnan(ndi_arr[-1])):
                return None
            return {"adx": float(adx_arr[-1]), "pdi": float(pdi_arr[-1]), "ndi": float(ndi_arr[-1])}
        except ImportError:
            return self._calc_adx_wilder(highs, lows, closes, period)
        except Exception:
            return None

    def _calc_adx_wilder(self, highs: list, lows: list, closes: list, period: int = 14) -> Optional[dict]:
        n = len(highs)
        if n < period + 2:
            return None
        tr_list, plus_dm, minus_dm = [], [], []
        for i in range(1, n):
            h, l, pc = highs[i], lows[i], closes[i - 1]
            ph, pl = highs[i - 1], lows[i - 1]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            up = h - ph
            down = pl - l
            pdm = up if (up > down and up > 0) else 0
            mdm = down if (down > up and down > 0) else 0
            tr_list.append(tr)
            plus_dm.append(pdm)
            minus_dm.append(mdm)
        if len(tr_list) < period:
            return None
        atr = sum(tr_list[:period]) / period
        sum_pdm = sum(plus_dm[:period])
        sum_mdm = sum(minus_dm[:period])
        for i in range(period, len(tr_list)):
            atr = (atr * (period - 1) + tr_list[i]) / period
            sum_pdm = (sum_pdm * (period - 1) + plus_dm[i]) / period
            sum_mdm = (sum_mdm * (period - 1) + minus_dm[i]) / period
        pdi = 100 * sum_pdm / atr if atr > 0 else 0
        ndi = 100 * sum_mdm / atr if atr > 0 else 0
        dx = abs(pdi - ndi) / (pdi + ndi) * 100 if (pdi + ndi) > 0 else 0
        dx_list = [dx]
        for i in range(period, len(tr_list)):
            pdi = 100 * sum_pdm / atr if atr > 0 else 0
            ndi = 100 * sum_mdm / atr if atr > 0 else 0
            dx = abs(pdi - ndi) / (pdi + ndi) * 100 if (pdi + ndi) > 0 else 0
            dx_list.append(dx)
        adx = sum(dx_list[:period]) / period
        for i in range(period, len(dx_list)):
            adx = (adx * (period - 1) + dx_list[i]) / period
        return {"adx": adx, "pdi": pdi, "ndi": ndi}

    def _calc_atr_values(self, period: int = 20) -> Optional[list[float]]:
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

    def _calc_atr(self, period: int = 20) -> Optional[float]:
        vals = self._calc_atr_values(period)
        return vals[-1] if vals else None

    # ═══════════════ Signal generation ═══════════════

    def generate_signal(self) -> Optional[OrderType]:
        candles = self.candles
        if len(candles) < 251:
            return None

        closes = self.get_close_prices()
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        close = closes[-1]

        # ── Indicators ──
        ma_val = self._calc_ema(closes, self.ma_period)
        if ma_val is None:
            return None

        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return None

        adx_data = self._calc_adx()
        if adx_data is None:
            return None
        adx = adx_data["adx"]
        pdi = adx_data["pdi"]
        ndi = adx_data["ndi"]

        bb = self._calc_bb()
        if bb is None:
            return None
        bb_width = bb["width"]

        stoch = self._calc_stoch()
        if stoch is None:
            return None
        k_curr = stoch["curr_k"]
        k_prev = stoch["prev_k"]
        d_curr = stoch["curr_d"]
        d_prev = stoch["prev_d"]

        cross_up = (k_curr > d_curr) and (k_prev <= d_prev)
        cross_down = (k_curr < d_curr) and (k_prev >= d_prev)

        is_ranging = adx < self.adx_range_threshold
        is_trend = adx >= self.adx_trend_threshold and bb_width > self.bb_width_max / 2

        # ── 评分 ──
        long_score = 0
        short_score = 0
        long_factors = []
        short_factors = []

        # ① 震荡模式: Stoch 交叉 + EMA21
        if is_ranging and bb_width <= self.bb_width_max:
            if (k_curr < 20) and cross_up and (close < ma_val):
                long_score += 3
                long_factors.append("RNG-STOCH-L20-CUP")
                long_factors.append(f"K={k_curr:.0f}")
            if (k_curr > 80) and cross_down and (close > ma_val):
                short_score += 3
                short_factors.append("RNG-STOCH-G80-CDN")
                short_factors.append(f"K={k_curr:.0f}")

        # ② 趋势模式: DI 主导 + EMA21 + Stoch 交叉确认
        if is_trend:
            if (pdi - ndi) > self.di_threshold and close > ma_val and cross_up:
                long_score += 3
                long_factors.append("TREND-DI-UP")
                long_factors.append(f"DI={pdi - ndi:.0f}")
                long_factors.append("STOCH-CUP")
            elif (ndi - pdi) > self.di_threshold and close < ma_val and cross_down:
                short_score += 3
                short_factors.append("TREND-DI-DN")
                short_factors.append(f"DI={ndi - pdi:.0f}")
                short_factors.append("STOCH-CDN")

        now = time.time()

        # ── 冷却 ──
        if long_score >= 3:
            remaining = self._exit_cooldown_seconds - (now - self._last_profit_exit_time.get("BUY", 0))
            if remaining > 0:
                long_factors.append(f"COOLDOWN({int(remaining)}s)")
                long_score = 0
        if short_score >= 3:
            remaining = self._exit_cooldown_seconds - (now - self._last_profit_exit_time.get("SELL", 0))
            if remaining > 0:
                short_factors.append(f"COOLDOWN({int(remaining)}s)")
                short_score = 0

        signal = None
        if long_score >= 3:
            signal = OrderType.BUY
        elif short_score >= 3:
            signal = OrderType.SELL

        # ── Logging ──
        detail_parts = []
        if long_factors:
            detail_parts.append("LONG: " + " ".join(long_factors))
        if short_factors:
            detail_parts.append("SHORT: " + " ".join(short_factors))
        logger.info(
            f"[{self.name}] 评分: {long_score}/{short_score}  "
            f"{'LONG' if signal == OrderType.BUY else 'SELL' if signal == OrderType.SELL else '无信号'}  "
            f"ADX={adx:.1f} BBw={bb_width:.2f} K={k_curr:.0f} "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )

        bb_mid = bb["sma"]
        bb_range_val = (close - (bb_mid - bb["width"] * bb_mid / 2)) / (bb["width"] * bb_mid)
        lookback = min(20, len(closes))
        indicator_values = {
            "close": round(close, 2),
            "adx": round(adx, 1),
            "pdi": round(pdi, 1),
            "ndi": round(ndi, 1),
            "bb_width": round(bb_width, 3),
            "stoch_k": round(k_curr, 1),
            "stoch_d": round(d_curr, 1),
            "atr": round(atr_val, 2),
            "ema21": round(ma_val, 2),
            "regime": "trend" if is_trend else "range",
            "bb_position": round(bb_range_val, 3),
            "recent_high": round(max(closes[-lookback:]), 2),
            "recent_low": round(min(closes[-lookback:]), 2),
        }
        return (signal, long_score, short_score, long_factors, short_factors, indicator_values)

    # ═══════════════ Exit management ═══════════════

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        dist = atr_val * self.p_hard_atr
        if direction == OrderType.BUY:
            sl = round(entry_price - dist, 2)
            tp = round(entry_price + dist * 50, 2)
        else:
            sl = round(entry_price + dist, 2)
            tp = round(entry_price - dist * 50, 2)
            if tp <= 0:
                tp = 0
        return sl, tp

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """ATR 动态追踪止损 + 硬止损"""
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
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return False

        trail_mult = self.p_trailing_atr
        hard_mult = self.p_hard_atr
        pdd = self.profit_drawdown_pct

        if self.tight_exit_mode:
            trail_mult = 0.5
            hard_mult = 1.0
            pdd = 0.15

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - td["entry"]
            loss = td["entry"] - bid

            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)

            if current_profit > 0:
                if self.profit_drawdown_enabled and td["peak_profit"] > atr_val * 0.5:
                    profit_ratio = current_profit / td["peak_profit"]
                    if profit_ratio < (1 - pdd):
                        logger.info(f"[{self.name}] BUY ProfitStop ticket={ticket} profit=${current_profit:.2f}")
                        self._last_exit_detail = {"exit_type": "profit_drawdown"}
                        self._last_profit_exit_time["BUY"] = time.time()
                        del self._trail_data[ticket]
                        return True
                drawdown = td["highest"] - bid
                if drawdown > atr_val * trail_mult:
                    logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} drawdown=${drawdown:.2f}")
                    self._last_exit_detail = {"exit_type": "trail_stop"}
                    self._last_profit_exit_time["BUY"] = time.time()
                    del self._trail_data[ticket]
                    return True
            if loss > atr_val * hard_mult:
                logger.info(f"[{self.name}] BUY HardStop ticket={ticket} loss=${loss:.2f}")
                self._last_exit_detail = {"exit_type": "hard_stop"}
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            current_profit = td["entry"] - ask
            loss = ask - td["entry"]

            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)

            if current_profit > 0:
                if self.profit_drawdown_enabled and td["peak_profit"] > atr_val * 0.5:
                    profit_ratio = current_profit / td["peak_profit"]
                    if profit_ratio < (1 - pdd):
                        logger.info(f"[{self.name}] SELL ProfitStop ticket={ticket} profit=${current_profit:.2f}")
                        self._last_exit_detail = {"exit_type": "profit_drawdown"}
                        self._last_profit_exit_time["SELL"] = time.time()
                        del self._trail_data[ticket]
                        return True
                rally = ask - td["lowest"]
                if rally > atr_val * trail_mult:
                    logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} rally=${rally:.2f}")
                    self._last_exit_detail = {"exit_type": "trail_stop"}
                    self._last_profit_exit_time["SELL"] = time.time()
                    del self._trail_data[ticket]
                    return True
            if loss > atr_val * hard_mult:
                logger.info(f"[{self.name}] SELL HardStop ticket={ticket} loss=${loss:.2f}")
                self._last_exit_detail = {"exit_type": "hard_stop"}
                del self._trail_data[ticket]
                return True

        self._last_exit_detail = None
        return False
