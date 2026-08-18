"""
Stoch 回调with-trendstrategy (v7_optimized)
==================================
大师理论: ADX>20 趋-trendconfirm + Stoch 超买超卖回调Entry
XAUUSD 专用param: Stoch(14,3,3) 更快Signal响应

核心变化 vs v6:
  - ADX threshold从 25 降到 20，在较弱趋-trend 也能产生Signal
  - Stoch(21,5,3) → Stoch(14,3,3)，Signal响应更快
  - AND 逻辑 → 加权Score系统（满分 8 分，4 分及格）

Score因子:
  - Stoch 极端区 (K<20 / K>80): +2
  - Stoch 金叉/死叉: +2
  - EMA21 方向对齐: +1
  - DI 方向对齐: +1
  - H4 趋-trend对齐: +1
  - M15 Stoch 对齐: +1
  threshold: 4 分

多w期架构:
  H4: EMA21 趋-trend方向filter
  H1: ADX>20 + Stoch Score + DI 方向
  M15: Stoch(14,3,3) 精确Entry时机

出场:
  - 硬止损: 2.0 ATR
  - ATRtrailingtake profit: 峰值drawdown 1.5 ATR
  - profitdrawdowntake profit: 峰值profitdrawdown N%
  - ADX<20: 趋-trend衰竭出场
  - DI反转: 趋-trend可能反转出场

version履历:
  v6 (661201) — 初始多w期, Stoch(21,5,3)
  v7_optimized (661202) — Score系统, Stoch(14,3,3), ADX>20

data源: all指标从 DataFactory TA-Lib read
"""

import logging
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy
from services.data_factory import get_cache

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v7_optimized"
STRATEGY_MAGIC = 661202
STRATEGY_LEGACY_MAGICS: list[int] = [661201]
STRATEGY_CHANGELOG = [
    {"version": "v6", "magic": 661201, "date": "2026-06-29",
     "desc": "初始: 多w期 H4→H1→M15, Stoch(21,5,3)@H1 + Stoch(14,3,3)@M15"},
    {"version": "v7_optimized", "magic": 661202, "date": "2026-07-11",
     "desc": "optimize: Score系统代替AND逻辑, Stoch(14,3,3), ADX>20, threshold4/8"},
    {"version": "v8_optimized", "magic": 661202, "date": "2026-08-08",
     "desc": "optimize: ADX=25, sl_atr=1.2, score_threshold=5, Stoch极端区权重+2→+1"},
]


