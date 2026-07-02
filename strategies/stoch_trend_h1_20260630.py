"""
Stoch 回调顺势策略 (v6)
======================
大师理论: ADX>25 趋势确认 + Stoch 超买超卖回调入场
XAUUSD 专用参数: Stoch(21,5,3) 减少黄金趋势中的假信号

多周期架构:
  H4: EMA21 趋势方向过滤 — 只顺着 H4 方向交易
  H1: ADX>25 + Stoch 极端回调 + DI 方向确认
  M15: Stoch(14,3,3) 精确入场时机 — M15 也到超买/超卖区才扣扳机

入场:
  ADX > 25: 趋势市
    - BUY:  Stoch K<20 + 金叉 + close>EMA21 + +DI>-DI + H4↑ + M15 K<30
    - SELL: Stoch K>80 + 死叉 + close<EMA21 + -DI>+DI + H4↓ + M15 K>70
  ADX <= 25: 不交易（震荡市 Stoch 信号不可靠）
  H4/M15 桥接加载失败时自动跳过对应过滤，仅用 H1 交易

出场:
  - 硬止损: 2.0 ATR
  - ATR追踪止盈: 峰值回撤 1.5 ATR
  - 利润回撤止盈: 峰值利润回撤 N%
  - ADX<20: 趋势衰竭出场
  - DI反转: 趋势可能反转出场
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v6"
STRATEGY_MAGIC = 661201
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v6", "magic": 661201, "date": "2026-06-29",
     "desc": "初始: 多周期 H4→H1→M15, Stoch(21,5,3)@H1 + Stoch(14,3,3)@M15"},
]


class StochTrendH1Strategy(BaseStrategy):
    """Stoch 多周期回调顺势策略 — H4趋势+H1信号+M15精确入场"""

    name = "stoch_trend_h1"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)

        # v6 参数（XAUUSD 黄金专用 — 大师推荐 (21,5,3)）
        self.stoch_k_period = 21         # 黄金趋势持久，更慢的参数减少假信号
        self.stoch_slowing = 5
        self.stoch_d_period = 3
        self.adx_threshold = 25          # 标准 ADX 趋势阈值
        self.sl_atr = 2.0                # 硬止损倍数
        self.trail_atr = 1.5             # ATR 追踪止盈距离

        # 持仓跟踪
        self._pos_data: dict[int, dict] = {}
        self._pending_entry_info: dict = {}
        self._last_exit_detail: Optional[dict] = None

        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

        # 多周期数据（桥接实时加载，refresh_data 时刷新）
        self._h4_candles: list[Candle] = []
        self._m15_candles: list[Candle] = []

        # M15 Stoch 参数（比 H1 更快，用于精确入场时机）
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

        ma_val = self.get_indicator("ema_20")
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

        # ADX <= 25: 震荡市，Stoch信号不可靠，不交易
        if adx <= self.adx_threshold:
            return None

        # ADX > 25: 趋势市，只在Stoch极端值回调时顺势入场
        signal = None
        long_score, short_score = 0, 0
        long_factors, short_factors = [], []

        # ── H4 趋势方向（多周期过滤，桥接无数据时跳过） ──
        h4_trend = self._calc_h4_trend()
        if h4_trend is None:
            h4_tag = "H4:NODATA"
        else:
            h4_tag = f"H4:{h4_trend}"

        # ── M15 Stoch 精确入场时机 ──
        m15_stoch = self._calc_m15_stoch()
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
            "adx": round(adx, 1), "pdi": round(adx_data['pdi'], 1),
            "ndi": round(adx_data['ndi'], 1),
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
