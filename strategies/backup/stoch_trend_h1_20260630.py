"""
Stoch 回调with-trendstrategy (v6)
======================
大师理论: ADX>25 趋-trendconfirm + Stoch 超买超卖回调Entry
XAUUSD 专用param: Stoch(21,5,3) 减少黄金趋-trend  假Signal

多w期架构:
  H4: EMA21 趋-trend方向filter — 只with着 H4 方向交易
  H1: ADX>25 + Stoch 极端回调 + DI 方向confirm
  M15: Stoch(14,3,3) 精确Entry时机 — M15 也到超买/超卖区才扣扳机

Entry:
  ADX > 25: 趋-trend市
    - BUY:  Stoch K<20 + 金叉 + close>EMA21 + +DI>-DI + H4↑ + M15 K<30
    - SELL: Stoch K>80 + 死叉 + close<EMA21 + -DI>+DI + H4↓ + M15 K>70
  ADX <= 25: 不交易（震荡市 Stoch Signal不可靠）
  H4/M15 桥接loadfailed时autoskip对应filter，仅用 H1 交易

出场:
  - 硬止损: 2.0 ATR
  - ATRtrailingtake profit: 峰值drawdown 1.5 ATR
  - profitdrawdowntake profit: 峰值profitdrawdown N%
  - ADX<20: 趋-trend衰竭出场
  - DI反转: 趋-trend可能反转出场

data源: all指标从 DataFactory TA-Lib read
"""

import logging
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy
from services.data_factory import get_cache

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v6"
STRATEGY_MAGIC = 661201
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v6", "magic": 661201, "date": "2026-06-29",
     "desc": "初始: 多w期 H4→H1→M15, Stoch(21,5,3)@H1 + Stoch(14,3,3)@M15"},
]


class StochTrendH1Strategy(BaseStrategy):
    """Stoch 多w期回调with-trendstrategy — H4趋-trend+H1Signal+M15精确Entry"""

    name = "stoch_trend_h1"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)

        # v6 param（XAUUSD 黄金专用 — 大师推荐 (21,5,3)）
        self.adx_threshold = 25          # 标准 ADX 趋-trendthreshold
        self.sl_atr = 2.0                # 硬止损x数
        self.trail_atr = 1.5             # ATR trailingtake profit距离

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
        stoch = self.get_indicator("stoch_21_5_3")
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

        # ADX <= 25: 震荡市，StochSignal不可靠，不交易
        if adx <= self.adx_threshold:
            return None

        # ADX > 25: 趋-trend市，只在Stoch极端值回调时with-trendEntry
        signal = None
        long_score, short_score = 0, 0
        long_factors, short_factors = [], []

        # ── H4 趋-trend方向（多w期filter，DataFactory 缓存无data时skip） ──
        h4_trend = self._get_h4_trend()
        if h4_trend is None:
            h4_tag = "H4:NODATA"
        else:
            h4_tag = f"H4:{h4_trend}"

        # ── M15 Stoch 精确Entry时机（DataFactory 缓存） ──
        m15 = get_cache("M15")
        m15_stoch = m15.get("stoch_14_3_3") if m15 else None
        m15_k = m15_stoch["k"] if m15_stoch else None

        # BUY: 超卖区金叉 + EMA21上方 + +DI主导 + H4上升 + M15超卖
        if k_curr < 20 and cross_up_now and close > ma_val and pdi > ndi:
            pass_h4 = (h4_trend is None or h4_trend == 'UP')
            pass_m15 = (m15_k is None or m15_k < 30)
            if pass_h4 and pass_m15:
                signal = OrderType.BUY
                long_score = 3
                long_factors = [f"K={k_curr:.0f}", "PULLBACK", f"ADX={adx:.0f}", h4_tag]
                if m15_k is not None:
                    long_factors.append(f"M15K={m15_k:.0f}")
                self._pending_entry_info = {"regime": "trend", "adx": adx, "atr": atr_val}

        # SELL: 超买区死叉 + EMA21下方 + -DI主导 + H4下降 + M15超买
        elif k_curr > 80 and cross_down_now and close < ma_val and ndi > pdi:
            pass_h4 = (h4_trend is None or h4_trend == 'DOWN')
            pass_m15 = (m15_k is None or m15_k > 70)
            if pass_h4 and pass_m15:
                signal = OrderType.SELL
                short_score = 3
                short_factors = [f"K={k_curr:.0f}", "PULLBACK", f"ADX={adx:.0f}", h4_tag]
                if m15_k is not None:
                    short_factors.append(f"M15K={m15_k:.0f}")
                self._pending_entry_info = {"regime": "trend", "adx": adx, "atr": atr_val}

        iv = {
            "close": round(close, 2), "atr": round(atr_val, 2),
            "adx": round(adx, 1), "pdi": round(pdi, 1),
            "ndi": round(ndi, 1),
            "k": round(k_curr, 1), "d": round(d_curr, 1),
            "ema21": round(ma_val, 2),
            "h4_trend": h4_trend or "NODATA",
            "m15_k": round(m15_k, 1) if m15_k is not None else None,
        }

        logger.info(
            f"[{self.name}] K={k_curr:.1f} D={d_curr:.1f} ADX={adx:.1f} "
            f"H4={h4_trend or 'N/A'} M15K={f'{m15_k:.0f}' if m15_k is not None else 'N/A'} "
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
        stoch = latest.get("stoch_21_5_3") or {}
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
