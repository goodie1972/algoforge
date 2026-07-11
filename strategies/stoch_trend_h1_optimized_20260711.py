"""
Stoch 回调顺势策略 (v7_optimized)
==================================
大师理论: ADX>20 趋势确认 + Stoch 超买超卖回调入场
XAUUSD 专用参数: Stoch(14,3,3) 更快信号响应

核心变化 vs v6:
  - ADX 阈值从 25 降到 20，在较弱趋势中也能产生信号
  - Stoch(21,5,3) → Stoch(14,3,3)，信号响应更快
  - AND 逻辑 → 加权评分系统（满分 8 分，4 分及格）

评分因子:
  - Stoch 极端区 (K<20 / K>80): +2
  - Stoch 金叉/死叉: +2
  - EMA21 方向对齐: +1
  - DI 方向对齐: +1
  - H4 趋势对齐: +1
  - M15 Stoch 对齐: +1
  阈值: 4 分

多周期架构:
  H4: EMA21 趋势方向过滤
  H1: ADX>20 + Stoch 评分 + DI 方向
  M15: Stoch(14,3,3) 精确入场时机

出场:
  - 硬止损: 2.0 ATR
  - ATR追踪止盈: 峰值回撤 1.5 ATR
  - 利润回撤止盈: 峰值利润回撤 N%
  - ADX<20: 趋势衰竭出场
  - DI反转: 趋势可能反转出场

版本履历:
  v6 (661201) — 初始多周期, Stoch(21,5,3)
  v7_optimized (661202) — 评分系统, Stoch(14,3,3), ADX>20
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v7_optimized"
STRATEGY_MAGIC = 661202
STRATEGY_LEGACY_MAGICS: list[int] = [661201]
STRATEGY_CHANGELOG = [
    {"version": "v6", "magic": 661201, "date": "2026-06-29",
     "desc": "初始: 多周期 H4→H1→M15, Stoch(21,5,3)@H1 + Stoch(14,3,3)@M15"},
    {"version": "v7_optimized", "magic": 661202, "date": "2026-07-11",
     "desc": "优化: 评分系统代替AND逻辑, Stoch(14,3,3), ADX>20, 阈值4/8"},
]


class StochTrendH1Optimized(BaseStrategy):
    """Stoch 多周期回调顺势策略 — v7_optimized 评分系统"""

    name = "stoch_trend_h1_optimized"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)

        # v7 参数（XAUUSD — 更快 Stoch 响应）
        self.stoch_k_period = 14         # 从 21 降到 14，信号更快
        self.stoch_slowing = 3           # 从 5 降到 3
        self.stoch_d_period = 3
        self.adx_threshold = 20          # 从 25 降到 20，在较弱趋势也产生信号
        self.sl_atr = 2.0                # 硬止损倍数
        self.trail_atr = 1.5             # ATR 追踪止盈距离

        # 评分系统参数
        self.score_threshold = 4         # 满分 8 分，4 分及格

        # 持仓跟踪
        self._pos_data: dict[int, dict] = {}
        self._pending_entry_info: dict = {}
        self._last_exit_detail: Optional[dict] = None

        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

        # 多周期数据（桥接实时加载，refresh_data 时刷新）
        self._h4_candles: list[Candle] = []
        self._m15_candles: list[Candle] = []

        # M15 Stoch 参数（用于精确入场时机）
        self.m15_stoch_k_period = 14
        self.m15_stoch_slowing = 3
        self.m15_stoch_d_period = 3

    def refresh_data(self, count: int = 350):
        self._cached_atr_key = 0
        self._cached_atr_values = None
        super().refresh_data(count)
        # 多周期实时数据（桥接直接拉，SQLite 有滞后不可用）
        try:
            raw_h4 = self.bridge.get_candles(self.symbol, "H4", 100)
            self._h4_candles = list(reversed(raw_h4))
        except Exception as e:
            logger.warning(f"[{self.name}] H4 bridge load failed: {e}")
            self._h4_candles = []
        try:
            raw_m15 = self.bridge.get_candles(self.symbol, "M15", 200)
            self._m15_candles = list(reversed(raw_m15))
        except Exception as e:
            logger.warning(f"[{self.name}] M15 bridge load failed: {e}")
            self._m15_candles = []

    def get_adx_data(self) -> Optional[dict]:
        return self._calc_adx()

    # ─────────────── Indicator helpers ───────────────

    def _calc_ema(self, closes: list[float], period: int):
        """EMA 计算"""
        if len(closes) < period:
            return None
        k = 2.0 / (period + 1)
        ema = closes[0]
        for i in range(1, period):
            ema = closes[i] * k + ema * (1 - k)
        avg = sum(closes[:period]) / period
        ema = avg
        for i in range(period, len(closes)):
            ema = closes[i] * k + ema * (1 - k)
        return ema

    def _calc_stoch(self) -> Optional[dict]:
        candles = self.candles
        if len(candles) < self.stoch_k_period + self.stoch_slowing + self.stoch_d_period + 1:
            return None
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        n = len(closes)
        kp, sp, dp = self.stoch_k_period, self.stoch_slowing, self.stoch_d_period
        raw_k = []
        for i in range(kp - 1, n):
            hi = max(highs[i - kp + 1:i + 1])
            lo = min(lows[i - kp + 1:i + 1])
            raw_k.append(50.0 if hi == lo else (closes[i] - lo) / (hi - lo) * 100)
        if len(raw_k) < sp + dp + 1:
            return None
        smooth_k = [sum(raw_k[i - sp + 1:i + 1]) / sp for i in range(sp - 1, len(raw_k))]
        if len(smooth_k) < dp + 1:
            return None
        return {
            "curr_k": smooth_k[-1], "prev_k": smooth_k[-2],
            "curr_d": sum(smooth_k[-dp:]) / dp,
            "prev_d": sum(smooth_k[-(dp + 1):-1]) / dp,
        }

    # ─────────────── H4 多周期方向 ───────────────

    def _calc_h4_trend(self) -> Optional[str]:
        """判断 H4 趋势方向（close vs EMA21），返回 'UP' | 'DOWN' | None"""
        c = self._h4_candles
        if len(c) < 26:
            return None
        closes = [x.close for x in c]
        ema21 = self._calc_ema(closes, 21)
        if ema21 is None:
            return None
        return 'UP' if c[-1].close > ema21 else 'DOWN' if c[-1].close < ema21 else None

    # ─────────────── M15 精确入场时机 ───────────────

    def _calc_m15_stoch(self) -> Optional[dict]:
        """M15 Stoch 计算（快参数，用于精确入场时机）"""
        candles = self._m15_candles
        n = len(candles)
        kp, sp, dp = self.m15_stoch_k_period, self.m15_stoch_slowing, self.m15_stoch_d_period
        if n < kp + sp + dp + 1:
            return None
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        raw_k = []
        for i in range(kp - 1, n):
            hi = max(highs[i - kp + 1:i + 1])
            lo = min(lows[i - kp + 1:i + 1])
            raw_k.append(50.0 if hi == lo else (closes[i] - lo) / (hi - lo) * 100)
        if len(raw_k) < sp + dp + 1:
            return None
        smooth_k = [sum(raw_k[i - sp + 1:i + 1]) / sp for i in range(sp - 1, len(raw_k))]
        if len(smooth_k) < dp + 1:
            return None
        return {
            "k": smooth_k[-1],
            "d": sum(smooth_k[-dp:]) / dp,
        }

    def _calc_adx(self) -> Optional[dict]:
        """标准 Wilder ADX/+DI/-DI（0-100 量纲），委托基类统一实现（与 talib 一致）"""
        return self.calc_adx_wilder(self.candles, 14)

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 100:
            return None

        closes = self.get_close_prices()
        close = closes[-1]

        stoch = self._calc_stoch()
        if stoch is None:
            return None

        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return None

        adx_data = self._calc_adx()
        if adx_data is None:
            return None

        ma_val = self.get_indicator("ema_21")
        if ma_val is None:
            return None

        adx = adx_data['adx']
        pdi = adx_data['pdi']
        ndi = adx_data['ndi']
        k_curr = stoch["curr_k"]
        k_prev = stoch["prev_k"]
        d_curr = stoch["curr_d"]
        d_prev = stoch["prev_d"]

        cross_up_now = (k_curr > d_curr) and (k_prev <= d_prev)
        cross_down_now = (k_curr < d_curr) and (k_prev >= d_prev)

        # ADX <= 20: 弱势震荡，不交易
        if adx <= self.adx_threshold:
            return None

        # ── H4 趋势方向（多周期过滤，桥接无数据时跳过） ──
        h4_trend = self._calc_h4_trend()
        if h4_trend is None:
            h4_tag = "H4:NODATA"
        else:
            h4_tag = f"H4:{h4_trend}"

        # ── M15 Stoch 精确入场时机 ──
        m15_stoch = self._calc_m15_stoch()
        m15_k = m15_stoch["k"] if m15_stoch else None

        # ── 评分系统（满分 8 分，阈值 4 分） ──
        long_score, short_score = 0, 0
        long_factors, short_factors = [], []

        # BUY 评分
        if k_curr < 20:
            long_score += 2
            long_factors.append("StochExtreme")
        if cross_up_now:
            long_score += 2
            long_factors.append("StochCross")
        if close > ma_val:
            long_score += 1
            long_factors.append("EMA21Dir")
        if pdi > ndi:
            long_score += 1
            long_factors.append("DIDir")
        if h4_trend == 'UP':
            long_score += 1
            long_factors.append("H4Trend")
        if m15_k is not None and m15_k < 30:
            long_score += 1
            long_factors.append("M15Align")

        # SELL 评分
        if k_curr > 80:
            short_score += 2
            short_factors.append("StochExtreme")
        if cross_down_now:
            short_score += 2
            short_factors.append("StochCross")
        if close < ma_val:
            short_score += 1
            short_factors.append("EMA21Dir")
        if ndi > pdi:
            short_score += 1
            short_factors.append("DIDir")
        if h4_trend == 'DOWN':
            short_score += 1
            short_factors.append("H4Trend")
        if m15_k is not None and m15_k > 70:
            short_score += 1
            short_factors.append("M15Align")

        signal = None
        if long_score >= self.score_threshold:
            signal = OrderType.BUY
            self._pending_entry_info = {"regime": "trend", "adx": adx, "atr": atr_val}
        elif short_score >= self.score_threshold:
            signal = OrderType.SELL
            self._pending_entry_info = {"regime": "trend", "adx": adx, "atr": atr_val}

        iv = {
            "close": round(close, 2), "atr": round(atr_val, 2),
            "adx": round(adx, 1), "pdi": round(adx_data['pdi'], 1),
            "ndi": round(adx_data['ndi'], 1),
            "k": round(k_curr, 1), "d": round(d_curr, 1),
            "ema21": round(ma_val, 2),
            "h4_trend": h4_trend or "NODATA",
            "m15_k": round(m15_k, 1) if m15_k is not None else None,
            "long_score": long_score,
            "short_score": short_score,
        }

        logger.info(
            f"[{self.name}] K={k_curr:.1f} D={d_curr:.1f} ADX={adx:.1f} "
            f"H4={h4_trend or 'N/A'} M15K={f'{m15_k:.0f}' if m15_k is not None else 'N/A'} "
            f"得分:多={long_score} 空={short_score} "
            f"{'BUY' if signal == OrderType.BUY else 'SELL' if signal == OrderType.SELL else '无'}"
        )

        return (signal, long_score, short_score, long_factors, short_factors, iv)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr_20")
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
            self._pos_data[ticket] = {
                "entry_price": position.open_price,
                "peak": position.open_price,
                "peak_profit": 0.0,
                "adx_entry": self._pending_entry_info.get("adx", 0),
            }

        td = self._pos_data[ticket]
        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return False

        adx_data = self._calc_adx()
        entry_price = td["entry_price"]
        pnl_pts = (bid - entry_price) if is_buy else (entry_price - ask)

        # 硬止损: 2.0 ATR
        if pnl_pts < -atr_val * self.sl_atr:
            logger.info(f"[{self.name}] HardStop ticket={ticket}")
            self._last_exit_detail = {"exit_type": "hard_stop"}
            del self._pos_data[ticket]
            return True

        # 更新峰值 + 利润峰值跟踪
        if is_buy:
            td["peak"] = max(td["peak"], bid)
            _cp = bid - entry_price
        else:
            td["peak"] = min(td["peak"], ask)
            _cp = entry_price - ask
        if abs(_cp) < atr_val * 10:
            td["peak_profit"] = max(td["peak_profit"], _cp)

        # 保本出场：走过≥0.3ATR盈利后回到成本附近
        mfe = (td["peak"] - entry_price) if is_buy else (entry_price - td["peak"])
        if mfe >= atr_val * 0.3 and 0 <= _cp <= atr_val * 0.05:
            logger.info(f"[{self.name}] {'BUY' if is_buy else 'SELL'} Breakeven ticket={ticket}")
            self._last_exit_detail = {"exit_type": "breakeven", "profit": round(_cp, 2)}
            del self._pos_data[ticket]
            return True

        # 利润回撤止盈
        if _cp > 0 and self.profit_drawdown_enabled and td["peak_profit"] > atr_val * self.profit_drawdown_min_peak_atr:
            profit_ratio = _cp / td["peak_profit"]
            _pdd = self.profit_drawdown_pct
            if adx_data and adx_data.get("adx", 0) > 25:
                _pdd = max(_pdd, 0.5)
            if profit_ratio < (1 - _pdd):
                logger.info(f"[{self.name}] ProfitStop ticket={ticket} profit=${_cp:.2f}")
                self._last_exit_detail = {"exit_type": "profit_drawdown",
                                          "peak_profit": round(td["peak_profit"], 2),
                                          "current_profit": round(_cp, 2)}
                del self._pos_data[ticket]
                return True

        # ATR追踪止盈: 峰值回撤 1.5 ATR
        if is_buy:
            if bid < td["peak"] - atr_val * self.trail_atr:
                self._last_exit_detail = {"exit_type": "trend_trail"}
                del self._pos_data[ticket]
                return True
        else:
            if ask > td["peak"] + atr_val * self.trail_atr:
                self._last_exit_detail = {"exit_type": "trend_trail"}
                del self._pos_data[ticket]
                return True

        # ADX < 20: 趋势衰竭
        if adx_data and adx_data["adx"] < 20:
            self._last_exit_detail = {"exit_type": "trend_adx_drop"}
            del self._pos_data[ticket]
            return True

        # DI反转: 趋势可能反转
        if adx_data:
            if is_buy and adx_data["ndi"] > adx_data["pdi"]:
                self._last_exit_detail = {"exit_type": "trend_di_flip"}
                del self._pos_data[ticket]
                return True
            elif not is_buy and adx_data["pdi"] > adx_data["ndi"]:
                self._last_exit_detail = {"exit_type": "trend_di_flip"}
                del self._pos_data[ticket]
                return True

        self._last_exit_detail = None
        return False

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
            direction = signal.get("direction", "BUY")
            adx = latest.get("adx", 20)
            pdi, ndi = latest.get("pdi", 15), latest.get("ndi", 15)
            stoch = latest.get("stoch_14_3_3") or {}
            stoch_k = stoch.get("k", 50)

            if direction == "BUY":
                if adx < 20:
                    return False
                if pdi <= ndi:
                    return False
                if stoch_k > 40:
                    return False
            else:
                if adx < 20:
                    return False
                if ndi <= pdi:
                    return False
                if stoch_k < 60:
                    return False
            return True
