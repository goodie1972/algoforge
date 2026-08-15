"""
M30 RSI分级Scoreoptimize版 v3_optimized — RSI+MA14+BBoptimize
===================================
基于 rsi_grading_m30_20260630.py v5 optimize:
  - CRITICAL: ADX<=28 时保持threshold 2 (原提升到 3, 导致整w零Signal)
  - restore RSI 方向反转因子 (v3 去除  RSI 短侧filter)
  - 放宽 RSI threshold: oversold<=35, overbought>=60
  - 保留 ADX>28 趋-trendGate + EMA9/21 趋-trend感知出场
  - 魔术码 660903, 旧魔术 660902 保留供回测
data源: all指标从 DataFactory TA-Lib read
"""

import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v3_optimized"
STRATEGY_MAGIC = 660903
STRATEGY_LEGACY_MAGICS: list[int] = [660902]
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 660902, "date": "2026-06-21", "desc": "初始上线: RSI分级Score+MA14+BB, thr=2, trail=2.0 hard=3.0"},
    {"version": "v2", "magic": 660902, "date": "2026-06-22", "desc": "新增ADX>28趋-trend增强: +DI/-DI方向Score+2"},
    {"version": "v3", "magic": 660902, "date": "2026-06-22", "desc": "removetight_exit_mode and RSI短侧filter, exit改trail=1.5 hard=1.5"},
    {"version": "v4", "magic": 660902, "date": "2026-06-22", "desc": "趋-trend增强改EMA9/21定方向+DI差值定强度"},
    {"version": "v5", "magic": 660902, "date": "2026-06-22", "desc": "重构: ADX>28趋-trendGate(禁reverse), EMA9/21趋-trend感知出场(with2.0逆1.0)"},
    {"version": "v3_optimized", "magic": 660903, "date": "2026-07-11", "desc": "optimize版: ADX<=28保持threshold2, restoreRSI方向反转因子, 放宽RSIthreshold至35/60"},
]


