"""
ATR 突破策略 - XAUUSD 波段跟踪
逻辑:
  - N 日高低点突破入场
  - ATR 动态止损（N 倍 ATR）
  - 趋势跟踪，适合黄金大波段
"""

import logging
from typing import Optional

from config.settings import SYMBOL, LOT_SIZE
from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class ATRBreakoutStrategy(BaseStrategy):
    """ATR 突破策略"""

    name = "atr_breakout"

    def __init__(self, bridge: MT4BridgeBase):
        super().__init__(bridge)
        self.breakout_period = 20    # 突破周期（N日高低点）
        self.atr_period = 14         # ATR 周期
        self.atr_multiplier = 2.0    # ATR 止损倍数

    def _calc_atr(self, period: int = None) -> Optional[float]:
        """计算当前 ATR"""
        period = period or self.atr_period
        if len(self.candles) < period + 1:
            return None

        trs = []
        for i in range(len(self.candles) - period, len(self.candles)):
            if i == 0:
                continue
            curr = self.candles[i]
            prev = self.candles[i - 1]
            high = float(curr.high)
            low = float(curr.low)
            prev_close = float(prev.close)
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)

        if not trs:
            return None
        return sum(trs) / len(trs)

    def _get_channel(self) -> tuple[Optional[float], Optional[float]]:
        """获取突破通道（N周期最高/最低价）"""
        if len(self.candles) < self.breakout_period + 1:
            return None, None

        # 前 N 根K线（不含当前未完成的那根）
        lookback = self.candles[-self.breakout_period - 1:-1]
        highest = max(float(c.high) for c in lookback)
        lowest = min(float(c.low) for c in lookback)
        return highest, lowest

    def generate_signal(self) -> Optional[OrderType]:
        """突破信号"""
        if len(self.candles) < self.breakout_period + 5:
            return None

        current = self.candles[-1]
        current_close = float(current.close)
        highest, lowest = self._get_channel()

        if highest is None or lowest is None:
            return None

        atr = self._calc_atr()

        # 向上突破最高价 → 做多
        if current_close > highest:
            logger.info(
                f"[{self.name}] 向上突破! 现价={current_close:.2f} "
                f"通道高={highest:.2f} ATR={atr:.2f}"
            )
            return OrderType.BUY

        # 向下突破最低价 → 做空
        if current_close < lowest:
            logger.info(
                f"[{self.name}] 向下突破! 现价={current_close:.2f} "
                f"通道低={lowest:.2f} ATR={atr:.2f}"
            )
            return OrderType.SELL

        return None

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """动态止损止盈"""
        atr = self._calc_atr()
        if atr is None:
            atr = entry_price * 0.005  # fallback: 0.5%

        sl_distance = atr * self.atr_multiplier
        tp_distance = sl_distance * 2  # 盈亏比 2:1

        if direction == OrderType.BUY:
            sl = entry_price - sl_distance
            tp = entry_price + tp_distance
        else:
            sl = entry_price + sl_distance
            tp = entry_price - tp_distance

        return round(sl, 2), round(tp, 2)
