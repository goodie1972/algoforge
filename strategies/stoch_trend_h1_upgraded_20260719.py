"""
Stoch KDJ 周期策略 (v12)
=================================
3 道闸门入场 + 抓完整 KDJ 周期出场

入场 (generate_signal):
  1. ADX > 25 (震荡市不做)
  2. KDJ 金叉/死叉
  3. K 在极值区: K<20 (金叉做多) / K>80 (死叉做空)
  4. close vs BBI 方向确认: 金叉+close>BBI / 死叉+close<BBI
  → 4 道闸门全过才出票, 运动员直接入场

出场 (check_ema20_exit):
  - 入场 BUY 在 K<20: 等 K 和 D 都到 >80, 然后 KDJ 死叉 → 平
  - 入场 SELL 在 K>80: 等 K 和 D 都到 <20, 然后 KDJ 金叉 → 平
  - 不考虑 BBI 反转
  - 不要硬止损

数据源: 全部指标从 DataFactory 读取
"""
import logging
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy
from services.data_factory import get_cache

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v12_kdj_cycle"
STRATEGY_MAGIC = 661204
STRATEGY_LEGACY_MAGICS: list[int] = [661201, 661202, 661203]
STRATEGY_CHANGELOG = [
    {"version": "v9_trend_zone", "magic": 661204, "date": "2026-07-24",
     "desc": "趋势中段: 金叉K>=65(原<40), 死叉K<=35(原>60); 极端金叉K>80, 极端死叉K<20"},
    {"version": "v8_upgraded", "magic": 661203, "date": "2026-07-19",
     "desc": "升级版: ADX>25; 极端不独立给分; 1.5ATR止损3.0ATR止盈; Stoch交叉趋势走完出场"},
    {"version": "v10_counter_trend", "magic": 661204, "date": "2026-07-28",
     "desc": "真正逆势: K<=35金叉做多 (超卖反弹), K>=65死叉做空 (超买回调)"},
    {"version": "v12_kdj_cycle", "magic": 661204, "date": "2026-07-28",
     "desc": "KDJ 周期策略: 入场 4 闸门(ADX>25+KDJ交叉+K极值+BBI方向); 出场等 K/D 到反向极值再 KDJ 反向交叉; 不要硬止损, 不要 BBI 反转出场"},
]


