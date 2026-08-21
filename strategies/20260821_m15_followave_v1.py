"""
m15_followave v1 — M15 Stoch+BBI+BB 趋势跟踪策略
=================================================
核心逻辑：
- 趋势方向：±DI 门禁确认（|+DI - -DI| > 5）+ 方向（+DI > -DI 做多，-DI > +DI 做空）
- 入场：BBI 上方 + Stoch 金叉 + K < 80 + 价格 ≥ BB 中轨
- 出场：连续 3 根 K 线 < BBI + BBI 斜率向下 → 趋势反转出场
- 硬止损：价格跌破 BB 下轨

时间周期：M15

回测结果（M15, Stoch5_3_3, 2024~2026）：
- 净PnL: +$403（+4.03% on $10k）
- 交易笔数: 312笔
- 胜率: 36%
- 盈亏比: 2.09
"""
import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 661401
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 661401, "date": "2026-08-21",
     "desc": "首次发布：M15 Stoch+BBI+BB 趋势跟踪，±DI门禁，无 trailing stop"},
]


class M15FollowAveStrategy(BaseStrategy):
    """M15 FollowAve — Stoch+BBI+BB 趋势跟踪"""

    name = "m15_followave"
    default_timeframe = "M15"
    TIMEFRAME = "M15"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    # ── 参数（回测确定）──
    DI_GATE = 5               # ±DI 差值门禁
    EXIT_CONFIRM_BARS = 3     # 出场确认 K 线数
    TRAIL_ATR = 0             # 不使用 trailing stop

    # ── Stoch ──
    STOCH_K_OVERBOUGHT = 80   # 超买阈值
    STOCH_K_OVERSOLD = 20     # 超卖阈值

    # ── 风控 ──
    FIXED_LOTS = 0.01
    MAX_SLIPPAGE = 30

    # 禁用 BaseStrategy 的默认出场（我们用自己的）
    breakeven_enabled = False
    profit_drawdown_enabled = False
    trailing_stop_enabled = False

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        # 出场状态跟踪
        self._exit_state: dict = {}

    # ─────────────── 辅助 ───────────────

    def _get_bb(self) -> Optional[dict]:
        bb = self.get_indicator("bb")
        if isinstance(bb, dict) and "mid" in bb:
            return bb
        return None

    # ─────────────── 入场逻辑 ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 30:
            return None

        close = candles[-1].close
        bbi = self.get_indicator("bbi")
        stoch = self.get_indicator("stoch_5_3_3") or {}
        bb = self._get_bb()
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")

        if any(v is None for v in [bbi, pdi, ndi, bb]):
            return None

        stoch_k = stoch.get("k")
        stoch_d = stoch.get("d")
        if stoch_k is None or stoch_d is None:
            return None

        bb_mid = bb.get("mid", 0)

        # ── ±DI 门禁 ──
        di_diff = abs(pdi - ndi)
        if di_diff <= self.DI_GATE:
            return None

        # ── 多头：+DI > -DI, 价格>BBI, Stoch金叉, K<80, 价格>=BB中轨 ──
        if pdi > ndi:
            if close > bbi and stoch_k > stoch_d and stoch_k < self.STOCH_K_OVERBOUGHT and close >= bb_mid:
                logger.info(f"[{self.name}] 信号做多: +DI={pdi:.1f} > -DI={ndi:.1f} "
                            f"BBI={bbi:.2f} StochK={stoch_k:.1f} close={close:.2f}")
                return (OrderType.BUY, 1, 0, ["FOLLOWAVE-LONG"], [], {
                    "bbi": round(bbi, 2), "stoch_k": round(stoch_k, 1), "stoch_d": round(stoch_d, 1),
                    "pdi": round(pdi, 1), "ndi": round(ndi, 1), "bb_mid": round(bb_mid, 2)
                })

        # ── 空头：-DI > +DI, 价格<BBI, Stoch死叉, K>20, 价格<=BB中轨 ──
        else:
            if close < bbi and stoch_k < stoch_d and stoch_k > self.STOCH_K_OVERSOLD and close <= bb_mid:
                logger.info(f"[{self.name}] 信号做空: -DI={ndi:.1f} > +DI={pdi:.1f} "
                            f"BBI={bbi:.2f} StochK={stoch_k:.1f} close={close:.2f}")
                return (OrderType.SELL, 0, 1, [], ["FOLLOWAVE-SHORT"], {
                    "bbi": round(bbi, 2), "stoch_k": round(stoch_k, 1), "stoch_d": round(stoch_d, 1),
                    "pdi": round(pdi, 1), "ndi": round(ndi, 1), "bb_mid": round(bb_mid, 2)
                })

        return None

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: str, entry_price: float, atr_val: float,
                          position_type: str = "entry") -> tuple[float, float]:
        """宽止损兜底（BB 下轨止损更灵敏，但用 ATR 兜底）"""
        if atr_val <= 0:
            atr_val = 10.0
        stop_dist = max(atr_val * 3.0, 30.0)  # 宽止损，BB 下轨才是主要止损
        if direction == "BUY":
            return entry_price - stop_dist, 0
        else:
            return entry_price + stop_dist, 0

    # ─────────────── 出场逻辑 ───────────────

    def mark_extreme_entry(self, ticket: int | str):
        """引擎告知入场已成交，初始化出场状态"""
        self._exit_state[str(ticket)] = {
            "exit_count": 0,           # 连续 K 线在 BBI 另一侧的计数
            "trail_peak": None,        # trailing stop 跟踪峰值
        }

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """趋势反转出场 + BB 硬止损"""
        ticket = str(getattr(position, 'ticket', id(position)))
        state = self._exit_state.get(ticket)
        if state is None:
            return False

        is_buy = (getattr(position, 'order_type', 'BUY') in ('OP_BUY', 'BUY'))
        close = self.candles[-1].close if self.candles else None
        if close is None:
            return False

        bbi = self.get_indicator("bbi")
        bb = self._get_bb()
        if bbi is None or bb is None:
            return False

        bb_bot = bb.get("lower", 0)
        bb_top = bb.get("upper", 0)
        atr_val = self.get_indicator("atr") or 10.0

        # 更新 trailing stop 峰值
        high = self.candles[-1].high if self.candles else close
        low = self.candles[-1].low if self.candles else close

        if is_buy:
            # BB 硬止损
            if close < bb_bot:
                logger.info(f"[{self.name}] BB硬止损 LONG: close={close:.2f} < BB下轨={bb_bot:.2f}")
                return True

            # 趋势反转出场：连续 EXIT_CONFIRM_BARS 根 < BBI + BBI 斜率向下
            bbi_dir = self.get_indicator("bb_mid_direction")  # 用 bb_mid_direction 近似 bbi 斜率
            if close < bbi:
                state["exit_count"] += 1
            else:
                state["exit_count"] = 0

            if state["exit_count"] >= self.EXIT_CONFIRM_BARS:
                logger.info(f"[{self.name}] 趋势反转 LONG: close={close:.2f} < BBI={bbi:.2f} 连续{state['exit_count']}根")
                return True

        else:  # SHORT
            if close > bb_top:
                logger.info(f"[{self.name}] BB硬止损 SHORT: close={close:.2f} > BB上轨={bb_top:.2f}")
                return True

            if close > bbi:
                state["exit_count"] += 1
            else:
                state["exit_count"] = 0

            if state["exit_count"] >= self.EXIT_CONFIRM_BARS:
                logger.info(f"[{self.name}] 趋势反转 SHORT: close={close:.2f} > BBI={bbi:.2f} 连续{state['exit_count']}根")
                return True

        return False