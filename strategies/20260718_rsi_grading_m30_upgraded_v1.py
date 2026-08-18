"""
M30 RSI分级Score升级版 v5_upgraded — RSI+MA14+BB升级
===================================
基于 rsi_grading_m30_optimized 升级:
  - RSI threshold重定义: <20=+2, 20~35=+1, 35~65=0, 65~80=+1, >80=+2
  - thresholdlock 3 分（极端 RSI 自带 2 分→只需 1 其他因子；正常 RSI 需 3 因子对齐）
  - 其他逻辑不变: ADX>28 趋-trendGate + EMA9/21 趋-trend感知出场
data源: all指标从 DataFactory read
"""
import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v5_upgraded"
STRATEGY_MAGIC = 660904
STRATEGY_LEGACY_MAGICS: list[int] = [660902, 660903]
STRATEGY_CHANGELOG = [
    {"version": "v6_optimized", "magic": 660904, "date": "2026-08-08",
     "desc": "optimize版: restoreADX>28趋-trend方向Gate(禁反 lots), 新增ADX>25趋-trend加分(+1)"},
    {"version": "v5_upgraded", "magic": 660904, "date": "2026-07-18",
     "desc": "升级版: RSI<20/+2, 20~35/+1, 35~65/0, 65~80/+1, >80/+2; 固定threshold3分"},
]


