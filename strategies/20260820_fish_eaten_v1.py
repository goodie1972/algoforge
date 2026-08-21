"""
fish_eaten v2 — M30 价格回归策略
================================
核心逻辑：
- 门禁：ADX > 阈值 + DI 方向确认（|+DI - -DI| > 阈值）
- −DI 大（空头主导）→ 超卖入场做多（BUY 抢反弹）
- +DI 大（多头主导）→ 超买入场做空（SELL 抢回落）
- 出场：RSI/MFI 都进入过极限区后一个离开 + BB 位置 → 吃完整条鱼

时间周期：M30

参数回测结论（M30 最佳）：
- ADX_GATE: 20/22 均可，推荐 20
- DI_DIFF_GATE: 5（10与5无差异）
- BB_EXIT_OFFSET: 8/10
- TIME_STOP_BARS: 48（平衡鱼出场和死单风险）

回测结果（M30, ADX22_DI5_BB8_TS48, 2024-01~2026-08）：
- 净PnL: +$346（+3.46% on $10k）
- 交易笔数: 26笔
- 胜率: 62%
- 出场原因: fish_exit 为主 + time_stop 兜底死单

出场规则（吃鱼）：
  做多：RSI≥70 且 MFI≥75 都到过 → 一个离开（RSI<70 或 MFI<75）
        → 且 close < BB上轨 - offset → 出场
  做空：RSI≤30 且 MFI≤25 都到过 → 一个离开（RSI>30 或 MFI>25）
        → 且 close > BB下轨 + offset → 出场
  时间止损：一个指标到极限后，另一个在 48 根 K 线内未到 → 出场
"""
import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v2"
STRATEGY_MAGIC = 661301
STRATEGY_LEGACY_MAGICS: list[int] = [880601]
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 880601, "date": "2026-08-20",
     "desc": "首次发布：价格回归策略，门禁 + 3层筛子入场 + 吃鱼出场"},
    {"version": "v2", "magic": 661301, "date": "2026-08-20",
     "desc": "改为M30周期，TS=48，命名fish_eaten"},
]


