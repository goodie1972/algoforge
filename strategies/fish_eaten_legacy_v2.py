"""
fish_eaten v2 — 旧版「原样保留」并行测试版（M30）
================================================
本文件是 v3 开发前的**原始 v2** 逻辑，原样保留用于与 v3(661303) 做并行纸面对照：
- 入场：原始 6 道筛子（ADX>22 无上界 / DI差>5 无上界 / -DI>+DI / RSI<30&MFI<25 /
        close≤下轨+5 / bb_mid_dir=="down" 做多；镜像做空）
- 出场：原始「吃鱼」逻辑（RSI/MFI 都到过极限区后一个离开 + BB 位置）+ 时间止损（沿用）
- **唯一改动**：硬止损从 1.5×ATR 放宽到 3.0×ATR（SL_ATR_MULT=3.0），
  与 v3.1 使用同一档止损，做公平对照。

与原 v2 的两点偏差（均为对齐对照/纪律，非策略逻辑变更）：
1. 入场价判定用 candles[-2].close（bar1，已闭合）而非原 candles[-1].close（forming bar0），
   既与回测口径一致，也符合「确认性信号只能源自 bar1」的纪律。
2. name 改为 "fish_eaten_v2"、magic 改回 661302（沿用原版 magic），与 v3(661303) 在扫描器/仓位管理区分。

时间周期：M30
"""
import logging
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v2.2"
STRATEGY_MAGIC = 661302
STRATEGY_LEGACY_MAGICS: list[int] = [880601, 661301]
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 880601, "date": "2026-08-20",
     "desc": "首次发布：价格回归策略，门禁 + 3层筛子入场 + 吃鱼出场"},
    {"version": "v2", "magic": 661302, "date": "2026-08-20",
     "desc": "改为M30周期，TS=48，命名fish_eaten"},
    {"version": "v2.1", "magic": 661302, "date": "2026-08-27",
     "desc": "修复magic冲突(661301→661302)，清理死代码，修复内存泄漏"},
    {"version": "v2.2", "magic": 661302, "date": "2026-09-06",
     "desc": "并行测试版：原样保留 v2 入场(6筛子)+出场(吃鱼)，"
             "仅将硬止损从 1.5×ATR 放宽到 3.0×ATR(SL_ATR_MULT)，与 v3(661303) 同档对照；"
             "name 改为 fish_eaten_v2、magic 改回 661302（沿用原版 magic）避免冲突；"
             "入场价判定改 candles[-2].close(bar1) 对齐回测口径与 bar1 纪律。"},
]


