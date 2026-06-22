"""
M30 Stoch 均值回归 + 趋势叠加 (T6v8 独立版)
==========================================
v13 回测 T6v8 配置:
  - ADX<30 → v11 A5 原始震荡 (K/D交叉+EMA21+BB宽度)
  - ADX≥30 + DI主导 + EMA21 + Stoch交叉 → 趋势顺势单
  - 趋势出场: 宽SL 2.0 ATR + TP 4.0 ATR + ADX衰减 + DI反转

回测结果 (T6v8):
  M30:   98 笔 +$27.64 PF=1.24
  GC:    57 笔 +$45.12 PF=1.71
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v3"
STRATEGY_MAGIC = 660903
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 660903, "date": "2026-06-21", "desc": "初始上线: Stoch+T6v8 震荡+趋势双模, SL2.0 TP4.0"},
    {"version": "v2", "magic": 660903, "date": "2026-06-22", "desc": "ADX阈值 30→28, 更早切换趋势模式, 减少逆势开仓"},
    {"version": "v3", "magic": 660903, "date": "2026-06-22", "desc": "新增宽幅震荡子模式: BB width>2%时, 触轨+K极端(85/15)+DI交叉进场, 窄幅原版不变"},
]


class StochTrendM30Strategy(BaseStrategy):
    """M30 Stoch 均值回归 + 趋势叠加 (T6v8)"""

    name = "stoch_trend_m30"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)

        # v11 A5 参数
        self.ma_period = 21
        self.adx_range_threshold = 28
        self.bb_slope_threshold = 0.01

        # T6v8 趋势参数
        self.di_threshold = 10
        self.trend_sl_atr = 2.0
        self.trend_tp_atr = 4.0

        # 持仓跟踪
        self._pos_data: dict[int, dict] = {}
        self._pending_entry_info: dict = {}
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
            prev_pdi = float(pdi_a[-2]) if len(pdi_a) >= 2 and not np.isnan(pdi_a[-2]) else None
            prev_ndi = float(ndi_a[-2]) if len(ndi_a) >= 2 and not np.isnan(ndi_a[-2]) else None
            return {
                "adx": float(adx_a[-1]), "pdi": float(pdi_a[-1]), "ndi": float(ndi_a[-1]),
                "prev_pdi": prev_pdi, "prev_ndi": prev_ndi,
            }
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
        prev_pdi = pdi_s[-2] if len(pdi_s) >= 2 else None
        prev_ndi = ndi_s[-2] if len(ndi_s) >= 2 else None
        return {"adx": adx[-1], "pdi": pdi_s[-1], "ndi": ndi_s[-1],
                "prev_pdi": prev_pdi, "prev_ndi": prev_ndi}

    def _bb_rising_ok(self, k_curr: float, k_prev: float) -> bool:
        closes = self.get_close_prices()
        if len(closes) < 21: return True
        sma20_prev = sum(closes[-21:-1]) / 20
        bb = self._calc_bb()
        if bb is None: return True
        bb_mid_slope = bb["sma"] - sma20_prev
        k_rising = k_curr > k_prev
        bb_rising = bb_mid_slope > self.bb_slope_threshold
        return bb_rising == k_rising

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

        adx = adx_data['adx']; pdi = adx_data['pdi']; ndi = adx_data['ndi']
        k_curr = stoch["curr_k"]; k_prev = stoch["prev_k"]
        d_curr = stoch["curr_d"]; d_prev = stoch["prev_d"]

        cross_up_now = (k_curr > d_curr) and (k_prev <= d_prev)
        cross_down_now = (k_curr < d_curr) and (k_prev >= d_prev)
        is_ranging = adx < self.adx_range_threshold

        # BB 中轨斜率
        if len(closes) >= 21:
            sma20_prev = sum(closes[-21:-1]) / 20
            bb_mid_slope = bb["sma"] - sma20_prev
        else:
            bb_mid_slope = 0

        signal = None
        long_score, short_score = 0, 0
        long_factors, short_factors = [], []

        bb_width_threshold = 0.02  # 宽窄幅分界（黄金分割61.8%分位≈2%）

        # ── 震荡模式 ──
        if is_ranging:
            if bb["width"] <= bb_width_threshold:
                # 窄幅震荡 (原版 v11 A5)
                if (k_curr < 20) and cross_up_now and (close < ma_val):
                    signal = OrderType.BUY
                    long_score = 3
                    long_factors = [f"K={k_curr:.0f}", "CROSS-UP", "RNG"]
                    self._pending_entry_info = {"regime": "range", "adx": adx, "atr": atr_val}
                elif (k_curr > 80) and cross_down_now and (close > ma_val):
                    signal = OrderType.SELL
                    short_score = 3
                    short_factors = [f"K={k_curr:.0f}", "CROSS-DN", "RNG"]
                    self._pending_entry_info = {"regime": "range", "adx": adx, "atr": atr_val}
            else:
                # 宽幅震荡：触轨 + K极端 + DI交叉
                touch_upper = candles[-1].high >= bb["upper"]
                touch_lower = candles[-1].low <= bb["lower"]
                if len(candles) >= 2:
                    touch_upper = touch_upper or candles[-2].high >= bb["upper"]
                    touch_lower = touch_lower or candles[-2].low <= bb["lower"]

                prev_pdi = adx_data.get("prev_pdi")
                prev_ndi = adx_data.get("prev_ndi")
                di_death = prev_pdi is not None and prev_ndi is not None and prev_pdi >= prev_ndi and pdi < ndi
                di_golden = prev_pdi is not None and prev_ndi is not None and prev_pdi <= prev_ndi and pdi > ndi

                if touch_lower and k_curr < 15 and di_golden:
                    signal = OrderType.BUY
                    long_score = 3
                    long_factors = [f"K={k_curr:.0f}", "TOUCH-LOW", "DI-GOLD"]
                    self._pending_entry_info = {"regime": "range_wide", "adx": adx, "atr": atr_val}
                elif touch_upper and k_curr > 85 and di_death:
                    signal = OrderType.SELL
                    short_score = 3
                    short_factors = [f"K={k_curr:.0f}", "TOUCH-UP", "DI-DEATH"]
                    self._pending_entry_info = {"regime": "range_wide", "adx": adx, "atr": atr_val}

        # ── 趋势模式 (T6v8) ──
        if signal is None and (not is_ranging) and adx >= self.adx_range_threshold:
            if (pdi - ndi) > self.di_threshold and close > ma_val and cross_up_now:
                signal = OrderType.BUY
                long_score = 3
                long_factors = [f"ADX={adx:.0f}", f"DI+={pdi-ndi:.0f}", "TREND"]
                self._pending_entry_info = {"regime": "trend", "adx": adx, "atr": atr_val}
            elif (ndi - pdi) > self.di_threshold and close < ma_val and cross_down_now:
                signal = OrderType.SELL
                short_score = 3
                short_factors = [f"ADX={adx:.0f}", f"DI-={ndi-pdi:.0f}", "TREND"]
                self._pending_entry_info = {"regime": "trend", "adx": adx, "atr": atr_val}

        regime_label = "RNG" if is_ranging and bb["width"] <= bb_width_threshold else "RNG-W" if is_ranging else "TRD"
        iv = {
            "close": round(close, 2), "atr": round(atr_val, 2),
            "adx": round(adx, 1), "pdi": round(pdi, 1), "ndi": round(ndi, 1),
            "bb_width": round(bb["width"], 4),
            "k": round(k_curr, 1), "d": round(d_curr, 1),
            "ema21": round(ma_val, 2), "ranging": is_ranging,
        }

        logger.info(
            f"[{self.name}] K={k_curr:.1f} D={d_curr:.1f} "
            f"{'CROSS-UP' if cross_up_now else 'CROSS-DN' if cross_down_now else '--'} "
            f"ADX={adx:.1f} {regime_label} "
            f"信号={'BUY' if signal == OrderType.BUY else 'SELL' if signal == OrderType.SELL else '无'}"
        )

        return (signal, long_score, short_score, long_factors, short_factors, iv)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        regime = self._pending_entry_info.get("regime", "range")
        mult = self.trend_sl_atr if regime == "trend" else 1.0  # range/range_wide both use 1.0 ATR
        dist = atr_val * mult
        if direction == OrderType.BUY:
            return round(entry_price - dist, 2), round(entry_price + dist * 50, 2)
        else:
            return round(entry_price + dist, 2), max(round(entry_price - dist * 50, 2), 0)

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._pos_data:
            reg = self._pending_entry_info.get("regime", "range")
            self._pos_data[ticket] = {
                "entry_price": position.open_price,
                "regime": reg, "peak": position.open_price,
                "peak_profit": 0.0,
            }

        td = self._pos_data[ticket]
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return False

        closes = self.get_close_prices()
        ma_val = self._calc_ema(closes, self.ma_period)
        stoch = self._calc_stoch()
        adx_data = self._calc_adx()
        regime = td["regime"]
        entry_price = td["entry_price"]
        pnl_pts = (bid - entry_price) if is_buy else (entry_price - ask)

        # 硬止损
        sl_mult = self.trend_sl_atr if regime == "trend" else 1.0
        if pnl_pts < -atr_val * sl_mult:
            logger.info(f"[{self.name}] {regime.upper()} HardStop ticket={ticket}")
            self._last_exit_detail = {"exit_type": "hard_stop", "regime": regime}
            del self._pos_data[ticket]; return True

        # 更新峰值 + 利润峰值跟踪
        if is_buy:
            td["peak"] = max(td["peak"], bid)
            _cp = bid - entry_price
        else:
            td["peak"] = min(td["peak"], ask)
            _cp = entry_price - ask
        if abs(_cp) < atr_val * 10:
            td["peak_profit"] = max(td["peak_profit"], _cp)

        # 利润回撤止盈（通用，不限 regime）
        if _cp > 0 and self.profit_drawdown_enabled and td["peak_profit"] > atr_val * self.profit_drawdown_min_peak_atr:
            profit_ratio = _cp / td["peak_profit"]
            if profit_ratio < (1 - self.profit_drawdown_pct):
                logger.info(f"[{self.name}] ProfitStop ticket={ticket} profit=${_cp:.2f} peak=${td['peak_profit']:.2f}")
                self._last_exit_detail = {"exit_type": "profit_drawdown", "peak_profit": round(td["peak_profit"], 2), "current_profit": round(_cp, 2), "atr": round(atr_val, 2)}
                del self._pos_data[ticket]; return True

        # ── 震荡出场 (v11 A5，宽幅同规则) ──
        if regime in ("range", "range_wide") and stoch and ma_val:
            k_curr, k_prev = stoch["curr_k"], stoch["prev_k"]
            d_curr, d_prev = stoch["curr_d"], stoch["prev_d"]
            close = closes[-1] if closes else (bid if is_buy else ask)
            cross_up = (k_curr > d_curr) and (k_prev <= d_prev)
            cross_down = (k_curr < d_curr) and (k_prev >= d_prev)

            if is_buy and cross_down and close >= ma_val:
                if k_curr >= 80:
                    self._last_exit_detail = {"exit_type": "rng_long_main"}
                    del self._pos_data[ticket]; return True
                elif not self._bb_rising_ok(k_curr, k_prev):
                    self._last_exit_detail = {"exit_type": "rng_long_misalign"}
                    del self._pos_data[ticket]; return True
            if not is_buy and cross_up and close <= ma_val:
                if k_curr <= 20:
                    self._last_exit_detail = {"exit_type": "rng_short_main"}
                    del self._pos_data[ticket]; return True
                elif not self._bb_rising_ok(k_curr, k_prev):
                    self._last_exit_detail = {"exit_type": "rng_short_misalign"}
                    del self._pos_data[ticket]; return True

        # ── 趋势出场 ──
        if regime == "trend":
            # 从峰值回撤止盈 (trail = TP/2)
            trail_dist = atr_val * (self.trend_tp_atr * 0.5)
            if (is_buy and bid < td["peak"] - trail_dist) or (not is_buy and ask > td["peak"] + trail_dist):
                self._last_exit_detail = {"exit_type": "trend_trail"}
                del self._pos_data[ticket]; return True
            # TP
            if pnl_pts > atr_val * self.trend_tp_atr:
                self._last_exit_detail = {"exit_type": "trend_tp"}
                del self._pos_data[ticket]; return True
            # ADX 衰减
            if adx_data and adx_data["adx"] < 20:
                self._last_exit_detail = {"exit_type": "trend_adx_drop"}
                del self._pos_data[ticket]; return True
            # DI 反转
            if adx_data:
                if is_buy and adx_data["ndi"] > adx_data["pdi"]:
                    self._last_exit_detail = {"exit_type": "trend_di_flip_long"}
                    del self._pos_data[ticket]; return True
                elif not is_buy and adx_data["pdi"] > adx_data["ndi"]:
                    self._last_exit_detail = {"exit_type": "trend_di_flip_short"}
                    del self._pos_data[ticket]; return True

        self._last_exit_detail = None
        return False
