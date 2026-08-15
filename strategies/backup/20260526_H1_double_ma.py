"""
双均线交叉策略 - XAUUSD 趋势跟踪
逻辑:
  - EMA(FAST) 上穿 EMA(SLOW) → 做多信号
  - EMA(FAST) 下穿 EMA(SLOW) → 做空信号
"""

import logging
from typing import Optional

from config.settings import MA_FAST, MA_SLOW, MA_METHOD, SYMBOL, LOT_SIZE
from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class DoubleMAStrategy(BaseStrategy):
    """双均线策略"""

    name = "double_ma"

    def __init__(self, bridge: MT4BridgeBase):
        super().__init__(bridge)
        self.ma_fast_period = MA_FAST
        self.ma_slow_period = MA_SLOW
        self.ma_method = MA_METHOD

    def _calc_ma(self, period: int, method: str = None) -> Optional[float]:
        """计算当前K线的均线值"""
        method = method or self.ma_method
        closes = self.get_close_prices()
        if len(closes) < period:
            return None

        if method == "SMA":
            return sum(closes[-period:]) / period
        elif method == "EMA":
            multiplier = 2.0 / (period + 1)
            ema = closes[0]
            for price in closes[1:]:
                ema = (price - ema) * multiplier + ema
            return ema
        return None

    def generate_signal(self) -> Optional[OrderType]:
        """
        双均线交叉信号
        比较当前K线和前一根K线的均线关系
        """
        # 需要至少比慢线多2根K线来判断交叉
        required = max(self.ma_fast_period, self.ma_slow_period) + 2
        if len(self.candles) < required:
            return None

        # 当前均线
        fast_now = self._calc_ma(self.ma_fast_period)
        slow_now = self._calc_ma(self.ma_slow_period)
        if fast_now is None or slow_now is None:
            return None

        # 前一根均线（用少一根K线的数据计算）
        old_candles = self.candles[:-1]
        old_closes = [c.close for c in old_candles]

        if len(old_closes) < self.ma_slow_period:
            return None

        if self.ma_method == "EMA":
            multiplier_fast = 2.0 / (self.ma_fast_period + 1)
            multiplier_slow = 2.0 / (self.ma_slow_period + 1)
            ema_fast = old_closes[0]
            ema_slow = old_closes[0]
            for price in old_closes[1:]:
                ema_fast = (price - ema_fast) * multiplier_fast + ema_fast
                ema_slow = (price - ema_slow) * multiplier_slow + ema_slow
            fast_prev = ema_fast
            slow_prev = ema_slow
        else:  # SMA
            fast_prev = sum(old_closes[-self.ma_fast_period:]) / self.ma_fast_period
            slow_prev = sum(old_closes[-self.ma_slow_period:]) / self.ma_slow_period

        # 金叉：快线从下方穿越到上方 → 做多
        if fast_prev <= slow_prev and fast_now > slow_now:
            logger.info(
                f"[{self.name}] 金叉! FAST={fast_now:.2f} SLOW={slow_now:.2f} "
                f"(前: FAST={fast_prev:.2f} SLOW={slow_prev:.2f})"
            )
            return OrderType.BUY

        # 死叉：快线从上方穿越到下方 → 做空
        if fast_prev >= slow_prev and fast_now < slow_now:
            logger.info(
                f"[{self.name}] 死叉! FAST={fast_now:.2f} SLOW={slow_now:.2f} "
                f"(前: FAST={fast_prev:.2f} SLOW={slow_prev:.2f})"
            )
            return OrderType.SELL

        return None