class FishEatenLegacyV2Strategy(BaseStrategy):
    """Fish Eaten — 旧版 v2 并行测试（原样保留 + 3.0ATR 止损）"""

    name = "fish_eaten_v2"
    default_timeframe = "M30"
    TIMEFRAME = "M30"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    # ── 门禁参数（原始 v2）──
    ADX_GATE = 22          # 原始：只有下界，趋势确实存在
    DI_DIFF_GATE = 5       # 原始：DI 方向确认差值的下界

    # ── 入场参数（原始 v2）──
    RSI_OVERSOLD = 30      # 超卖阈值
    RSI_OVERBOUGHT = 70    # 超买阈值
    MFI_OVERSOLD = 25      # 超卖阈值
    MFI_OVERBOUGHT = 75    # 超买阈值
    BB_ENTRY_OFFSET = 5    # 入场：价格与 BB 轨的触及偏移

    # ── 出场参数（原始 v2，吃鱼）──
    BB_EXIT_OFFSET = 8     # 回测：5/8/10，M30最佳8/10
    TIME_STOP_BARS = 48    # 回测：TS=48平衡鱼出场和死单风险

    # ── 风控 ──
    FIXED_LOTS = 0.01
    MAX_SLIPPAGE = 30
    SL_ATR_MULT = 3.0       # v2.2：与原 v2(1.5)唯一差异——硬止损放宽到 3.0×ATR，与 v3.1 同档

    # 禁用 BaseStrategy 的默认出场（我们用自己的吃鱼逻辑）
    breakeven_enabled = False
    profit_drawdown_enabled = False
    trailing_stop_enabled = False

    @staticmethod
    def _verify_entry(signal, tick_price, latest, item=None):
        """跳过 Athlete 验证，有票直接入场"""
        return True

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

    # ─────────────── 入场逻辑（原始 v2 6 筛子）───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 30:
            return None

        # 指标（均为 bar1 单值，来自 DataFactory 缓存）
        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        rsi = self.get_indicator("rsi")
        mfi = self.get_indicator("mfi")
        bb = self._get_bb()
        bb_mid_dir = self.get_indicator("bb_mid_direction")

        if any(v is None for v in [adx, pdi, ndi, rsi, mfi, bb]):
            return None

        # bar1（已闭合 K 线）收盘价，用于位置判定
        close = candles[-2].close

        # ── 门禁 1：ADX 阈值（原始只有下界）──
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
            # 第3层：BB 中轨向下（原始 v2 硬门禁 —— 这也是「中段入场」根因）
            if bb_mid_dir != "down":
                return None

            logger.info(f"[{self.name}] 信号做多: ADX={adx:.1f} -DI={ndi:.1f}>+DI={pdi:.1f} "
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

            logger.info(f"[{self.name}] 信号做空: ADX={adx:.1f} +DI={pdi:.1f}>-DI={ndi:.1f} "
                        f"RSI={rsi:.1f} MFI={mfi:.1f} close={close:.2f} ≥ 上轨-{self.BB_ENTRY_OFFSET}={bb['upper']-self.BB_ENTRY_OFFSET:.2f}")
            return (OrderType.SELL, 0, 1, [], ["RSI-BB-TREND-SHORT"], {})

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: str, entry_price: float, atr_val: float = None,
                          position_type: str = "entry") -> tuple[float, float]:
        """宽止损兜底，无止盈（吃鱼出场管理）"""
        if atr_val is None:
            atr_val = self.get_indicator("atr") or 10.0
        if atr_val <= 0:
            atr_val = 10.0
        # 硬止损兜底（SL_ATR_MULT 倍 ATR，下限 15 美元）
        stop_dist = max(atr_val * self.SL_ATR_MULT, 15.0)
        if direction == "BUY":
            return entry_price - stop_dist, 0
        else:
            return entry_price + stop_dist, 0

    # ─────────────── 出场逻辑（原始 v2 吃鱼，未改动）───────────────

    def mark_extreme_entry(self, ticket: int | str):
        """引擎告知入场已成交，初始化鱼状态（幂等：已有状态不覆盖）"""
        if str(ticket) in self._fish_state:
            return
        self._fish_state[str(ticket)] = {
            "rsi_extreme": False,           # RSI 曾进入极限区
            "mfi_extreme": False,           # MFI 曾进入极限区
            "first_extreme_type": None,     # "rsi" or "mfi"
            "first_extreme_bar": None,      # 第一个进入极限区时 candles 数
            "exit_armed": False,            # 两者都进入过，可以触发吃鱼出场
            "time_stop_fired": False,       # 避免重复触发时间止损
        }

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """吃鱼出场逻辑 + 时间止损"""
        ticket = str(getattr(position, 'ticket', id(position)))
        state = self._fish_state.get(ticket)
        if state is None:
            return False

        rsi = self.get_indicator("rsi")
        mfi = self.get_indicator("mfi")
        bb = self._get_bb()
        if any(v is None for v in [rsi, mfi, bb]):
            return False

        close = self.candles[-1].close if self.candles else None
        if close is None:
            return False

        is_buy = (getattr(position, 'order_type', 'BUY') in ('OP_BUY', 'BUY'))

        if is_buy:
            rsi_extreme_val = 70
            mfi_extreme_val = 75
            rsi_exit_val = 70
            mfi_exit_val = 75
            bb_compare_offset = bb["upper"] - self.BB_EXIT_OFFSET
        else:
            rsi_extreme_val = 30
            mfi_extreme_val = 25
            rsi_exit_val = 30
            mfi_exit_val = 25
            bb_compare_offset = bb["lower"] + self.BB_EXIT_OFFSET

        if not state["rsi_extreme"]:
            if (is_buy and rsi >= rsi_extreme_val) or (not is_buy and rsi <= rsi_extreme_val):
                state["rsi_extreme"] = True
                if state["first_extreme_type"] is None:
                    state["first_extreme_type"] = "rsi"
                    state["first_extreme_bar"] = len(self.candles)

        if not state["mfi_extreme"]:
            if (is_buy and mfi >= mfi_extreme_val) or (not is_buy and mfi <= mfi_extreme_val):
                state["mfi_extreme"] = True
                if state["first_extreme_type"] is None:
                    state["first_extreme_type"] = "mfi"
                    state["first_extreme_bar"] = len(self.candles)

        if state["rsi_extreme"] and state["mfi_extreme"]:
            state["exit_armed"] = True

        if not state["exit_armed"] and state["first_extreme_bar"] is not None:
            bars_waited = len(self.candles) - state["first_extreme_bar"]
            if bars_waited >= self.TIME_STOP_BARS and not state["time_stop_fired"]:
                state["time_stop_fired"] = True
                other = "MFI" if state["first_extreme_type"] == "rsi" else "RSI"
                logger.info(f"[{self.name}] 时间止损: {state['first_extreme_type'].upper()} 已到极限, {other} 在 {self.TIME_STOP_BARS} 根内未到, 平仓")
                del self._fish_state[ticket]
                return True

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
                del self._fish_state[ticket]
                return True

        return False