class RSIGradingM30Upgraded(BaseStrategy):
    """M30 RSI分级Score升级版 (固定threshold3分 + RSI极端+2/bound+1/正常0)"""

    name = "rsi_grading_m30_upgraded"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)

        # Entry params
        self.score_threshold = 3          # 固定 3 分

        # RSI threshold（升级版定义）
        self.rsi_extreme_os = 20          # 极端超卖 <20 → +2
        self.rsi_os = 35                  # 超卖 <35 → +1
        self.rsi_ob = 65                  # 超买 >65 → +1
        self.rsi_extreme_ob = 80          # 极端超买 >80 → +2

        # Exit params (EMA趋-trend感知, with宽逆窄)
        self.trend_trail = 2.0
        self.trend_hard = 2.0
        self.counter_trail = 1.0
        self.counter_hard = 1.0

        # ADX>28 趋-trendGate
        self.adx_threshold = 28
        self.ema_fast = 9
        self.ema_slow = 21

        # 指标param
        self.bb_period = 20
        self.bb_std = 2.0
        self.rsi_period = 14
        self.atr_period = 20
        self.ma14_period = 14

        # Positions跟踪
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None

    def get_adx_data(self) -> Optional[dict]:
        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        if adx is None:
            return None
        return {"adx": adx, "pdi": pdi, "ndi": ndi}

    def refresh_data(self, count: int = 350):
        super().refresh_data(count)

    # ─────────────── Indicator helpers ───────────────

    def _get_ma14_trend(self) -> str:
        sma14 = self.get_indicator("sma_14")
        close = self.get_indicator("close")
        if sma14 is None or close is None:
            return 'NEUTRAL'
        return 'UP' if close > sma14 else 'DOWN'

    # ─────────────── RSI 方向反转检测 ───────────────

    def _get_rsi_direction(self) -> tuple[bool, bool]:
        """RSI 方向反转检测（从 DataFactory read RSI 序列比较）"""
        rsi_curr = self.get_indicator("rsi")
        rsi_5 = self.get_indicator("rsi_5")
        rsi_10 = self.get_indicator("rsi_10")
        if rsi_curr is None or rsi_5 is None or rsi_10 is None:
            return (False, False)

        # rsi_5 比 rsi_10 快，rsi_curr 比 rsi_5 快
        # 反转: 短w期从低于长w期变为高于长w期（或反之）
        long_boost = rsi_5 > rsi_10 and rsi_curr > rsi_5
        short_boost = rsi_5 < rsi_10 and rsi_curr < rsi_5
        return (long_boost, short_boost)

    # ─────────────── 新版 RSI Score ───────────────

    def _score_rsi(self, rsi_val: float) -> tuple[int, int, str]:
        """RSI Score规则（区分多空方向）:
          <20  → long+2 (极端超卖), short+0
          20~35 → long+1, short+0
          35~65 → long+0, short+0 (正常区)
          65~80 → long+0, short+1
          >80  → long+0, short+2 (极端超买)
        return: (long_add, short_add, label)
        """
        if rsi_val < self.rsi_extreme_os:
            return (2, 0, f"RSI-{rsi_val:.0f}(极低)")
        if rsi_val < self.rsi_os:
            return (1, 0, f"RSI-{rsi_val:.0f}")
        if rsi_val > self.rsi_extreme_ob:
            return (0, 2, f"RSI-{rsi_val:.0f}(极高)")
        if rsi_val > self.rsi_ob:
            return (0, 1, f"RSI-{rsi_val:.0f}")
        return (0, 0, "")

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 100:
            return None

        closes = self.get_close_prices()
        close = closes[-1]

        bb = self.get_indicator("bb")
        if bb is None:
            return None

        rsi_val = self.get_indicator("rsi")
        if rsi_val is None:
            return None

        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return None

        adx = self.get_indicator("adx")
        ma14_trend = self._get_ma14_trend()

        rsi_long_boost, rsi_short_boost = self._get_rsi_direction()

        # ── Scoring — threshold固定 3 分 ──
        long_score = 0
        long_factors = []
        short_score = 0
        short_factors = []

        # MA14
        if ma14_trend == 'UP':
            long_score += 1
            long_factors.append("MA14-UP")
        elif ma14_trend == 'DOWN':
            short_score += 1
            short_factors.append("MA14-DN")

        # BB touch
        if close <= bb['lower']:
            long_score += 1
            long_factors.append(f"BB-BOT({bb['lower']:.1f})")
        if close >= bb['upper']:
            short_score += 1
            short_factors.append(f"BB-TOP({bb['upper']:.1f})")

        # RSI 新版Score（区分多空方向）
        rsi_long_add, rsi_short_add, rsi_label = self._score_rsi(rsi_val)
        if rsi_long_add > 0:
            long_score += rsi_long_add
            long_factors.append(rsi_label)
        if rsi_short_add > 0:
            short_score += rsi_short_add
            short_factors.append(rsi_label)

        # RSI 方向反转
        if rsi_long_boost:
            long_score += 1
            long_factors.append("RSI-反转↑")
        if rsi_short_boost:
            short_score += 1
            short_factors.append("RSI-反转↓")

        # ── BB expand  + MFI方向一致拦截（防趋-trend加速接飞刀） ──
        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _bb = self.get_indicator("bb")
        if _bwr and _bwr > 1.05 and _bwd == "up" and _mfi is not None and _mfi_dir and _bb:
            _price_above_mid = close > _bb["mid"]
            if _price_above_mid and _mfi_dir in ("up", "flat"):
                short_score = 0
                short_factors.append("BBW-MFI-UP↑")
                logger.info(f"[{self.name}] BB expand + price > mid + MFI rising，block short")
            if not _price_above_mid and _mfi_dir in ("down", "flat"):
                long_score = 0
                long_factors.append("BBW-MFI-DN↓")
                logger.info(f"[{self.name}] BB expand + price < mid + MFI falling，block long")

        # ADX>28 趋-trendGate — 方向性拦截: 趋-trend方向禁反 lots
        if adx is not None and adx > 28:
            gate_side = 'short' if ma14_trend == 'UP' else 'long'
        else:
            gate_side = None

        # 趋-trend跟随加分（ADX>25 时给with-trend方向+1，抓暴涨暴跌行情）
        if adx is not None and adx > 25:
            if ma14_trend == 'UP':
                long_score += 1
                long_factors.append("TREND-BOOST")
            elif ma14_trend == 'DOWN':
                short_score += 1
                short_factors.append("TREND-BOOST")

        # ── Decision ──
        signal = None
        signal_str = "No signal"

        can_long = gate_side != 'long'
        can_short = gate_side != 'short'

        effective_threshold = self.score_threshold  # 始终 3

        if can_long and long_score >= effective_threshold:
            signal = OrderType.BUY
            signal_str = "LONG"
        elif can_short and short_score >= effective_threshold:
            signal = OrderType.SELL
            signal_str = "SELL"

        if gate_side and not signal:
            signal_str += f" ({'上升趋-trend禁空' if gate_side == 'short' else '下降趋-trend禁多'})"

        detail_parts = []
        if long_factors:
            detail_parts.append("LONG: " + " ".join(long_factors))
        if short_factors:
            detail_parts.append("SHORT: " + " ".join(short_factors))
        logger.info(
            f"[{self.name}] Score: {long_score}/{short_score} {signal_str}  "
            f"{' | '.join(detail_parts) if detail_parts else '无'}"
        )

        ema9_v = self.get_indicator("ema_9")
        ema21_v = self.get_indicator("ema_21")
        gate_log = ""
        if gate_side:
            gate_log = " [Gate]" + ("禁空" if gate_side == 'short' else "禁多")
        ema_log = ""
        if ema9_v is not None and ema21_v is not None:
            ema_log = f" EMA9={ema9_v:.2f} EMA21={ema21_v:.2f}"
        adx_log = f" ADX={adx:.1f}" if adx else ""
        logger.info(
            f"[{self.name}] Price={close:.2f} RSI={rsi_val:.1f}"
            f" BB={bb['lower']:.1f}/{bb['upper']:.1f} ATR={atr_val:.2f}"
            f"{adx_log}{ema_log}{gate_log}"
        )

        iv = {
            "close": round(close, 2), "rsi": round(rsi_val, 1),
            "atr": round(atr_val, 2),
            "bb_upper": round(bb["upper"], 2), "bb_lower": round(bb["lower"], 2),
            "bb_mid": round(bb["mid"], 2), "ma14_trend": ma14_trend,
            "adx": round(adx, 1) if adx else 0,
            "pdi": self.get_indicator("pdi") or 0,
            "ndi": self.get_indicator("ndi") or 0,
            "ema9": round(ema9_v, 2) if ema9_v is not None else 0,
            "ema21": round(ema21_v, 2) if ema21_v is not None else 0,
            "gate": gate_side or "",
        }
        return (signal, long_score, short_score, long_factors, short_factors, iv)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        is_buy = direction == OrderType.BUY
        _, hard = self._get_exit_multipliers(is_buy)
        dist = atr_val * hard
        if is_buy:
            sl = round(entry_price - dist, 2)
            tp = 0  # 无固定止盈，交给 check_ema20_exit 自然出场
        else:
            sl = round(entry_price + dist, 2)
            tp = 0
        return sl, tp

    def _get_exit_multipliers(self, is_buy: bool) -> tuple[float, float]:
        """EMA9/21 趋-trend感知"""
        ema9 = self.get_indicator("ema_9")
        ema21 = self.get_indicator("ema_21")
        trend_up = ema9 is not None and ema21 is not None and ema9 > ema21

        if (is_buy and trend_up) or (not is_buy and not trend_up):
            return self.trend_trail, self.trend_hard
        return self.counter_trail, self.counter_hard

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """趋-trend感知出场: 使用 BaseStrategy._run_exit_policy 统一执行出场策略"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")
        current_price = bid if is_buy else ask

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
                "peak_profit": 0.0,
            }

        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return False

        trail, hard = self._get_exit_multipliers(is_buy)
        reg = "with" if (trail == self.trend_trail) else "逆"
        pdd = self.profit_drawdown_pct
        _ax_adx = self.get_indicator("adx")
        if _ax_adx and _ax_adx > 25:
            pdd = max(pdd, 0.5) if reg == "with" else min(pdd, 0.15)

        should_exit, exit_type, detail = self._run_exit_policy(
            td, is_buy, current_price, atr_val, trail, hard,
            pdd=pdd, update_peak_guard=False,
        )
        if not should_exit:
            self._last_exit_detail = None
            return False

        direction = "BUY" if is_buy else "SELL"
        detail["direction"] = direction
        detail["reg"] = reg
        # 带趋-trend感知前缀的 exit_type
        prefixed_type = f"{reg}_{exit_type}" if exit_type in ("trail_stop", "hard_stop") else exit_type
        self._last_exit_detail = {"exit_type": prefixed_type, **detail}

        if exit_type == "breakeven":
            self._last_profit_exit_time[direction] = time.time()

        logger.info(f"[{self.name}] {direction} {reg} {exit_type} ticket={ticket} {detail}")
        del self._trail_data[ticket]
        return True

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        """defaultverify：tick 价不跑出 BB bound"""
        direction = signal.get("direction", "BUY")
        bb = latest.get("bb") or signal.get("indicator_values", {}).get("bb") or {}
        if direction == "BUY":
            if bb.get("lower") and tick_price > bb["lower"] * 1.005:
                return False
        else:
            if bb.get("upper") and tick_price < bb["upper"] * 0.995:
                return False
        return True
