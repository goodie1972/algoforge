"""
fish_eaten v3 — M30 趋势衰竭反手策略
====================================
核心逻辑：
- 门禁：ADX 双向区间（下界 22 / 上界 30）+ DI 方向确认 + 极端区已触及 + 价格触轨
- −DI 大（空头主导）→ 超卖区衰竭 → 做多抢反弹
- +DI 大（多头主导）→ 超买区衰竭 → 做空抢回落
- 入场不再要求「趋势仍在跑」（旧版 bb_mid_dir=="down" 已删除），
  改为对「趋势动能正在衰减」打分：ADX 掉头 / DI 收敛 / 带宽收缩 /
  插针收回 / RSI·MFI 离开极端区 / 背离，总分 ≥ SCORE_MIN 才入场。
- 出场：RSI/MFI 都进入过极限区后一个离开 + BB 位置 → 吃完整条鱼（沿用 v2，未改动）

时间周期：M30

⚠️ v3 相对 v2 的关键变更（解决「总在趋势中段入场」）：
  旧 6 道筛子全是下限型/滞后型（ADX>22 无上界、DI差>5 无上界、
  close≤下轨+5 选中 band walk、bb_mid_dir=="down" 是趋势跟随判定），
  在趋势中段与末端同样通过 → 结构性选中段。详见 strategies/fish_eaten_entry.py 头部。

  1. ADX 加双向区间（≤ ADX_MAX=60）并加分「ADX 掉头」
  2. DI 差要求收敛（不再继续放大）
  3. 用「带宽收缩」替代 bb_mid_dir == "down"
  4. 入场形态改「插针收回」（bar1 破轨但收盘收回轨内）
  5. RSI/MFI 由「处于超卖」改为「离开超卖」（上穿 30 / 下穿 70）
  6. 增加背离判定（价格新低而 RSI 不新低，需 ~10 根历史）
  打分实现在 strategies/fish_eaten_entry.py（纯函数，与回测共用同一份逻辑）。

历史回测结论（v2，M30，ADX22_DI5_BB8_TS48，2026-03~2026-08）：
- v2 基线：26 笔 / 胜率 62% / 净 PnL +$346（无硬止损回测口径）
- v3 回测结果见 backtest/fish_eaten_v3.py 输出
"""
import logging
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy
from strategies.fish_eaten_entry import EntryParams, score_entry, seq_at

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v3.1"
STRATEGY_MAGIC = 661303
STRATEGY_LEGACY_MAGICS: list[int] = [880601, 661301, 661302]
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 880601, "date": "2026-08-20",
     "desc": "首次发布：价格回归策略，门禁 + 3层筛子入场 + 吃鱼出场"},
    {"version": "v2", "magic": 661302, "date": "2026-08-20",
     "desc": "改为M30周期，TS=48，命名fish_eaten"},
    {"version": "v2.1", "magic": 661302, "date": "2026-08-27",
     "desc": "修复magic冲突(661301→661302)，清理死代码，修复内存泄漏"},
    {"version": "v3", "magic": 661303, "date": "2026-09-06",
     "desc": "入场改衰竭打分制，解决「总在趋势中段挨打」："
             "①ADX加双向区间(≤40)且要求掉头 ②DI差要求收敛 ③用带宽收缩替代bb_mid_dir==down "
             "④形态改插针收回(bar1破轨收盘收回) ⑤RSI/MFI改「离开极端区」而非「处于极端区」 "
             "⑥新增背离判定(需10根历史)。打分逻辑抽到 strategies/fish_eaten_entry.py，"
             "与回测 backtest/fish_eaten_v3.py 共用同一份代码。出场(吃鱼+时间止损)未改动。"
             "依赖 base.py v2 新增的 get_indicator_series() 读取指标历史序列。"},
    {"version": "v3.1", "magic": 661303, "date": "2026-09-06",
     "desc": "回测标定参数 + 止损放宽：入场默认参数改为 S4/A60/-/D8 "
             "(score_min=4, adx_max=60 即取消ADX上界, 取消插针硬门禁, 背离回看8根)；"
             "硬止损从 1.5×ATR 放宽到 3.0×ATR(SL_ATR_MULT)。"
             "依据 sl_sweep.py（当前M30数据, DB源）：窄止损下 S4/A30 是过拟合，"
             "宽止损(3.0ATR)下冠军翻为 A60（S4/A60/-/D8=22笔/40.9%/+$156，S5/A60/P/D8=10笔/50%/+$155）。"
             "原瓶颈是止损过窄(MAE≈$25 > SL=$18)，非入场；v2原版同口径重跑=57笔(vs旧26笔)。"},
]