class StochTrendH1Upgraded(BaseStrategy):
    """Stoch KDJ 周期策略 — v12"""

    name = "stoch_trend_h1_upgraded"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)

        # 参数
        self.adx_threshold = 25
        self.bbi_periods = (3, 6, 12, 24)  # BBI = (MA3+MA6+MA12+MA24)/4
        self.k_extreme_buy = 20   # K<20 视为超卖
        self.k_extreme_sell = 80  # K>80 视为超买

        # 持仓跟踪
        self._pos_data: dict[int, dict] = {}
        self._pending_entry_info: dict = {}
        self._last_exit_detail: Optional[dict] = None

        # Stoch 交叉检测
        self._prev_stoch_k: float = 50.0
        self._prev_stoch_d: float = 50.0

    def refresh_data(self, count: int = 350):
        super().refresh_data(count)

    # ─────────────── 指标计算 ───────────────

    def _get_bbi(self) -> Optional[float]:
        """BBI = (MA3 + MA6 + MA12 + MA24) / 4"""
        try:
            closes = self.get_close_prices()
            if len(closes) < 24:
                return None
            ma = {}
            for p in self.bbi_periods:
                ma[p] = sum(closes[-p:]) / p
            return sum(ma.values()) / len(ma)
        except Exception:
            return None

    def _get_kdj(self) -> Optional[dict]:
        """返回 K, D, K_prev, D_prev"""
        stoch = self.get_indicator("stoch_5_3_3")
        if stoch is None:
            return None
        k_curr = stoch["k"]
        d_curr = stoch["d"]
        k_prev = self._prev_stoch_k
        d_prev = self._prev_stoch_d
        self._prev_stoch_k = k_curr
        self._prev_stoch_d = d_curr
        return {
            "k": k_curr,
            "d": d_curr,
            "k_prev": k_prev,
            "d_prev": d_prev,
            "cross_up": (k_curr > d_curr) and (k_prev <= d_prev),
            "cross_down": (k_curr < d_curr) and (k_prev >= d_prev),
        }

    # ─────────────── 入场 ───────────────

    def generate_signal(self) -> Optional[tuple]:
        """4 道闸门: ADX>25 + KDJ交叉 + K极值 + BBI 方向"""
        if len(self.candles) < 100:
            return None

        # 1. ADX > 25
        adx = self.get_indicator("adx")
        if adx is None or adx <= self.adx_threshold:
            return None

        # 2 & 3. KDJ 交叉 + K 极值
        kdj = self._get_kdj()
        if kdj is None:
            return None

        bbi = self._get_bbi()
        if bbi is None:
            return None

        close = self.get_close_prices()[-1]

        signal = None
        extreme_zone = False

        # BUY: 金叉 + K<20 + close>BBI
        if kdj["cross_up"] and kdj["k"] < self.k_extreme_buy and close > bbi:
            signal = OrderType.BUY
            extreme_zone = True
        # SELL: 死叉 + K>80 + close<BBI
        elif kdj["cross_down"] and kdj["k"] > self.k_extreme_sell and close < bbi:
            signal = OrderType.SELL
            extreme_zone = True

        if signal is None:
            self._pending_entry_info = {}
            return None

        self._pending_entry_info = {
            "direction": "BUY" if signal == OrderType.BUY else "SELL",
            "k_at_entry": kdj["k"],
            "d_at_entry": kdj["d"],
            "extreme": extreme_zone,
        }

        logger.info(
            f"[{self.name}] {signal.value} K={kdj['k']:.1f} D={kdj['d']:.1f} ADX={adx:.1f} BBI={bbi:.1f}"
        )

        iv = {
            "close": round(close, 2),
            "k": round(kdj["k"], 1),
            "d": round(kdj["d"], 1),
            "adx": round(adx, 1),
            "bbi": round(bbi, 2),
        }
        return (signal, 1, 1, [], [], iv)

    # ─────────────── SL/TP (给极宽止损, 不做硬止损) ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """不给硬止损, 给极宽兜底, 实际靠 check_ema20_exit"""
        if direction == OrderType.BUY:
            return round(entry_price * 0.50, 2), round(entry_price * 10, 2)
        else:
            return round(entry_price * 1.50, 2), round(entry_price * 0.01, 2)

    # ─────────────── 出场 ───────────────

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """出场: 等 K/D 到反向极值, 然后 KDJ 反向穿越
        BUY 入场在 K<20 → 等 K>80 且 D>80 → KDJ 死叉
        SELL 入场在 K>80 → 等 K<20 且 D<20 → KDJ 金叉
        """
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        # 记录入场 K/D
        if ticket not in self._pos_data:
            self._pos_data[ticket] = {
                "entry_k": self._pending_entry_info.get("k_at_entry", 50),
                "entry_d": self._pending_entry_info.get("d_at_entry", 50),
            }

        td = self._pos_data[ticket]
        entry_k = td.get("entry_k", 50)

        kdj = self._get_kdj()
        if kdj is None:
            return False

        curr_k = kdj["k"]
        curr_d = kdj["d"]
        cross_down = kdj["cross_down"]   # K 下穿 D
        cross_up = kdj["cross_up"]       # K 上穿 D

        if is_buy:
            # BUY 入场在 K<20: 等 K>80 且 D>80 → KDJ 死叉
            if entry_k < self.k_extreme_buy:
                if curr_k > self.k_extreme_sell and curr_d > self.k_extreme_sell:
                    if cross_down:
                        logger.info(f"[{self.name}] BUY极值出场(K={curr_k:.1f}/D={curr_d:.1f} 均>80) ticket={ticket}")
                        del self._pos_data[ticket]
                        return True
        else:
            # SELL 入场在 K>80: 等 K<20 且 D<20 → KDJ 金叉
            if entry_k > self.k_extreme_sell:
                if curr_k < self.k_extreme_buy and curr_d < self.k_extreme_buy:
                    if cross_up:
                        logger.info(f"[{self.name}] SELL极值出场(K={curr_k:.1f}/D={curr_d:.1f} 均<20) ticket={ticket}")
                        del self._pos_data[ticket]
                        return True

        return False

    # ─────────────── 验票 ───────────────

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        """v12 验票: 默认通过, 让引擎直接入场"""
        return True
