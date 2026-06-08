"""
V6 Hybrid v6 — 减逆势版本
==========================================================
基于 V6v1 修改：去除 BB/KC 碰触信号（均值回归噪音），保留 KDJ/RSI/背离/低波动/M30方向
回测: 994 笔, -$133.30, 48.1% WR（较 V6v1 改善 80%）
==========================================================
- 入场: 6 因子评分系统 ≥3 分触发（不含 BB/KC touch）
- 双向交易 (Long / Short)
- 出场: ATR 动态追踪止损 (Trailing Stop + Hard Stop)
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class V6HybridStrategy(BaseStrategy):
    """V6 Hybrid — 多因子评分 + ATR 动态止损 + 双向交易 + M30 方向过滤"""

    name = "H1_v6_hybrid"

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._prev_k: Optional[float] = None
        self._prev_d: Optional[float] = None
        self._trail_data: dict[int, dict] = {}
        self._m30_candles: list[Candle] = []
        self._m30_closes: list[float] = []

        # V6 scoring params (optimized via parameter scan)
        self.oversold = 30
        self.overbought = 65
        self.div_lookback = 10
        self.p_trailing_atr = 4.0
        self.p_hard_atr = 2.0

        # Indicator calculation params
        self.bb_period = 20
        self.bb_std = 2.5
        self.stoch_k = 9
        self.stoch_slowing = 3
        self.stoch_d = 3
        self.atr_period = 20
        self.atr_sma_period = 10
        self.kc_mult = 2.5

        # ATR cache
        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

    def refresh_data(self, count: int = 350):
        """Override to request enough candles for V6 (needs >=250) and reset ATR cache"""
        self._cached_atr_key = 0
        self._cached_atr_values = None
        super().refresh_data(count)
        self._load_m30_data()

    def _load_m30_data(self):
        """加载 M30 K 线数据从本地 SQLite（由引擎每 300s 同步）"""
        try:
            from data.database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
            ).fetchall()
            conn.close()
            self._m30_candles = [
                Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                for r in rows
            ]
            self._m30_closes = [c.close for c in self._m30_candles]
        except Exception as e:
            logger.warning(f"[{self.name}] M30 data load failed: {e}")
            self._m30_candles = []
            self._m30_closes = []

    def _calc_m30_trend(self) -> str:
        """判断 M30 趋势方向: 'UP' / 'DOWN' / 'NEUTRAL'

        使用 EMA20 斜率 + 价格 vs SMA50 组合判断。
        需要至少 60 根 M30 K 线（约 30小时数据）才能计算。
        """
        closes = self._m30_closes
        if len(closes) < 60:
            return 'NEUTRAL'

        # EMA20 series
        k = 2.0 / 21
        ema = closes[0]
        ema_values = [ema]
        for p in closes[1:]:
            ema = (p - ema) * k + ema
            ema_values.append(ema)

        if len(ema_values) < 6:
            return 'NEUTRAL'

        ema_slope = ema_values[-1] - ema_values[-6]  # slope over last 5 M30 bars = 2.5h

        # SMA50
        if len(closes) < 50:
            return 'NEUTRAL'
        sma50 = sum(closes[-50:]) / 50

        current_price = closes[-1]

        # Strong trend: EMA slope and price agree
        if ema_slope > 0 and current_price > sma50:
            return 'UP'
        if ema_slope < 0 and current_price < sma50:
            return 'DOWN'
        # Weak trend: only slope
        if ema_slope > 0:
            return 'UP'
        if ema_slope < 0:
            return 'DOWN'

        return 'NEUTRAL'

    # ──────────────────────────────────────────────
    # Indicator helpers
    # ──────────────────────────────────────────────

    def _calc_sma(self, period: int) -> Optional[float]:
        """Simple Moving Average of close prices"""
        closes = self.get_close_prices()
        if len(closes) < period:
            return None
        return sum(closes[-period:]) / period

    def _calc_ema(self, period: int, shift: int = 0) -> Optional[float]:
        """Exponential Moving Average of close prices"""
        closes = self.get_close_prices()
        needed = period + shift
        if len(closes) < needed:
            return None
        if shift:
            closes = closes[:-shift]
        k = 2.0 / (period + 1)
        ema = closes[0]
        for p in closes[1:]:
            ema = (p - ema) * k + ema
        return ema

    def _calc_stoch(self) -> Optional[dict]:
        """Stochastic: K/D values

        Returns dict with prev_k, curr_k, prev_d, curr_d, or None if insufficient data.
        """
        candles = self.candles
        n = len(candles)
        min_needed = self.stoch_k + self.stoch_slowing + self.stoch_d + 1
        if n < min_needed:
            return None

        # %K_raw[i] = (close[i] - lowest_low) / (highest_high - lowest_low) * 100
        raw_k = []
        for i in range(self.stoch_k - 1, n):
            window = candles[i - self.stoch_k + 1: i + 1]
            highest = max(c.high for c in window)
            lowest = min(c.low for c in window)
            close = window[-1].close
            if highest == lowest:
                raw_k.append(50.0)
            else:
                raw_k.append((close - lowest) / (highest - lowest) * 100)

        if len(raw_k) < self.stoch_slowing + self.stoch_d + 1:
            return None

        # K = SMA(%K_raw, stoch_slowing)
        smooth_k = []
        for i in range(self.stoch_slowing - 1, len(raw_k)):
            val = sum(raw_k[i - self.stoch_slowing + 1: i + 1]) / self.stoch_slowing
            smooth_k.append(val)

        if len(smooth_k) < self.stoch_d + 1:
            return None

        curr_k = smooth_k[-1]
        prev_k = smooth_k[-2]

        # D = SMA(K, stoch_d)
        curr_d = sum(smooth_k[-self.stoch_d:]) / self.stoch_d
        prev_d = sum(smooth_k[-(self.stoch_d + 1):-1]) / self.stoch_d

        return {"prev_k": prev_k, "curr_k": curr_k, "prev_d": prev_d, "curr_d": curr_d}

    def _calc_rsi(self, period: int) -> Optional[float]:
        """Wilder's RSI"""
        closes = self.get_close_prices()
        if len(closes) < period + 1:
            return None

        # Initial SMA
        gains, losses = [], []
        for i in range(1, period + 1):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        # Wilder's smoothing for remaining values
        for i in range(period + 1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gain = max(diff, 0)
            loss = max(-diff, 0)
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calc_macd(self) -> Optional[dict]:
        """MACD(12,26,9) with histogram

        Returns dict with macd, signal, histogram, hist_increasing, hist_values.
        hist_values is a list aligned with close prices.
        """
        closes = self.get_close_prices()
        if len(closes) < 35:
            return None

        k12 = 2.0 / 13
        k26 = 2.0 / 27
        k9 = 2.0 / 10

        ema12 = closes[0]
        ema26 = closes[0]
        macd_line = []

        for price in closes:
            ema12 = (price - ema12) * k12 + ema12
            ema26 = (price - ema26) * k26 + ema26
            macd_line.append(ema12 - ema26)

        # Signal line = EMA9 of MACD
        signal_line = [macd_line[0]]
        for v in macd_line[1:]:
            signal_line.append((v - signal_line[-1]) * k9 + signal_line[-1])

        # Histogram = MACD - Signal
        hist_values = [macd_line[i] - signal_line[i] for i in range(len(macd_line))]

        return {
            "macd": round(macd_line[-1], 4),
            "signal": round(signal_line[-1], 4),
            "histogram": round(hist_values[-1], 4),
            "hist_increasing": hist_values[-1] > hist_values[-2],
            "hist_values": hist_values,
        }

    def _calc_bb_levels(self) -> Optional[dict]:
        """Bollinger Bands: SMA20 + std × bb_std upper/lower"""
        closes = self.get_close_prices()
        if len(closes) < self.bb_period:
            return None
        recent = closes[-self.bb_period:]
        sma = sum(recent) / self.bb_period
        variance = sum((c - sma) ** 2 for c in recent) / self.bb_period
        std = math.sqrt(variance)
        return {
            "sma": sma,
            "upper": sma + self.bb_std * std,
            "lower": sma - self.bb_std * std,
        }

    def _calc_atr_values(self, period: int = 20) -> Optional[list[float]]:
        """Return list of ATR values (oldest → newest) using Wilder's smoothing

        TR = max(high - low, abs(high - prev_close), abs(low - prev_close))
        First ATR = SMA of first 'period' TRs
        Subsequent ATR_t = (ATR_{t-1} × (period-1) + TR_t) / period

        Results are cached based on candle count to avoid 3× recalculation per tick.
        """
        # Cache based on data length
        cache_key = len(self.candles)
        if self._cached_atr_key == cache_key and self._cached_atr_values is not None:
            return self._cached_atr_values

        candles = self.candles
        if len(candles) < period + 2:
            return None

        tr_values = []
        for i in range(1, len(candles)):
            h = candles[i].high
            l_ = candles[i].low
            pc = candles[i - 1].close
            tr = max(h - l_, abs(h - pc), abs(l_ - pc))
            tr_values.append(tr)

        if len(tr_values) < period:
            return None

        # First ATR = SMA of first 'period' TRs
        atr_list = [sum(tr_values[:period]) / period]
        # Wilder's smoothing for remaining values
        for i in range(period, len(tr_values)):
            atr_list.append((atr_list[-1] * (period - 1) + tr_values[i]) / period)

        self._cached_atr_values = atr_list
        self._cached_atr_key = cache_key
        return atr_list

    def _calc_atr(self, period: int = 20) -> Optional[float]:
        """Latest ATR value"""
        vals = self._calc_atr_values(period)
        if vals is None or len(vals) == 0:
            return None
        return vals[-1]

    def _calc_atr_sma(self, period: int = 10) -> Optional[float]:
        """SMA of ATR values over `period`"""
        vals = self._calc_atr_values()
        if vals is None or len(vals) < period:
            return None
        return sum(vals[-period:]) / period

    def _calc_keltner(self) -> Optional[dict]:
        """Keltner Channel: EMA20 ± ATR × kc_mult"""
        ema20 = self._calc_ema(20)
        atr = self._calc_atr()
        if ema20 is None or atr is None:
            return None
        return {
            "ema": ema20,
            "upper": ema20 + atr * self.kc_mult,
            "lower": ema20 - atr * self.kc_mult,
        }

    # ──────────────────────────────────────────────
    # MACD Divergence detection
    # ──────────────────────────────────────────────

    def _check_bottom_divergence(self, lookback: int = 15) -> bool:
        """MACD bottom divergence: price lower but MACD histogram higher at local minima"""
        macd = self._calc_macd()
        if macd is None:
            return False
        hist = macd.get("hist_values")
        if hist is None or len(hist) < lookback * 2 + 3:
            return False

        candles = self.candles
        n = len(candles)
        start = n - lookback * 2
        if start < 1:
            return False

        lows = []
        for i in range(start + 1, n - 1):
            if candles[i].low < candles[i - 1].low and candles[i].low < candles[i + 1].low:
                lows.append((i, candles[i].low, hist[i]))

        if len(lows) < 2:
            return False
        p1, m1 = lows[-2][1], lows[-2][2]
        p2, m2 = lows[-1][1], lows[-1][2]
        return p2 < p1 and m2 > m1

    def _check_top_divergence(self, lookback: int = 15) -> bool:
        """MACD top divergence: price higher but MACD histogram lower at local maxima"""
        macd = self._calc_macd()
        if macd is None:
            return False
        hist = macd.get("hist_values")
        if hist is None or len(hist) < lookback * 2 + 3:
            return False

        candles = self.candles
        n = len(candles)
        start = n - lookback * 2
        if start < 1:
            return False

        highs = []
        for i in range(start + 1, n - 1):
            if candles[i].high > candles[i - 1].high and candles[i].high > candles[i + 1].high:
                highs.append((i, candles[i].high, hist[i]))

        if len(highs) < 2:
            return False
        p1, m1 = highs[-2][1], highs[-2][2]
        p2, m2 = highs[-1][1], highs[-1][2]
        return p2 > p1 and m2 < m1

    # ──────────────────────────────────────────────
    # Signal generation (V6 Scoring System)
    # ──────────────────────────────────────────────

    def generate_signal(self) -> Optional[OrderType]:
        candles = self.candles
        if len(candles) < 250:
            logger.debug(f"[{self.name}] 数据不足: {len(candles)} < 250")
            return None

        closes = self.get_close_prices()
        close = closes[-1]
        low = candles[-1].low
        high = candles[-1].high

        # ── Indicators ──

        sma200 = self._calc_sma(200)
        if sma200 is None:
            return None

        stoch = self._calc_stoch()
        if stoch is None:
            return None
        k_curr = stoch["curr_k"]
        k_prev = stoch["prev_k"]
        d_curr = stoch["curr_d"]

        rsi = self._calc_rsi(14)
        if rsi is None:
            return None

        bottom_div = self._check_bottom_divergence(self.div_lookback)
        top_div = self._check_top_divergence(self.div_lookback)

        atr_val = self._calc_atr()
        atr_sma_val = self._calc_atr_sma()
        if atr_val is None or atr_sma_val is None:
            return None

        # ── Long scoring ──
        long_score = 0
        long_detail = []

        # ① SMA200 trend
        if close > sma200:
            long_score += 1
            long_detail.append("TREND+")

        # ② KDJ oversold
        if k_curr < self.oversold or k_prev < self.oversold:
            long_score += 1
            long_detail.append("KDJ-OS")

        # ③ MACD bottom divergence
        if bottom_div:
            long_score += 2
            long_detail.append("DIVERGENCE")

        # ④ RSI oversold
        if rsi < 30:
            long_score += 1
            long_detail.append("RSI-OS")

        # ⑤ Low volatility
        if atr_val < atr_sma_val * 1.2:
            long_score += 1
            long_detail.append("LOW-VOL")

        # ⑥ M30 trend direction alignment
        m30_dir = self._calc_m30_trend()
        m30_up = m30_dir == 'UP'
        m30_down = m30_dir == 'DOWN'
        if m30_up:
            long_score += 1
            long_detail.append("M30-UP")
        elif m30_down:
            long_score -= 1
            long_detail.append("M30-DN↓")

        # ── Short scoring (only when below SMA200) ──
        short_score = 0
        short_detail = []

        if close <= sma200:
            if k_curr > self.overbought:
                short_score += 1
                short_detail.append("KDJ-OB")


            if top_div:
                short_score += 2
                short_detail.append("TOP-DIV")

            if rsi > 70:
                short_score += 1
                short_detail.append("RSI-OB")

            # M30 direction for short
            if m30_down:
                short_score += 1
                short_detail.append("M30-DN")
            elif m30_up:
                short_score -= 1
                short_detail.append("M30-UP↑")

        # ── Decision ──
        signal = None
        signal_str = "无信号"
        if long_score >= 3:
            signal = OrderType.BUY
            signal_str = "LONG"
        elif short_score >= 3:
            signal = OrderType.SELL
            signal_str = "SELL"

        # ── Logging ──
        detail_parts = []
        if long_detail:
            detail_parts.append("LONG: " + " ".join(long_detail))
        if short_detail:
            detail_parts.append("SHORT: " + " ".join(short_detail))

        logger.info(
            f"[{self.name}] 评分: {long_score}/{short_score}  {signal_str}  "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )
        logger.info(
            f"[{self.name}] Price={close:.2f} SMA200={sma200:.2f} "
            f"K={k_curr:.1f} D={d_curr:.1f} RSI={rsi:.2f} ATR={atr_val:.2f}"
        )

        return signal

    # ──────────────────────────────────────────────
    # SL/TP and Exit
    # ──────────────────────────────────────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """ATR-based initial stop-loss and far take-profit

        Initial SL = ATR × 3.0
        TP set at 50× SL distance — trailing stop handled by check_ema20_exit.
        """
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
        """ATR trailing stop + hard stop exit (name inherited from base strategy interface)

        Trailing stop: drawdown/rally > ATR × self.p_trailing_atr → exit
        Hard stop: loss from entry > ATR × self.p_hard_atr → exit
        """
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        # Initialize tracking for this ticket
        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
            }

        td = self._trail_data[ticket]
        atr_val = self._calc_atr_sma()  # Use double-smoothed ATR for exit thresholds
        if atr_val is None or atr_val <= 0:
            return False

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            drawdown = td["highest"] - bid
            loss = td["entry"] - bid
            if drawdown > atr_val * self.p_trailing_atr:
                logger.info(
                    f"[{self.name}] BUY TrailStop ticket={ticket} "
                    f"drawdown={drawdown:.2f} > {atr_val * self.p_trailing_atr:.2f}"
                )
                del self._trail_data[ticket]
                return True
            if loss > atr_val * self.p_hard_atr:
                logger.info(
                    f"[{self.name}] BUY HardStop ticket={ticket} "
                    f"loss={loss:.2f} > {atr_val * self.p_hard_atr:.2f}"
                )
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            rally = ask - td["lowest"]
            loss = ask - td["entry"]
            if rally > atr_val * self.p_trailing_atr:
                logger.info(
                    f"[{self.name}] SELL TrailStop ticket={ticket} "
                    f"rally={rally:.2f} > {atr_val * self.p_trailing_atr:.2f}"
                )
                del self._trail_data[ticket]
                return True
            if loss > atr_val * self.p_hard_atr:
                logger.info(
                    f"[{self.name}] SELL HardStop ticket={ticket} "
                    f"loss={loss:.2f} > {atr_val * self.p_hard_atr:.2f}"
                )
                del self._trail_data[ticket]
                return True

        return False