class FishEatenStrategy(BaseStrategy):
    """Fish Eaten v3 — 价格回归策略"""

    name = "fish_eaten_v3"
    default_timeframe = "M30"
    TIMEFRAME = "M30"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    # ── 门禁参数（回测标定 v3.1）──
    ADX_GATE = 22          # ADX 下界：趋势确实存在
    ADX_MAX = 60.0         # v3.1：宽止损回测下 A60 优于 A30/A40（A30 是窄止损 regime 过拟合）
    DI_DIFF_GATE = 5       # 回测：5/10，效果无差异
    DIV_LOOKBACK = 8       # v3.1：背离回看根数，网格冠军 D8
    # v3.1 回测结论（M30, 2026-03~2026-08, DB源, 5419 根）：
    #   默认 S4/A30/-/D8 + SL=3.0ATR → 胜率/净PnL 较 v3 默认(1.5ATR)显著提升，
    #   且原版 v2 同口径在该数据下跑出 57 笔（原 26 笔为更小口径），
    #   验证「瓶颈在止损过窄(MAE≈$25 > SL=$18)」而非入场。详见 backtest/sl_sweep.py。
    SCORE_MIN = 4
    REQUIRE_PIERCE = False # v3.1：取消插针硬门禁（网格 - 优于 P）
    SERIES_LEN = 12        # v3：向 base 请求的历史序列长度（≥ DIV_LOOKBACK+2）

    # ── 入场参数 ──
    RSI_OVERSOLD = 30      # 超卖阈值
    RSI_OVERBOUGHT = 70    # 超买阈值
    MFI_OVERSOLD = 25      # 超卖阈值
    MFI_OVERBOUGHT = 75    # 超买阈值
    BB_ENTRY_OFFSET = 5    # 入场：价格与 BB 轨的触及偏移

    # ── 出场参数（回测确定）──
    BB_EXIT_OFFSET = 8     # 回测：5/8/10，M30最佳8/10
    TIME_STOP_BARS = 48    # 回测：TS=48平衡鱼出场和死单风险

    # ── 风控 ──
    FIXED_LOTS = 0.01
    MAX_SLIPPAGE = 30
    SL_ATR_MULT = 3.0       # v3.1：硬止损倍数（1.5→3.0，解决 SL 落在 MAE 内被提前扫损）

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
        # v3：最近一次入场打分详情（供日志/排查）
        self._last_entry_score: Optional[dict] = None
        self._series_warned = False

    # ─────────────── 辅助 ───────────────

    def _get_bb(self) -> Optional[dict]:
        bb = self.get_indicator("bb")
        if isinstance(bb, dict) and "mid" in bb:
            return bb
        return None

    # ─────────────── 入场逻辑 ───────────────

    def generate_signal(self) -> Optional[tuple]:
        """v3 入场：硬门禁（趋势存在+极端已触及）+ 衰竭打分"""
        candles = self.candles
        if len(candles) < 30:
            return None

        # ── bar1 = 最近已闭合 K 线（禁止用 forming bar0 做确认判定）──
        bar1 = candles[-2]
        bb = self._get_bb()
        if bb is None:
            return None

        # ── 历史序列（旧→新，末项 = bar1）──
        n = max(self.SERIES_LEN, self.DIV_LOOKBACK + 2)
        series = {k: self.get_indicator_series(k, n) for k in
                  ("rsi", "mfi", "adx", "pdi", "ndi", "bb_width")}
        closes = self.get_bar1_series("close", n)
        if len(closes) < 3 and not self._series_warned:
            self._series_warned = True
            logger.warning(f"[{self.name}] 指标历史序列不足({len(closes)}根)，"
                           f"背离/掉头类判定会降级；请确认 indicator_snapshots 已回填")

        seq_rsi = series["rsi"]
        ctx = {
            "rsi": seq_at(seq_rsi, 0), "rsi_prev": seq_at(seq_rsi, 1),
            "mfi": seq_at(series["mfi"], 0), "mfi_prev": seq_at(series["mfi"], 1),
            "adx": seq_at(series["adx"], 0), "adx_prev": seq_at(series["adx"], 1),
            "pdi": seq_at(series["pdi"], 0), "pdi_prev": seq_at(series["pdi"], 1),
            "ndi": seq_at(series["ndi"], 0), "ndi_prev": seq_at(series["ndi"], 1),
            "bb_lower": float(bb["lower"]), "bb_upper": float(bb["upper"]),
            "bb_width": seq_at(series["bb_width"], 0),
            "bb_width_prev": seq_at(series["bb_width"], 1),
            "close": bar1.close, "low": bar1.low, "high": bar1.high,
            "closes": closes, "rsis": seq_rsi,
        }

        pdi, ndi = ctx["pdi"], ctx["ndi"]
        if pdi is None or ndi is None:
            return None
        side = "LONG" if ndi > pdi else "SHORT"

        params = EntryParams(
            adx_min=self.ADX_GATE, adx_max=self.ADX_MAX, di_diff_min=self.DI_DIFF_GATE,
            rsi_os=self.RSI_OVERSOLD, rsi_ob=self.RSI_OVERBOUGHT,
            mfi_os=self.MFI_OVERSOLD, mfi_ob=self.MFI_OVERBOUGHT,
            bb_entry_offset=self.BB_ENTRY_OFFSET,
            div_lookback=self.DIV_LOOKBACK, score_min=self.SCORE_MIN,
            require_pierce=self.REQUIRE_PIERCE,
        )

        res = score_entry(side, ctx, params)
        self._last_entry_score = res
        if not res["pass"]:
            return None

        adx = ctx["adx"]
        if side == "LONG":
            logger.info(f"[{self.name}] 信号做多: 衰竭分 {res['score']}/{res['max']} "
                        f"ADX={adx:.1f} -DI={ndi:.1f}>+DI={pdi:.1f} "
                        f"RSI={ctx['rsi']:.1f} MFI={ctx['mfi']:.1f} "
                        f"low={bar1.low:.2f}/close={bar1.close:.2f}/下轨={bb['lower']:.2f} "
                        f"| {' + '.join(res['reasons'])}")
            return (OrderType.BUY, 1, 0, ["RSI-BB-TREND-LONG"], [], {})
        else:
            logger.info(f"[{self.name}] 信号做空: 衰竭分 {res['score']}/{res['max']} "
                        f"ADX={adx:.1f} +DI={pdi:.1f}>-DI={ndi:.1f} "
                        f"RSI={ctx['rsi']:.1f} MFI={ctx['mfi']:.1f} "
                        f"high={bar1.high:.2f}/close={bar1.close:.2f}/上轨={bb['upper']:.2f} "
                        f"| {' + '.join(res['reasons'])}")
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

    # ─────────────── 出场逻辑 ───────────────

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
            bb_compare_offset = bb["upper"] - self.BB_EXIT_OFFSET   # close < 上轨 - offset
        else:
            # 做空：极限区 = 超卖 (RSI≤30, MFI≤25)
            rsi_extreme_val = 30
            mfi_extreme_val = 25
            rsi_exit_val = 30
            mfi_exit_val = 25
            bb_compare_offset = bb["lower"] + self.BB_EXIT_OFFSET   # close > 下轨 + offset

        # ── 更新鱼状态 ──

        # 检查 RSI 是否进入极限区
        if not state["rsi_extreme"]:
            if (is_buy and rsi >= rsi_extreme_val) or (not is_buy and rsi <= rsi_extreme_val):
                state["rsi_extreme"] = True
                if state["first_extreme_type"] is None:
                    state["first_extreme_type"] = "rsi"
                    state["first_extreme_bar"] = len(self.candles)

        # 检查 MFI 是否进入极限区
        if not state["mfi_extreme"]:
            if (is_buy and mfi >= mfi_extreme_val) or (not is_buy and mfi <= mfi_extreme_val):
                state["mfi_extreme"] = True
                if state["first_extreme_type"] is None:
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
                del self._fish_state[ticket]
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
                del self._fish_state[ticket]
                return True

        return False