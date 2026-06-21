"""
M30 RSI分级评分 + MA14 + BB 均值回归策略
========================================
基于回测最优配置 (m30_final_bt.py section 4):
  - RSI 分级评分: <20→+2, 20-30→+1, >70→+2, 65-70→+1
  - MA14 方向 (±1)
  - BB 触轨 (±1)
  - 无 RSI 方向因子
  - 阈值 2, trail=2.0×ATR, hard=3.0×ATR
  - 短侧 RSI 过滤: RSI<20 禁空, RSI 20-30 扣一分

回测结果: 27 笔 $44.32 PF=1.67 WR=37% (M30 双品种盈利)
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 660902
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 660902, "date": "2026-06-21", "desc": "初始上线: RSI分级评分+MA14+BB, thr=2, trail=2.0 hard=3.0"},
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

        # Exit params — 宽止损保留盈利空间
        self.trail_mult = 2.0    # 从峰值回撤 2×ATR 止盈
        self.hard_mult = 3.0     # 亏损 3×ATR 硬止损

        # 新闻风控
        self.tight_exit_mode: bool = False

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

        # ── Decision ──
        signal = None
        signal_str = "无信号"

        if long_score >= self.score_threshold:
            signal = OrderType.BUY
            signal_str = "LONG"
        elif short_score >= self.score_threshold:
            # RSI 深超卖禁空
            if rsi_val < self.rsi_deep_os:
                signal_str = f"RSI深超卖({rsi_val:.0f})禁空"
            elif rsi_val < self.rsi_os:
                short_score -= 1
                if short_score >= self.score_threshold:
                    signal = OrderType.SELL
                    signal_str = "SELL(罚)"
                else:
                    signal_str = f"RSI扣分({short_score}分)"
            else:
                signal = OrderType.SELL
                signal_str = "SELL"

        # Log
        detail_parts = []
        if long_factors: detail_parts.append("LONG: " + " ".join(long_factors))
        if short_factors: detail_parts.append("SHORT: " + " ".join(short_factors))
        logger.info(
            f"[{self.name}] 评分: {long_score}/{short_score} {signal_str}  "
            f"{' | '.join(detail_parts) if detail_parts else '无'}"
        )
        logger.info(
            f"[{self.name}] Price={close:.2f} RSI={rsi_val:.1f} "
            f"BB={bb['lower']:.1f}/{bb['upper']:.1f} ATR={atr_val:.2f}"
        )

        iv = {
            "close": round(close, 2), "rsi": round(rsi_val, 1),
            "atr": round(atr_val, 2),
            "bb_upper": round(bb["upper"], 2), "bb_lower": round(bb["lower"], 2),
            "bb_mid": round(bb["sma"], 2), "ma14_trend": ma14_trend,
        }
        return (signal, long_score, short_score, long_factors, short_factors, iv)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        dist = atr_val * self.hard_mult
        if direction == OrderType.BUY:
            sl = round(entry_price - dist, 2)
            tp = round(entry_price + dist * 50, 2)
        else:
            sl = round(entry_price + dist, 2)
            tp = max(round(entry_price - dist * 50, 2), 0)
        return sl, tp

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """宽止损出场: 回撤止盈 + 硬止损"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
            }

        td = self._trail_data[ticket]
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return False

        trail = self.trail_mult
        hard = self.hard_mult
        if self.tight_exit_mode:
            trail = 0.5
            hard = 1.0

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            loss = td["entry"] - bid

            # 回撤止盈 (从最高点回落 trail×ATR)
            drawdown = td["highest"] - bid
            if drawdown > atr_val * trail:
                logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} peak={td['highest']:.2f} drawdown={drawdown:.2f}")
                self._last_exit_detail = {"exit_type": "trail_stop", "drawdown": round(drawdown, 2), "atr": round(atr_val, 2)}
                del self._trail_data[ticket]
                return True
            # 硬止损
            if loss > atr_val * hard:
                logger.info(f"[{self.name}] BUY HardStop ticket={ticket} loss={loss:.2f}")
                self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss, 2), "atr": round(atr_val, 2)}
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            loss = ask - td["entry"]

            # 回撤止盈
            rally = ask - td["lowest"]
            if rally > atr_val * trail:
                logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} low={td['lowest']:.2f} rally={rally:.2f}")
                self._last_exit_detail = {"exit_type": "trail_stop", "rally": round(rally, 2), "atr": round(atr_val, 2)}
                del self._trail_data[ticket]
                return True
            # 硬止损
            if loss > atr_val * hard:
                logger.info(f"[{self.name}] SELL HardStop ticket={ticket} loss={loss:.2f}")
                self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss, 2), "atr": round(atr_val, 2)}
                del self._trail_data[ticket]
                return True

        self._last_exit_detail = None
        return False
