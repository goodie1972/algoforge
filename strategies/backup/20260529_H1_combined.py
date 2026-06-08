"""
组合策略：双均线 + ATR 双确认
- 两种策略同时跑 M30 周期
- 只有同向信号都出现时才开仓（多空对称）
- SL/TP 使用 ATR 动态止损
"""

import logging
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy
from strategies.double_ma import DoubleMAStrategy
from strategies.atr_breakout import ATRBreakoutStrategy

logger = logging.getLogger(__name__)


class CombinedStrategy(BaseStrategy):
    """双均线 + ATR 组合策略"""

    name = "combined"

    def __init__(self, bridge: MT4BridgeBase):
        super().__init__(bridge)
        self.ma_strategy = DoubleMAStrategy(bridge)
        self.atr_strategy = ATRBreakoutStrategy(bridge)
        # 暴露子策略属性，供引擎启动日志使用
        self.ma_fast_period = self.ma_strategy.ma_fast_period
        self.ma_slow_period = self.ma_strategy.ma_slow_period
        self.breakout_period = self.atr_strategy.breakout_period
        self.atr_period = self.atr_strategy.atr_period

    def refresh_data(self, count: int = 200):
        """一次刷新，两个子策略共享数据"""
        super().refresh_data(count)
        self.ma_strategy.candles = self.candles
        self.atr_strategy.candles = self.candles

    def generate_signal(self) -> Optional[OrderType]:
        """
        双确认信号：
        - 双均线 AND ATR 同时看多 → BUY
        - 双均线 AND ATR 同时看空 → SELL
        - 不一致 → None（不操作）
        """
        ma_signal = self.ma_strategy.generate_signal()
        atr_signal = self.atr_strategy.generate_signal()

        if ma_signal is None or atr_signal is None:
            return None

        if ma_signal == atr_signal:
            logger.info(
                f"[{self.name}] 双确认一致: "
                f"双均线={ma_signal} ATR={atr_signal}"
            )
            return ma_signal

        logger.info(
            f"[{self.name}] 双确认不一致: "
            f"双均线={ma_signal} ATR={atr_signal} — 跳过"
        )
        return None

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """委托给 ATR 策略计算动态止损止盈"""
        return self.atr_strategy.get_dynamic_sl_tp(direction, entry_price)
