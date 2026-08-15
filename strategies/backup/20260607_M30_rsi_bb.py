"""
M30 RSI + 布林带均值回归策略 — ATR动态出场
================================================
- 入场: 5因子评分系统 ≥3 分触发
  ① H1趋势 (SMA200)
  ② BB触轨
  ③ RSI超卖/超买
  ④ M30 RSI方向
  ⑤ 低波动率
- 出场: ATR 动态追踪止损 (Trailing Stop + Hard Stop)
- 双向交易 (Long / Short)
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class M30RSIStrategy(BaseStrategy):
    """M30 RSI + 布林带均值回归 + ATR动态出场"""

    name = "M30_rsi_bb"

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}

        # Entry params (from optimization)
        self.rsi_oversold = 30
        self.rsi_overbought = 65
        self.bb_std = 2.0
        self.score_threshold = 3

        # Exit params (from optimization)
        self.p_trailing_atr = 4.0
        self.p_hard_atr = 3.0

        # Indicator params
        self.bb_period = 20
        self.rsi_period = 14
        self.atr_period = 20

        # H1 data cache (loaded from SQLite)
        self._h1_closes: list[float] = []
        self._h1_candles_cache: list[Candle] = []
        self._last_h1_load = 0

        # ATR cache
        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

    def refresh_data(self, count: int = 350):
        """刷新M30 K线 + 加载H1趋势数据"""
        self._cached_atr_key = 0
        self._cached_atr_values = None
        super().refresh_data(count)
        self._load_h1_data()

    def _load_h1_data(self):
        """从SQLite加载H1收盘价（由引擎每300s同步）"""
        try:
            from data.database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
                "WHERE timeframe='H1' ORDER BY timestamp"
            ).fetchall()
            conn.close()
            self._h1_candles_cache = [
                Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                for r in rows
            ]
            self._h1_closes = [c.close for c in self._h1_candles_cache]
        except Exception as e:
            logger.warning(f"[{self.name}] H1 data load failed: {e}")
            self._h1_closes = []
            self._h1_candles_cache = []

    # ─────────────── Indicator helpers ───────────────

    def _calc_sma(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period: return None
        return sum(closes[-period:]) / period

    def _calc_ema(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period: return None
        k = 2.0 / (period + 1)
        ema = closes[0]
        for p in closes[1:]:
            ema = (p - ema) * k + ema
        return ema

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
            gain = max(diff, 0)
            loss = max(-diff, 0)
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
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
        if vals is None or len(vals) == 0: return None
        return vals[-1]

    def _get_h1_trend(self) -> str:
        """H1 SMA200趋势判断，返回 'UP' / 'DOWN' / 'NEUTRAL'"""
        if len(self._h1_closes) < 200: return 'NEUTRAL'
        sma200 = sum(self._h1_closes[-200:]) / 200
        return 'UP' if self._h1_closes[-1] > sma200 else 'DOWN'

    def _get_m30_rsi_direction(self) -> str:
        """M30 RSI方向: 最近2根完成K线RSI上升→up, 下降→down"""
        closes = self.get_close_prices()
        if len(closes) < self.rsi_period + 4: return 'flat'
        rsi_prev = self._calc_rsi(closes[:-1], self.rsi_period)
        rsi_curr = self._calc_rsi(closes, self.rsi_period)
        if rsi_prev is None or rsi_curr is None: return 'flat'
        if rsi_prev < rsi_curr: return 'up'
        if rsi_prev > rsi_curr: return 'down'
        return 'flat'

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[OrderType]:
        candles = self.candles
        if len(candles) < 100:
            logger.debug(f"[{self.name}] 数据不足: {len(candles)} < 100")
            return None

        closes = self.get_close_prices()
        close = closes[-1]
        low = candles[-1].low
        high = candles[-1].high

        # Indicators
        bb = self._calc_bb_levels()
        if bb is None: return None

        rsi_val = self._calc_rsi(closes, self.rsi_period)
        if rsi_val is None: return None

        atr_val = self._calc_atr()
        if atr_val is None: return None

        h1_trend = self._get_h1_trend()
        m30_rsi_dir = self._get_m30_rsi_direction()

        # Low vol filter: ATR < recent avg price × 2.5%
        vol_recent = sum(closes[-min(10, len(closes)):]) / min(10, len(closes))
        low_vol = atr_val < vol_recent * 0.025

        # ── Scoring ──
        long_score = 0; long_detail = []
        short_score = 0; short_detail = []

        # ① H1 trend
        if h1_trend == 'UP':
            long_score += 1; long_detail.append("H1-UP")
        elif h1_trend == 'DOWN':
            short_score += 1; short_detail.append("H1-DN")

        # ② BB touch
        if close <= bb['lower']:
            long_score += 1; long_detail.append("BB-BOT")
        if close >= bb['upper']:
            short_score += 1; short_detail.append("BB-TOP")

        # ③ RSI extreme
        if rsi_val < self.rsi_oversold:
            long_score += 1; long_detail.append(f"RSI-{rsi_val:.0f}")
        if rsi_val > self.rsi_overbought:
            short_score += 1; short_detail.append(f"RSI-{rsi_val:.0f}")

        # ④ M30 RSI direction
        if m30_rsi_dir == 'up':
            long_score += 1; long_detail.append("RSI-UP")
        elif m30_rsi_dir == 'down':
            short_score += 1; short_detail.append("RSI-DN")

        # ⑤ Low volatility
        if low_vol:
            long_score += 1; short_score += 1
            long_detail.append("LOW-VOL"); short_detail.append("LOW-VOL")

        # ── Decision ──
        signal = None
        signal_str = "无信号"
        if long_score >= self.score_threshold and h1_trend == 'UP':
            signal = OrderType.BUY
            signal_str = "LONG"
        elif short_score >= self.score_threshold and h1_trend == 'DOWN':
            signal = OrderType.SELL
            signal_str = "SELL"

        # ── Logging ──
        detail_parts = []
        if long_detail: detail_parts.append("LONG: " + " ".join(long_detail))
        if short_detail: detail_parts.append("SHORT: " + " ".join(short_detail))
        logger.info(
            f"[{self.name}] 评分: {long_score}/{short_score}  {signal_str}  "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )
        logger.info(
            f"[{self.name}] Price={close:.2f} BB={bb['lower']:.2f}/{bb['upper']:.2f} "
            f"RSI={rsi_val:.1f} ATR={atr_val:.2f} H1={h1_trend}"
        )

        return signal

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """ATR-based initial stop-loss and far take-profit"""
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        dist = atr_val * 3.0
        if direction == OrderType.BUY:
            sl = round(entry_price - dist, 2)
            tp = round(entry_price + dist * 50, 2)
        else:
            sl = round(entry_price + dist, 2)
            tp = round(entry_price - dist * 50, 2)
        return sl, tp

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """ATR trailing stop + hard stop exit

        Trailing stop: drawdown/rally > ATR × p_trailing_atr → exit
        Hard stop: loss from entry > ATR × p_hard_atr → exit
        """
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

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            drawdown = td["highest"] - bid
            loss = td["entry"] - bid
            if drawdown > atr_val * self.p_trailing_atr:
                logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} drawdown={drawdown:.2f}")
                del self._trail_data[ticket]
                return True
            if loss > atr_val * self.p_hard_atr:
                logger.info(f"[{self.name}] BUY HardStop ticket={ticket} loss={loss:.2f}")
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            rally = ask - td["lowest"]
            loss = ask - td["entry"]
            if rally > atr_val * self.p_trailing_atr:
                logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} rally={rally:.2f}")
                del self._trail_data[ticket]
                return True
            if loss > atr_val * self.p_hard_atr:
                logger.info(f"[{self.name}] SELL HardStop ticket={ticket} loss={loss:.2f}")
                del self._trail_data[ticket]
                return True

        return False
