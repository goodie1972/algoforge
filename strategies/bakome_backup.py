"""
BAKOME GoldScalper — 后备策略
=============================
ICT 概念: FVG (Fair Value Gap) + Order Block + Silver Bullet 时段
- 仅在 London (8-10) 和 NY (13-15) Silver Bullet 时段交易
- FVG: 3-K线 gap 模式检测
- OB: 强势突破前的反向K线
- ATR 过滤低波动环境
"""

import logging
from datetime import datetime
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class BAKOMEBackupStrategy(BaseStrategy):
    """BAKOME GoldScalper — ICT FVG + OB + Silver Bullet"""

    name = "bakome_backup"

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

        # Exit params
        self.p_trailing_atr = 2.5
        self.p_hard_atr = 1.5

    def refresh_data(self, count: int = 200):
        self._cached_atr_key = 0
        self._cached_atr_values = None
        super().refresh_data(count)

    # ─────────────── Indicator helpers ───────────────

    def _calc_atr_values(self, period: int = 14) -> Optional[list[float]]:
        cache_key = len(self.candles)
        if self._cached_atr_key == cache_key and self._cached_atr_values is not None:
            return self._cached_atr_values

        candles = self.candles
        if len(candles) < period + 2:
            return None
        tr_values = []
        for i in range(1, len(candles)):
            h, l, pc = candles[i].high, candles[i].low, candles[i - 1].close
            tr_values.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(tr_values) < period:
            return None
        atr_list = [sum(tr_values[:period]) / period]
        for i in range(period, len(tr_values)):
            atr_list.append((atr_list[-1] * (period - 1) + tr_values[i]) / period)
        self._cached_atr_values = atr_list
        self._cached_atr_key = cache_key
        return atr_list

    def _calc_atr(self, period: int = 14) -> Optional[float]:
        vals = self._calc_atr_values(period)
        return vals[-1] if vals else None

    # ─────────────── ICT Detection ───────────────

    def _is_silver_bullet(self) -> Optional[str]:
        """Check if current candle is in a Silver Bullet session.
        Returns 'london', 'ny', or None."""
        if not self.candles:
            return None
        ts = self.candles[-1].time
        dt = datetime.strptime(ts.split()[0] if ' ' in ts else ts, '%Y.%m.%d') if '.' in ts else datetime.now()
        # Use current time for server-time check
        now = datetime.now()
        h = now.hour
        # Silver Bullet windows (server time, typically UTC+2/+3 for MT5)
        if h in [8, 9, 10]:  # London session
            return 'london'
        if h in [13, 14, 15]:  # NY session
            return 'ny'
        return None

    def _detect_fvg(self) -> Optional[OrderType]:
        """Detect Fair Value Gap (3-candle pattern)."""
        candles = self.candles
        if len(candles) < 4:
            return None
        c0 = candles[-3]  # prev.prev
        c1 = candles[-2]  # prev
        c2 = candles[-1]  # current

        # Bullish FVG: prev.prev.low > current.high (gap down then up)
        if c0.low > c2.high and c1.close < c1.open:
            return OrderType.BUY
        # Bearish FVG: prev.prev.high < current.low (gap up then down)
        if c0.high < c2.low and c1.close > c1.open:
            return OrderType.SELL
        return None

    def _detect_order_block(self) -> Optional[OrderType]:
        """Detect Order Block: strong breakout preceded by opposite candle."""
        candles = self.candles
        if len(candles) < 6:
            return None
        n = len(candles)
        c1 = candles[-1]
        c2 = candles[-2]
        c3 = candles[-3]

        avg_body = sum(abs(candles[i].close - candles[i].open) for i in range(max(0, n - 11), n)) / min(10, n)

        # BUY OB: 2 big bullish candles → find previous bearish candle
        if c1.close > c1.open and c2.close > c2.open:
            body1 = abs(c1.close - c1.open)
            body2 = abs(c2.close - c2.open)
            if body2 > avg_body * 1.2 and body1 > avg_body * 1.5:
                for j in range(n - 3, max(0, n - 7), -1):
                    if candles[j].close < candles[j].open:
                        # Price returned to OB zone
                        ob_price = candles[j].close
                        if c1.low <= ob_price * 1.003:
                            return OrderType.BUY

        # SELL OB: 2 big bearish candles → find previous bullish candle
        if c1.close < c1.open and c2.close < c2.open:
            body1 = abs(c1.close - c1.open)
            body2 = abs(c2.close - c2.open)
            if body2 > avg_body * 1.2 and body1 > avg_body * 1.5:
                for j in range(n - 3, max(0, n - 7), -1):
                    if candles[j].close > candles[j].open:
                        ob_price = candles[j].close
                        if c1.high >= ob_price * 0.997:
                            return OrderType.SELL
        return None

    # ─────────────── Signal generation ───────────────

    def generate_signal(self):
        candles = self.candles
        if len(candles) < 30:
            return (None, 0, 0, [], [], {})

        # 1. Silver Bullet session check
        session = self._is_silver_bullet()
        if not session:
            return (None, 0, 0, [], [], {})

        # 2. ATR filter
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return (None, 0, 0, [], [], {})

        # 3. Check FVG
        indicator_values = {"close": round(self.candles[-1].close, 2), "atr": round(atr_val, 2)}
        fvg_sig = self._detect_fvg()
        if fvg_sig is not None:
            logger.info(f"[{self.name}] FVG {fvg_sig.value} in {session} session, ATR={atr_val:.2f}")
            indicator_values["pattern"] = "FVG"
            indicator_values["session"] = session
            return (fvg_sig, 1, 0, [session, "FVG"], [], indicator_values)

        # 4. Check Order Block
        ob_sig = self._detect_order_block()
        if ob_sig is not None:
            logger.info(f"[{self.name}] OB {ob_sig.value} in {session} session, ATR={atr_val:.2f}")
            indicator_values["pattern"] = "OB"
            indicator_values["session"] = session
            return (ob_sig, 1, 0, [session, "OB"], [], indicator_values)

        return (None, 0, 0, [], [], indicator_values)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        dist = atr_val * 2.0
        if direction == OrderType.BUY:
            return round(entry_price - dist, 2), round(entry_price + dist * 50, 2)
        else:
            return round(entry_price + dist, 2), round(entry_price - dist * 50, 2)

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
            }

        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr")
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