class StochTrendH1Optimized(BaseStrategy):
    """Stoch 多w期回调with-trendstrategy — v7_optimized Score系统"""

    name = "stoch_trend_h1_optimized"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)

        # v7 param（XAUUSD — 更快 Stoch 响应）
        self.adx_threshold = 25          # 从 20 升到 25，filter弱趋-trend假Signal
        self.sl_atr = 1.2                # 硬止损x数（从 2.0 收紧）
        self.trail_atr = 1.5             # ATR trailingtake profit距离

        # Score系统param
        self.score_threshold = 5         # 满分 8 分，从 4 升到 5 分及格

        # Positions跟踪
        self._pos_data: dict[int, dict] = {}
        self._pending_entry_info: dict = {}
        self._last_exit_detail: Optional[dict] = None

        # Stoch 交叉检测：record上一次 值（来自 DataFactory）
        self._prev_stoch_k: float = 50.0
        self._prev_stoch_d: float = 50.0

    def refresh_data(self, count: int = 350):
        super().refresh_data(count)
        # 多w期dataall从 DataFactory 缓存read，无需额外load

    def get_adx_data(self) -> Optional[dict]:
        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        if adx is None:
            return None
        return {"adx": adx, "pdi": pdi, "ndi": ndi}

    def _get_h4_trend(self) -> Optional[str]:
        """从 DataFactory 缓存read H4 EMA21 判断趋-trend"""
        try:
            h4 = get_cache("H4")
            if not h4:
                return None
            ema21 = h4.get("ema_21")
            candles = h4.get("candles", [])
            if ema21 is None or not candles:
                return None
            close = candles[-1].close
            return 'UP' if close > ema21 else 'DOWN' if close < ema21 else None
        except Exception:
            return None

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 100:
            return None

        closes = self.get_close_prices()
        close = closes[-1]

        # ── all从 DataFactory read ──
        stoch = self.get_indicator("stoch_5_3_3")
        if stoch is None:
            return None

        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return None

        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        if adx is None:
            return None

        ma_val = self.get_indicator("ema_21")
        if ma_val is None:
            return None

        k_curr = stoch["k"]
        d_curr = stoch["d"]
        k_prev = self._prev_stoch_k
        d_prev = self._prev_stoch_d
        self._prev_stoch_k = k_curr
        self._prev_stoch_d = d_curr

        cross_up_now = (k_curr > d_curr) and (k_prev <= d_prev)
        cross_down_now = (k_curr < d_curr) and (k_prev >= d_prev)

        # ADX <= 20: 弱-trend震荡，不交易
        if adx <= self.adx_threshold:
            return None

        # ── H4 趋-trend方向（多w期filter，DataFactory 缓存无data时skip） ──
        h4_trend = self._get_h4_trend()
        if h4_trend is None:
            h4_tag = "H4:NODATA"
        else:
            h4_tag = f"H4:{h4_trend}"

        # ── M15 Stoch 精确Entry时机（DataFactory 缓存） ──
        m15 = get_cache("M15")
        m15_stoch = m15.get("stoch_5_3_3") if m15 else None
        m15_k = m15_stoch["k"] if m15_stoch else None

        # ── Score系统（满分 8 分，threshold 4 分） ──
        long_score, short_score = 0, 0
        long_factors, short_factors = [], []

        # BUY Score
        if k_curr < 20:
            long_score += 1
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

        # SELL Score
        if k_curr > 80:
            short_score += 1
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
            "adx": round(adx, 1), "pdi": round(pdi, 1),
            "ndi": round(ndi, 1),
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
        # 无固定 TP，由 check_ema20_exit 运行时动态管理出场
        if direction == OrderType.BUY:
            return round(entry_price - dist, 2), 0
        else:
            return round(entry_price + dist, 2), 0

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

        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")

        entry_price = td["entry_price"]
        pnl_pts = (bid - entry_price) if is_buy else (entry_price - ask)

        # 硬止损: 2.0 ATR
        if pnl_pts < -atr_val * self.sl_atr:
            logger.info(f"[{self.name}] HardStop ticket={ticket}")
            self._last_exit_detail = {"exit_type": "hard_stop"}
            del self._pos_data[ticket]
            return True

        # update峰值 + profit峰值跟踪
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

        # profitdrawdowntake profit
        if _cp > 0 and self.profit_drawdown_enabled and td["peak_profit"] > atr_val * self.profit_drawdown_min_peak_atr:
            profit_ratio = _cp / td["peak_profit"]
            _pdd = self.profit_drawdown_pct
            if adx is not None and adx > 25:
                _pdd = max(_pdd, 0.5)
            if profit_ratio < (1 - _pdd):
                logger.info(f"[{self.name}] ProfitStop ticket={ticket} profit=${_cp:.2f}")
                self._last_exit_detail = {"exit_type": "profit_drawdown",
                                          "peak_profit": round(td["peak_profit"], 2),
                                          "current_profit": round(_cp, 2)}
                del self._pos_data[ticket]
                return True

        # ATRtrailingtake profit: 峰值drawdown 1.5 ATR
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

        # ADX < 20: 趋-trend衰竭
        if adx is not None and adx < 20:
            self._last_exit_detail = {"exit_type": "trend_adx_drop"}
            del self._pos_data[ticket]
            return True

        # DI反转: 趋-trend可能反转
        if adx is not None:
            if is_buy and ndi > pdi:
                self._last_exit_detail = {"exit_type": "trend_di_flip"}
                del self._pos_data[ticket]
                return True
            elif not is_buy and pdi > ndi:
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
        stoch = latest.get("stoch_5_3_3") or {}
        stoch_k = stoch.get("k", 50)

        if direction == "BUY":
            if adx < 25:
                return False
            if pdi <= ndi:
                return False
            if stoch_k > 40:
                return False
        else:
            if adx < 25:
                return False
            if ndi <= pdi:
                return False
            if stoch_k < 60:
                return False
        return True
