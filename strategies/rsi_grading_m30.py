"""
M30 RSI分级评分 + MA14 + BB + ADX>28 趋势门禁
===========================================
基于回测最优配置 (m30_final_bt.py section 4):
  - RSI 分级评分: <20→+2, 20-30→+1, >70→+2, 65-70→+1
  - MA14 方向 (±1)
  - BB 触轨 (±1)
  - ADX>28 趋势门禁: EMA9>EMA21→禁空, EMA9<EMA21→禁多
  - 无 RSI 方向因子，无短侧过滤
  - 阈值 2, EMA趋势感知出场: 顺2.0/逆1.0
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v5"
STRATEGY_MAGIC = 660902
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 660902, "date": "2026-06-21", "desc": "初始上线: RSI分级评分+MA14+BB, thr=2, trail=2.0 hard=3.0"},
    {"version": "v2", "magic": 660902, "date": "2026-06-22", "desc": "新增ADX>28趋势增强: +DI/-DI方向评分+2"},
    {"version": "v3", "magic": 660902, "date": "2026-06-22", "desc": "移除tight_exit_mode和RSI短侧过滤, exit改trail=1.5 hard=1.5"},
    {"version": "v4", "magic": 660902, "date": "2026-06-22", "desc": "趋势增强改EMA9/21定方向+DI差值定强度"},
    {"version": "v5", "magic": 660902, "date": "2026-06-22", "desc": "重构: ADX>28趋势门禁(禁反向), EMA9/21趋势感知出场(顺2.0逆1.0)"},
]


class RSIGradingM30Strategy(BaseStrategy):
    """M30 RSI分级评分均值回归 (去RSI方向) + ATR动态出场"""

    name = "rsi_grading_m30"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)

        # Entry params (from optimization)
        self.score_threshold = 2

        # RSI 阈值
        self.rsi_os = 30
        self.rsi_ob = 65
        self.rsi_deep_os = 20
        self.rsi_deep_ob = 70

        # Exit params (EMA趋势感知, 顺宽逆窄)
        self.trend_trail = 2.0   # 顺趋势: 峰谷回撤 2×ATR
        self.trend_hard = 2.0    # 顺趋势: 亏损 2×ATR 硬止损
        self.counter_trail = 1.0 # 逆趋势: 峰谷回撤 1×ATR
        self.counter_hard = 1.0  # 逆趋势: 亏损 1×ATR 硬止损

        # ADX>28 趋势门禁
        self.adx_threshold = 28
        self.ema_fast = 9
        self.ema_slow = 21

        # 指标参数
        self.bb_period = 20
        self.bb_std = 2.0
        self.rsi_period = 14
        self.atr_period = 20
        self.ma14_period = 14

        # 持仓跟踪
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None

        # 指标缓存
        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

    def get_adx_data(self) -> Optional[dict]:
        return self._calc_adx(14)

    def refresh_data(self, count: int = 350):
        self._cached_atr_key = 0
        self._cached_atr_values = None
        super().refresh_data(count)

    # ─────────────── Indicator helpers ───────────────

    def _calc_rsi(self, closes: list[float], period: int = 14) -> Optional[float]:
        if len(closes) < period + 1: return None
        gains, losses = [], []
        for i in range(1, period + 1):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        for i in range(period + 1, len(closes)):
            diff = closes[i] - closes[i - 1]
            avg_gain = (avg_gain * (period - 1) + max(diff, 0)) / period
            avg_loss = (avg_loss * (period - 1) + max(-diff, 0)) / period
        if avg_loss == 0: return 100.0
        return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    def _calc_bb_levels(self) -> Optional[dict]:
        closes = self.get_close_prices()
        if len(closes) < self.bb_period: return None
        recent = closes[-self.bb_period:]
        sma = sum(recent) / self.bb_period
        variance = sum((c - sma) ** 2 for c in recent) / self.bb_period
        std = math.sqrt(variance)
        return {"sma": sma, "upper": sma + self.bb_std * std, "lower": sma - self.bb_std * std}

    def _calc_atr_values(self, period: int = 20) -> Optional[list[float]]:
        cache_key = len(self.candles)
        if self._cached_atr_key == cache_key and self._cached_atr_values is not None:
            return self._cached_atr_values
        candles = self.candles
        if len(candles) < period + 2: return None
        tr_values = []
        for i in range(1, len(candles)):
            h = candles[i].high
            l_ = candles[i].low
            pc = candles[i - 1].close
            tr = max(h - l_, abs(h - pc), abs(l_ - pc))
            tr_values.append(tr)
        if len(tr_values) < period: return None
        atr_list = [sum(tr_values[:period]) / period]
        for i in range(period, len(tr_values)):
            atr_list.append((atr_list[-1] * (period - 1) + tr_values[i]) / period)
        self._cached_atr_values = atr_list
        self._cached_atr_key = cache_key
        return atr_list

    def _calc_atr(self, period: int = 20) -> Optional[float]:
        vals = self._calc_atr_values(period)
        return vals[-1] if vals and len(vals) > 0 else None

    def _get_ma14_trend(self) -> str:
        closes = self.get_close_prices()
        if len(closes) < self.ma14_period: return 'NEUTRAL'
        ma14 = sum(closes[-self.ma14_period:]) / self.ma14_period
        return 'UP' if closes[-1] > ma14 else 'DOWN'

    def _calc_ema(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period: return None
        k = 2.0 / (period + 1)
        ema = closes[0]
        for p in closes[1:]:
            ema = (p - ema) * k + ema
        return ema

    def _calc_adx(self, period: int = 14) -> Optional[dict]:
        candles = self.candles
        if len(candles) < period + 2: return None
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = self.get_close_prices()
        n = len(highs)
        tr_list, plus_dm, minus_dm = [], [], []
        for i in range(1, n):
            h, l_, pc = highs[i], lows[i], closes[i - 1]
            ph, pl = highs[i - 1], lows[i - 1]
            tr = max(h - l_, abs(h - pc), abs(l_ - pc))
            up = h - ph
            down = pl - l_
            plus_dm.append(up if (up > down and up > 0) else 0)
            minus_dm.append(down if (down > up and down > 0) else 0)
            tr_list.append(tr)
        if len(tr_list) < period: return None
        atr_v = sum(tr_list[:period]) / period
        pdi_v = sum(plus_dm[:period]) / period
        ndi_v = sum(minus_dm[:period]) / period
        if atr_v <= 0: return None
        pdi_v = pdi_v / atr_v * 100
        ndi_v = ndi_v / atr_v * 100
        atr_s, pdi_s, ndi_s = [atr_v], [pdi_v], [ndi_v]
        for i in range(period, len(tr_list)):
            atr_s.append((atr_s[-1] * (period - 1) + tr_list[i]) / period)
            if atr_s[-1] > 0:
                pdi_s.append((pdi_s[-1] * (period - 1) + plus_dm[i] / atr_s[-1] * 100) / period)
                ndi_s.append((ndi_s[-1] * (period - 1) + minus_dm[i] / atr_s[-1] * 100) / period)
            else:
                pdi_s.append(pdi_s[-1])
                ndi_s.append(ndi_s[-1])
        dx = [abs(pdi_s[i] - ndi_s[i]) / max(pdi_s[i] + ndi_s[i], 0.001) * 100 for i in range(len(atr_s))]
        adx = [sum(dx[:period]) / period]
        for i in range(period, len(dx)):
            adx.append((adx[-1] * (period - 1) + dx[i]) / period)
        return {"adx": adx[-1], "pdi": pdi_s[-1], "ndi": ndi_s[-1]}

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 100:
            return None

        closes = self.get_close_prices()
        close = closes[-1]

        bb = self._calc_bb_levels()
        if bb is None: return None

        rsi_val = self._calc_rsi(closes, self.rsi_period)
        if rsi_val is None: return None

        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0: return None

        adx_data = self._calc_adx()

        ma14_trend = self._get_ma14_trend()

        # ── Scoring (去RSI方向) ──
        long_score = 0; long_factors = []
        short_score = 0; short_factors = []

        # MA14
        if ma14_trend == 'UP':
            long_score += 1; long_factors.append("MA14-UP")
        else:
            short_score += 1; short_factors.append("MA14-DN")

        # BB touch
        if close <= bb['lower']:
            long_score += 1; long_factors.append(f"BB-BOT({bb['lower']:.1f})")
        if close >= bb['upper']:
            short_score += 1; short_factors.append(f"BB-TOP({bb['upper']:.1f})")

        # RSI 分级
        if rsi_val < self.rsi_deep_os:
            long_score += 2; long_factors.append(f"RSI-{rsi_val:.0f}(deep)")
        elif rsi_val < self.rsi_os:
            long_score += 1; long_factors.append(f"RSI-{rsi_val:.0f}")
        if rsi_val > self.rsi_deep_ob:
            short_score += 2; short_factors.append(f"RSI-{rsi_val:.0f}(deep)")
        elif rsi_val > self.rsi_ob:
            short_score += 1; short_factors.append(f"RSI-{rsi_val:.0f}")

        # ADX>28 趋势门禁: EMA9>EMA21→禁空, EMA9<EMA21→禁多
        gate_side = None  # None=无门禁, 'long'=禁多, 'short'=禁空
        if adx_data and adx_data["adx"] > self.adx_threshold:
            ema9 = self._calc_ema(closes, self.ema_fast)
            ema21 = self._calc_ema(closes, self.ema_slow)
            if ema9 is not None and ema21 is not None:
                if ema9 > ema21:
                    gate_side = 'short'
                elif ema9 < ema21:
                    gate_side = 'long'

        # ── Decision (ADX>28 门禁禁反向; ADX≤28 提高阈值到 3) ──
        signal = None
        signal_str = "无信号"

        can_long = gate_side != 'long'
        can_short = gate_side != 'short'

        # ADX≤28 无门禁: 需要更高阈值过滤震荡市假信号
        effective_threshold = 3 if (adx_data is None or adx_data["adx"] <= self.adx_threshold) else self.score_threshold

        if can_long and long_score >= effective_threshold:
            signal = OrderType.BUY; signal_str = "LONG"
        elif can_short and short_score >= effective_threshold:
            signal = OrderType.SELL; signal_str = "SELL"

        if gate_side and not signal:
            signal_str += f" ({'上升趋势禁空' if gate_side == 'short' else '下降趋势禁多'})"
        elif effective_threshold != self.score_threshold and not signal:
            signal_str += f" (ADX≤{self.adx_threshold} 阈值提升至 {effective_threshold})"

        # Log
        detail_parts = []
        if long_factors: detail_parts.append("LONG: " + " ".join(long_factors))
        if short_factors: detail_parts.append("SHORT: " + " ".join(short_factors))
        logger.info(
            f"[{self.name}] 评分: {long_score}/{short_score} {signal_str}  "
            f"{' | '.join(detail_parts) if detail_parts else '无'}"
        )
        adx_log = f" ADX={adx_data['adx']:.1f}" if adx_data else ""
        gate_log = ""
        if gate_side:
            gate_log = " [门禁]" + ("禁空" if gate_side == 'short' else "禁多")
        ema9_v = ema9 if 'ema9' in dir() else self._calc_ema(closes, self.ema_fast)
        ema21_v = ema21 if 'ema21' in dir() else self._calc_ema(closes, self.ema_slow)
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
            "bb_mid": round(bb["sma"], 2), "ma14_trend": ma14_trend,
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
        atr_val = self._calc_atr()
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
        """EMA9/21 趋势感知: 顺趋势宽, 逆趋势窄"""
        closes = self.get_close_prices()
        ema9 = self._calc_ema(closes, self.ema_fast)
        ema21 = self._calc_ema(closes, self.ema_slow)
        trend_up = ema9 is not None and ema21 is not None and ema9 > ema21

        if (is_buy and trend_up) or (not is_buy and not trend_up):
            return self.trend_trail, self.trend_hard
        return self.counter_trail, self.counter_hard

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """EMA趋势感知出场: 顺趋势宽/逆趋势窄"""
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
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return False

        trail, hard = self._get_exit_multipliers(is_buy)
        reg = "顺" if (trail == self.trend_trail) else "逆"
        pdd = self.profit_drawdown_pct
        # ADX>25 趋势强 → 放宽回撤
        _ax = self._calc_adx(14)
        if _ax and _ax.get("adx", 0) > 25:
            pdd = max(pdd, 0.5)

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - td["entry"]
            loss = td["entry"] - bid
            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)

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
            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)

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