class FishEatenStrategy(BaseStrategy):
    """Fish Eaten — 价格回归策略"""

    name = "fish_eaten"
    default_timeframe = "M30"
    TIMEFRAME = "M30"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    # ── 门禁参数（回测确定）──
    ADX_GATE = 20          # 回测：20/22/25，M30最佳ADX=22
    DI_DIFF_GATE = 5       # 回测：5/10，效果无差异

    # ── 入场参数 ──
    RSI_OVERSOLD = 30      # 超卖阈值
    RSI_OVERBOUGHT = 70    # 超买阈值
    MFI_OVERSOLD = 25      # 超卖阈值
    MFI_OVERBOUGHT = 75    # 超买阈值
    BB_ENTRY_OFFSET = 5    # 入场：close 与 BB 轨的偏移量

    # ── 出场参数（回测确定）──
    BB_EXIT_OFFSET = 8     # 回测：5/8/10，M30最佳8/10
    TIME_STOP_BARS = 48    # 回测：TS=48平衡鱼出场和死单风险

    # ── 风控 ──
    FIXED_LOTS = 0.01
    MAX_SLIPPAGE = 30

    # 禁用 BaseStrategy 的默认出场（我们用自己的吃鱼逻辑）
    breakeven_enabled = False
    profit_drawdown_enabled = False
    trailing_stop_enabled = False

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        # 吃鱼出场状态跟踪：{ticket: {...}}
        self._fish_state: dict = {}

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

        # 获取指标
        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        rsi = self.get_indicator("rsi")
        mfi = self.get_indicator("mfi")
        bb = self._get_bb()
        bb_mid_dir = self.get_indicator("bb_mid_direction")

        # 检查指标完整性
        if any(v is None for v in [adx, pdi, ndi, rsi, mfi, bb]):
            return None

        close = candles[-1].close

        # ── 门禁 1：ADX 阈值 ──
        if adx <= self.ADX_GATE:
            return None

        # ── 门禁 2：DI 方向确认 ──
        di_diff = abs(pdi - ndi)
        if di_diff <= self.DI_DIFF_GATE:
            return None

        # ── 前半段：−DI 大（空头主导）→ 超卖做多 ──
        if ndi > pdi:
            # 第1层：超卖（RSI < 30 且 MFI < 25）
            if rsi >= self.RSI_OVERSOLD or mfi >= self.MFI_OVERSOLD:
                return None
            # 第2层：close ≤ BB 下轨 + 偏移
            if close > bb["lower"] + self.BB_ENTRY_OFFSET:
                return None
            # 第3层：BB 中轨向下
            if bb_mid_dir != "down":
                return None

            logger.info(f"[{self.name}] 信号做多: ADX={adx:.1f} -DI={ndi:.1f} > +DI={pdi:.1f} "
                        f"RSI={rsi:.1f} MFI={mfi:.1f} close={close:.2f} ≤ 下轨+{self.BB_ENTRY_OFFSET}={bb['lower']+self.BB_ENTRY_OFFSET:.2f}")
            return (OrderType.BUY, 1, 0, ["RSI-BB-TREND-LONG"], [], {})

        # ── 后半段：+DI 大（多头主导）→ 超买做空 ──
        else:
            # 第1层：超买（RSI > 70 且 MFI > 75）
            if rsi <= self.RSI_OVERBOUGHT or mfi <= self.MFI_OVERBOUGHT:
                return None
            # 第2层：close ≥ BB 上轨 - 偏移
            if close < bb["upper"] - self.BB_ENTRY_OFFSET:
                return None
            # 第3层：BB 中轨向上
            if bb_mid_dir != "up":
                return None

            logger.info(f"[{self.name}] 信号做空: ADX={adx:.1f} +DI={pdi:.1f} > -DI={ndi:.1f} "
                        f"RSI={rsi:.1f} MFI={mfi:.1f} close={close:.2f} ≥ 上轨-{self.BB_ENTRY_OFFSET}={bb['upper']-self.BB_ENTRY_OFFSET:.2f}")
            return (OrderType.SELL, 0, 1, [], ["RSI-BB-TREND-SHORT"], {})

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: str, entry_price: float, atr_val: float,
                          position_type: str = "entry") -> tuple[float, float]:
        """宽止损兜底，无止盈（吃鱼出场管理）"""
        if atr_val <= 0:
            atr_val = 10.0
        # 1.5x ATR 硬止损兜底
        stop_dist = max(atr_val * 1.5, 15.0)
        if direction == "BUY":
            return entry_price - stop_dist, 0
        else:
            return entry_price + stop_dist, 0

    # ─────────────── 出场逻辑 ───────────────

    def mark_extreme_entry(self, ticket: int | str):
        """引擎告知入场已成交，初始化鱼状态"""
        self._fish_state[str(ticket)] = {
            "rsi_extreme": False,           # RSI 曾进入极限区
            "mfi_extreme": False,           # MFI 曾进入极限区
            "first_extreme_time": None,     # 第一个进入极限区的时间（用于时间止损）
            "first_extreme_type": None,     # "rsi" or "mfi"
            "first_extreme_bar": None,      # 第一个进入极限区时 candles 数
            "exit_armed": False,            # 两者都进入过，可以触发吃鱼出场
            "entry_bar": len(self.candles), # 入场时的 candles 数
            "time_stop_fired": False,       # 避免重复触发时间止损
        }

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """吃鱼出场逻辑 + 时间止损"""
        ticket = str(getattr(position, 'ticket', id(position)))
        state = self._fish_state.get(ticket)
        if state is None:
            return False

        # 获取当前指标
        rsi = self.get_indicator("rsi")
        mfi = self.get_indicator("mfi")
        bb = self._get_bb()
        if any(v is None for v in [rsi, mfi, bb]):
            return False

        close = self.candles[-1].close if self.candles else None
        if close is None:
            return False

        is_buy = (getattr(position, 'order_type', 'BUY') in ('OP_BUY', 'BUY'))

        # 构建极限区映射
        if is_buy:
            # 做多：极限区 = 超买 (RSI≥70, MFI≥75)
            rsi_extreme_val = 70
            mfi_extreme_val = 75
            rsi_exit_val = 70    # 离开条件
            mfi_exit_val = 75
            bb_compare = bb["upper"]
            bb_compare_offset = bb["upper"] - self.BB_EXIT_OFFSET   # close < 上轨 - offset
        else:
            # 做空：极限区 = 超卖 (RSI≤30, MFI≤25)
            rsi_extreme_val = 30
            mfi_extreme_val = 25
            rsi_exit_val = 30
            mfi_exit_val = 25
            bb_compare = bb["lower"]
            bb_compare_offset = bb["lower"] + self.BB_EXIT_OFFSET   # close > 下轨 + offset

        # ── 更新鱼状态 ──

        # 检查 RSI 是否进入极限区
        if not state["rsi_extreme"]:
            if (is_buy and rsi >= rsi_extreme_val) or (not is_buy and rsi <= rsi_extreme_val):
                state["rsi_extreme"] = True
                if state["first_extreme_type"] is None:
                    state["first_extreme_time"] = time.time()
                    state["first_extreme_type"] = "rsi"
                    state["first_extreme_bar"] = len(self.candles)

        # 检查 MFI 是否进入极限区
        if not state["mfi_extreme"]:
            if (is_buy and mfi >= mfi_extreme_val) or (not is_buy and mfi <= mfi_extreme_val):
                state["mfi_extreme"] = True
                if state["first_extreme_type"] is None:
                    state["first_extreme_time"] = time.time()
                    state["first_extreme_type"] = "mfi"
                    state["first_extreme_bar"] = len(self.candles)

        # 两者都进入过极限区 → 武装退出
        if state["rsi_extreme"] and state["mfi_extreme"]:
            state["exit_armed"] = True

        # ── 时间止损：一个到了，另一个在 N 根 K 线内没到 ──
        if not state["exit_armed"] and state["first_extreme_bar"] is not None:
            bars_waited = len(self.candles) - state["first_extreme_bar"]
            if bars_waited >= self.TIME_STOP_BARS and not state["time_stop_fired"]:
                state["time_stop_fired"] = True
                other = "MFI" if state["first_extreme_type"] == "rsi" else "RSI"
                logger.info(f"[{self.name}] 时间止损: {state['first_extreme_type'].upper()} 已到极限, {other} 在 {self.TIME_STOP_BARS} 根内未到, 平仓")
                return True

        # ── 吃鱼出场：两者都到过，一个离开，close 在 BB 反向位置 ──
        if state["exit_armed"]:
            one_left = False
            if is_buy:
                one_left = (rsi < rsi_exit_val or mfi < mfi_exit_val)
                close_cond = (close < bb_compare_offset)
            else:
                one_left = (rsi > rsi_exit_val or mfi > mfi_exit_val)
                close_cond = (close > bb_compare_offset)

            if one_left and close_cond:
                logger.info(f"[{self.name}] 吃鱼出场 {'BUY' if is_buy else 'SELL'}: "
                            f"RSI={rsi:.1f} MFI={mfi:.1f} close={close:.2f} "
                            f"{'<' if is_buy else '>'} "
                            f"{'上轨' if is_buy else '下轨'}-{self.BB_EXIT_OFFSET}={bb_compare_offset:.2f}")
                return True

        return False