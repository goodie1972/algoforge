"""
Stoch KDJ 周期策略 (v12)
=================================
入场 (3 道闸门必过):
  1. ADX > 25
  2. KDJ 金叉/死叉
  3. BBI 方向: 金叉+close>BBI, 死叉+close<BBI
  → 运动员直接入场

出场 (按入场 K 极值分情况):
  - 极值入场 (K<20 BUY / K>80 SELL): 等 K/D 到反向极值 + KDJ 反向
  - 非极值入场 (20≤K<50 BUY / 50<K≤80 SELL): BBI 反转 或 KDJ 反向
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
     "desc": "KDJ 周期: 入场 K<50 金叉+close>BBI / K>50 死叉+close<BBI; 出场按入场 K 极值分情况 (K<20 等 K>80+KDJ 反向, 20≤K<50 用 BBI 反转或 KDJ 反向)"},
    {"version": "v13_no_k_midline", "magic": 661204, "date": "2026-08-01",
     "desc": "去掉K极值半区门禁(K<50/K>50)，仅保留ADX+KDJ交叉+BBI方向3道闸门，增加信号频率"},
]


class StochTrendH1Upgraded(BaseStrategy):
    """Stoch KDJ 周期策略 — v12"""

    name = "stoch_trend_h1_upgraded"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)

        # 参数
        self.adx_threshold = 25
        self.bbi_periods = (3, 6, 12, 24)
        self.k_midline = 50             # K<50 金叉, K>50 死叉
        self.k_extreme_buy = 20         # K<20 视为超卖
        self.k_extreme_sell = 80        # K>80 视为超买

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
        """返回 K, D, K_prev, D_prev, cross_up, cross_down"""
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
        """3 道闸门:
        1. ADX > 25
        2. KDJ 交叉
        3. BBI 方向
        """
        if len(self.candles) < 100:
            return None

        # 1. ADX > 25
        adx = self.get_indicator("adx")
        if adx is None or adx <= self.adx_threshold:
            return None

        # 2 & 3. KDJ 交叉 + K 极值半区
        kdj = self._get_kdj()
        if kdj is None:
            return None

        bbi = self._get_bbi()
        if bbi is None:
            return None

        close = self.get_close_prices()[-1]
        k = kdj["k"]

        signal = None
        is_extreme = False

        # BUY: 金叉 + close>BBI
        if kdj["cross_up"] and close > bbi:
            signal = OrderType.BUY
            is_extreme = k < self.k_extreme_buy
        # SELL: 死叉 + close<BBI
        elif kdj["cross_down"] and close < bbi:
            signal = OrderType.SELL
            is_extreme = k > self.k_extreme_sell

        if signal is None:
            self._pending_entry_info = {}
            return None

        self._pending_entry_info = {
            "direction": "BUY" if signal == OrderType.BUY else "SELL",
            "k_at_entry": k,
            "d_at_entry": kdj["d"],
            "is_extreme": is_extreme,
        }

        logger.info(
            f"[{self.name}] {signal.value} K={k:.1f} D={kdj['d']:.1f} ADX={adx:.1f} BBI={bbi:.1f} extreme={is_extreme}"
        )

        iv = {
            "close": round(close, 2),
            "k": round(k, 1),
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
        """出场: 按入场 K 极值分情况
        极值入场 (K<20 BUY / K>80 SELL): 等 K/D 到反向极值 + KDJ 反向
        非极值入场: BBI 反转 OR KDJ 反向交叉
        """
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        # 记录入场 K/D 和极值标记
        if ticket not in self._pos_data:
            self._pos_data[ticket] = {
                "entry_k": self._pending_entry_info.get("k_at_entry", 50),
                "entry_d": self._pending_entry_info.get("d_at_entry", 50),
                "is_extreme": self._pending_entry_info.get("is_extreme", False),
            }

        td = self._pos_data[ticket]
        entry_k = td.get("entry_k", 50)
        is_extreme = td.get("is_extreme", False)

        kdj = self._get_kdj()
        if kdj is None:
            return False

        curr_k = kdj["k"]
        curr_d = kdj["d"]
        cross_down = kdj["cross_down"]
        cross_up = kdj["cross_up"]

        bbi = self._get_bbi()
        cl = self.get_close_prices()[-1]

        if is_buy:
            # KDJ 反向交叉 (死叉)
            if cross_down:
                if is_extreme:
                    # 极值入场: 等 K 和 D 都 >80
                    if curr_k > self.k_extreme_sell and curr_d > self.k_extreme_sell:
                        logger.info(f"[{self.name}] BUY 极值出场 (K/D 均>80) ticket={ticket}")
                        del self._pos_data[ticket]
                        return True
                else:
                    # 非极值入场: KDJ 反向即出
                    logger.info(f"[{self.name}] BUY KDJ反向出场 (K={curr_k:.1f}) ticket={ticket}")
                    del self._pos_data[ticket]
                    return True
            # 非极值入场: BBI 反转也出场
            if not is_extreme and bbi is not None and cl < bbi:
                logger.info(f"[{self.name}] BUY BBI反转出场 ticket={ticket}")
                del self._pos_data[ticket]
                return True
        else:  # SELL
            if cross_up:
                if is_extreme:
                    # 极值入场: 等 K 和 D 都 <20
                    if curr_k < self.k_extreme_buy and curr_d < self.k_extreme_buy:
                        logger.info(f"[{self.name}] SELL 极值出场 (K/D 均<20) ticket={ticket}")
                        del self._pos_data[ticket]
                        return True
                else:
                    logger.info(f"[{self.name}] SELL KDJ反向出场 (K={curr_k:.1f}) ticket={ticket}")
                    del self._pos_data[ticket]
                    return True
            if not is_extreme and bbi is not None and cl > bbi:
                logger.info(f"[{self.name}] SELL BBI反转出场 ticket={ticket}")
                del self._pos_data[ticket]
                return True

        return False

    # ─────────────── 验票 ───────────────

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        """v12 验票: 默认通过, 运动员直接入场"""
        return True
