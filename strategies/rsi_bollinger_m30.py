"""
M30 RSI + 布林带均值回归策略 + M15 RSI 方向过滤
继承 RSIBollingerStrategy，仅将方向过滤由 M30 改为 M15
"""

import logging
from typing import Optional

from strategies.rsi_bollinger import RSIBollingerStrategy

logger = logging.getLogger(__name__)


class RSIBollingerM30Strategy(RSIBollingerStrategy):
    """M30 RSI + M15 RSI 方向过滤"""

    name = "rsi_bollinger_m30"

    def _get_oversold(self, ema_trend: Optional[str] = None) -> int:
        """上涨趋势中放松买入阈值：30→35"""
        if ema_trend == "up":
            return 35
        return self.rsi_oversold

    def _get_overbought(self, ema_trend: Optional[str] = None) -> int:
        """下跌趋势中放松卖出阈值：70→65"""
        if ema_trend == "down":
            return 65
        return self.rsi_overbought

    def _calc_m30_rsi_direction(self) -> Optional[str]:
        """覆盖父类：取最近 3 根 M15 RSI 判断方向（父类用 M30）"""
        raw = self.bridge.get_candles(self.symbol, "M15", self.rsi_period + 10)
        if not raw or len(raw) < self.rsi_period + 4:
            return None
        candles = list(reversed(raw))
        closes = [c.close for c in candles]

        rsi_oldest = self._calc_m30_rsi(closes[:-2])
        rsi_mid = self._calc_m30_rsi(closes[:-1])
        rsi_newest = self._calc_m30_rsi(closes)

        if rsi_oldest is None or rsi_mid is None or rsi_newest is None:
            return None

        if rsi_oldest < rsi_mid < rsi_newest:
            return "up"
        elif rsi_oldest > rsi_mid > rsi_newest:
            return "down"
        return "flat"

    def _calc_m30_rsi_exit(self) -> Optional[str]:
        """覆盖父类：取最近 2 根 M15 RSI 判断出场方向（父类用 M30）"""
        raw = self.bridge.get_candles(self.symbol, "M15", self.rsi_period + 10)
        if not raw or len(raw) < self.rsi_period + 3:
            return None
        candles = list(reversed(raw))
        closes = [c.close for c in candles]

        rsi_prev = self._calc_m30_rsi(closes[:-1])
        rsi_curr = self._calc_m30_rsi(closes)

        if rsi_prev is None or rsi_curr is None:
            return None

        if rsi_prev < rsi_curr:
            return "up"
        elif rsi_prev > rsi_curr:
            return "down"
        return "flat"