class RSIGradingM30Optimized(BaseStrategy):
    """M30 RSI分级Scoreoptimize版 (restoreRSI方向反转因子 + 放宽threshold + ADX低threshold不提升)"""

    name = "rsi_grading_m30_optimized"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)

        # Entry params (from optimization)
        self.score_threshold = 2

        # RSI threshold (放宽)
        self.rsi_os = 35          # oversold (was 30)
        self.rsi_ob = 60          # overbought (was 65)
        self.rsi_deep_os = 25     # deep oversold (was 20)
        self.rsi_deep_ob = 75     # deep overbought (was 70)

        # Exit params (EMA趋-trend感知, with宽逆窄)
        self.trend_trail = 2.0   # with趋-trend: 峰谷drawdown 2*ATR
        self.trend_hard = 2.0    # with趋-trend: loss 2*ATR 硬止损
        self.counter_trail = 1.0 # 逆趋-trend: 峰谷drawdown 1*ATR
        self.counter_hard = 1.0  # 逆趋-trend: loss 1*ATR 硬止损

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
        """M30 MA14 趋-trend（保留独有逻辑）"""
        sma14 = self.get_indicator("sma_14")
        close = self.get_indicator("close")
        if sma14 is None or close is None:
            return 'NEUTRAL'
        return 'UP' if close > sma14 else 'DOWN'

    def _calc_ema(self, closes: list[float], period: int) -> Optional[float]:
        """EMA calc（保留用于 _get_exit_multipliers    EMA9/21 趋-trend判断）"""
        if len(closes) < period:
            return None
        k = 2.0 / (period + 1)
        ema = closes[0]
        for p in closes[1:]:
            ema = (p - ema) * k + ema
        return ema

    def _get_rsi_direction(self, closes: list[float]) -> tuple[bool, bool]:
        """检测 RSI 反转方向.

        基于连续 3  RSI 值判断趋-trend反转:
          - long_boost: RSI 之前下跌、现在回升 (反转看多)
          - short_boost: RSI 之前上涨、现在回落 (反转看空)
        """
        period = self.rsi_period
        if len(closes) < period + 4:
            return (False, False)

        def _rsi_sma(prices: list[float]) -> float:
            """SMA-based RSI calc（用于判断方向，无需精确 Wilder 平滑）"""
            gains = 0.0
            losses = 0.0
            for i in range(1, len(prices)):
                chg = prices[i] - prices[i - 1]
                if chg > 0:
                    gains += chg
                else:
                    losses -= chg
            ag = gains / period
            al = losses / period
            if al == 0:
                return 100.0
            return 100.0 - 100.0 / (1.0 + ag / al)

        # RSI for 3 consecutive bars: t (latest), t-1, t-2
        rsi_t = _rsi_sma(closes[-(period + 1):])         # latest
        rsi_t1 = _rsi_sma(closes[-(period + 2):-1])      # one bar before
        rsi_t2 = _rsi_sma(closes[-(period + 3):-2])      # two bars before

        # RSI was falling (t-1 < t-2) and now rising (t > t-1) -> reversal up
        long_boost = rsi_t1 < rsi_t2 and rsi_t > rsi_t1
        # RSI was rising (t-1 > t-2) and now falling (t < t-1) -> reversal down
        short_boost = rsi_t1 > rsi_t2 and rsi_t < rsi_t1

        return (long_boost, short_boost)

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
        adx_data = {"adx": adx, "pdi": self.get_indicator("pdi"), "ndi": self.get_indicator("ndi")}

        ma14_trend = self._get_ma14_trend()

        # RSI 方向反转因子
        rsi_long_boost, rsi_short_boost = self._get_rsi_direction(closes)

        # ── Scoring ──
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

        # RSI 分级 (放宽threshold)
        if rsi_val < self.rsi_deep_os:
            long_score += 2
            long_factors.append(f"RSI-{rsi_val:.0f}(deep)")
        elif rsi_val < self.rsi_os:
            long_score += 1
            long_factors.append(f"RSI-{rsi_val:.0f}")
        if rsi_val > self.rsi_deep_ob:
            short_score += 2
            short_factors.append(f"RSI-{rsi_val:.0f}(deep)")
        elif rsi_val > self.rsi_ob:
            short_score += 1
            short_factors.append(f"RSI-{rsi_val:.0f}")

        # RSI 方向反转因子 (restore)
        if rsi_long_boost:
            long_score += 1
            long_factors.append("RSI-反转↑")
        if rsi_short_boost:
            short_score += 1
            short_factors.append("RSI-反转↓")

        # ADX>28 趋-trendGate: EMA9>EMA21→禁空, EMA9<EMA21→禁多
        gate_side = None  # None=无Gate, 'long'=禁多, 'short'=禁空
        if adx is not None and adx > self.adx_threshold:
            ema9 = self.get_indicator("ema_9")
            ema21 = self.get_indicator("ema_21")
            if ema9 is not None and ema21 is not None:
                if ema9 > ema21:
                    gate_side = 'short'
                elif ema9 < ema21:
                    gate_side = 'long'

        # ── Decision ──
        # CRITICAL FIX: 始终使用固定threshold 2, 不再因 ADX<=28 提升到 3
        # (原strategy整w零Signal, 因为 ADX 长期 <=28)
        signal = None
        signal_str = "No signal"

        can_long = gate_side != 'long'
        can_short = gate_side != 'short'

        effective_threshold = self.score_threshold

        if can_long and long_score >= effective_threshold:
            signal = OrderType.BUY
            signal_str = "LONG"
        elif can_short and short_score >= effective_threshold:
            signal = OrderType.SELL
            signal_str = "SELL"

        if gate_side and not signal:
            signal_str += f" ({'上升趋-trend禁空' if gate_side == 'short' else '下降趋-trend禁多'})"

        # Log
        detail_parts = []
        if long_factors:
            detail_parts.append("LONG: " + " ".join(long_factors))
        if short_factors:
            detail_parts.append("SHORT: " + " ".join(short_factors))
        logger.info(
            f"[{self.name}] Score: {long_score}/{short_score} {signal_str}  "
            f"{' | '.join(detail_parts) if detail_parts else '无'}"
        )
        adx_log = f" ADX={adx_data['adx']:.1f}" if adx_data else ""

        # read EMA 用于log (独立于 if adx 块, 避免作用域问题)
        ema9_v = self.get_indicator("ema_9")
        ema21_v = self.get_indicator("ema_21")
        gate_log = ""
        if gate_side:
            gate_log = " [Gate]" + ("禁空" if gate_side == 'short' else "禁多")
        ema_log = ""
        if ema9_v is not None and ema21_v is not None:
            ema_log = f" EMA9={ema9_v:.2f} EMA21={ema21_v:.2f}"
        logger.info(
            f"[{self.name}] Price={close:.2f} RSI={rsi_val:.1f}"
            f" BB={bb['lower']:.1f}/{bb['upper']:.1f} ATR={atr_val:.2f}{adx_log}{ema_log}{gate_log}"
        )

        iv = {
            "close": round(close, 2), "rsi": round(rsi_val, 1),
            "atr": round(atr_val, 2),
            "bb_upper": round(bb["upper"], 2), "bb_lower": round(bb["lower"], 2),
            "bb_mid": round(bb["mid"], 2), "ma14_trend": ma14_trend,
            "adx": round(adx_data["adx"], 1) if adx_data else 0,
            "pdi": round(adx_data["pdi"], 1) if adx_data else 0,
            "ndi": round(adx_data["ndi"], 1) if adx_data else 0,
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
            tp = round(entry_price + dist * 50, 2)
        else:
            sl = round(entry_price + dist, 2)
            tp = max(round(entry_price - dist * 50, 2), 0)
        return sl, tp

    def _get_exit_multipliers(self, is_buy: bool) -> tuple[float, float]:
        """EMA9/21 趋-trend感知: with趋-trend宽, 逆趋-trend窄"""
        ema9 = self.get_indicator("ema_9")
        ema21 = self.get_indicator("ema_21")
        trend_up = ema9 is not None and ema21 is not None and ema9 > ema21

        if (is_buy and trend_up) or (not is_buy and not trend_up):
            return self.trend_trail, self.trend_hard
        return self.counter_trail, self.counter_hard

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """EMA趋-trend感知出场: with趋-trend宽/逆趋-trend窄"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

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
            pdd = max(pdd, 0.5)

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - td["entry"]
            loss = td["entry"] - bid
            td["peak_profit"] = max(td["peak_profit"], current_profit)

            # 保本出场：走过>=0.3ATR盈利后回到成本附近
            if self._check_breakeven_exit(td, current_profit, atr_val, td["entry"], is_buy):
                logger.info(f"[{self.name}] BUY Breakeven ticket={ticket} profit=${current_profit:.2f}")
                self._last_exit_detail = {"exit_type": "breakeven", "profit": round(current_profit, 2)}
                self._last_profit_exit_time["BUY"] = time.time()
                del self._trail_data[ticket]
                return True

            if current_profit > 0:
                if self.profit_drawdown_enabled and td["peak_profit"] > atr_val * self.profit_drawdown_min_peak_atr:
                    profit_ratio = current_profit / td["peak_profit"]
                    if profit_ratio < (1 - pdd):
                        logger.info(f"[{self.name}] BUY ProfitStop ticket={ticket} profit=${current_profit:.2f} peak=${td['peak_profit']:.2f}")
                        self._last_exit_detail = {"exit_type": "profit_drawdown", "peak_profit": round(td["peak_profit"], 2), "current_profit": round(current_profit, 2), "atr": round(atr_val, 2), "reg": reg}
                        del self._trail_data[ticket]
                        return True

            drawdown = td["highest"] - bid
            if drawdown > atr_val * trail:
                logger.info(f"[{self.name}] BUY {reg}TrailStop ticket={ticket} peak={td['highest']:.2f} drawdown={drawdown:.2f}")
                self._last_exit_detail = {"exit_type": f"{reg}_trail_stop", "drawdown": round(drawdown, 2), "atr": round(atr_val, 2)}
                del self._trail_data[ticket]
                return True
            if current_profit <= 0 and loss > atr_val * hard:
                logger.info(f"[{self.name}] BUY {reg}HardStop ticket={ticket} loss={loss:.2f}")
                self._last_exit_detail = {"exit_type": f"{reg}_hard_stop", "loss": round(loss, 2), "atr": round(atr_val, 2)}
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            current_profit = td["entry"] - ask
            loss = ask - td["entry"]
            td["peak_profit"] = max(td["peak_profit"], current_profit)

            # 保本出场：走过>=0.3ATR盈利后回到成本附近
            if self._check_breakeven_exit(td, current_profit, atr_val, td["entry"], is_buy):
                logger.info(f"[{self.name}] SELL Breakeven ticket={ticket} profit=${current_profit:.2f}")
                self._last_exit_detail = {"exit_type": "breakeven", "profit": round(current_profit, 2)}
                self._last_profit_exit_time["SELL"] = time.time()
                del self._trail_data[ticket]
                return True

            if current_profit > 0:
                if self.profit_drawdown_enabled and td["peak_profit"] > atr_val * self.profit_drawdown_min_peak_atr:
                    profit_ratio = current_profit / td["peak_profit"]
                    if profit_ratio < (1 - pdd):
                        logger.info(f"[{self.name}] SELL ProfitStop ticket={ticket} profit=${current_profit:.2f} peak=${td['peak_profit']:.2f}")
                        self._last_exit_detail = {"exit_type": "profit_drawdown", "peak_profit": round(td["peak_profit"], 2), "current_profit": round(current_profit, 2), "atr": round(atr_val, 2), "reg": reg}
                        del self._trail_data[ticket]
                        return True

            rally = ask - td["lowest"]
            if rally > atr_val * trail:
                logger.info(f"[{self.name}] SELL {reg}TrailStop ticket={ticket} low={td['lowest']:.2f} rally={rally:.2f}")
                self._last_exit_detail = {"exit_type": f"{reg}_trail_stop", "rally": round(rally, 2), "atr": round(atr_val, 2)}
                del self._trail_data[ticket]
                return True
            if current_profit <= 0 and loss > atr_val * hard:
                logger.info(f"[{self.name}] SELL {reg}HardStop ticket={ticket} loss={loss:.2f}")
                self._last_exit_detail = {"exit_type": f"{reg}_hard_stop", "loss": round(loss, 2), "atr": round(atr_val, 2)}
                del self._trail_data[ticket]
                return True

        self._last_exit_detail = None
        return False

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
