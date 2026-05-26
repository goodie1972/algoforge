"""
策略基类 - 所有策略继承此类
"""

import abc
import logging
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, Position, OrderType
from config.settings import SYMBOL, LOT_SIZE, TIMEFRAME

logger = logging.getLogger(__name__)


class BaseStrategy(abc.ABC):
    """策略基类"""

    name = "base"

    def __init__(self, bridge: MT4BridgeBase):
        self.bridge = bridge
        self.symbol = SYMBOL
        self.timeframe = TIMEFRAME
        self.candles: list[Candle] = []

    def refresh_data(self, count: int = 200):
        """刷新K线数据"""
        self.candles = self.bridge.get_candles(self.symbol, self.timeframe, count)

    def get_close_prices(self) -> list[float]:
        """获取收盘价序列"""
        return [c.close for c in self.candles]

    @abc.abstractmethod
    def generate_signal(self) -> Optional[OrderType]:
        """
        生成交易信号
        返回: OrderType.BUY / OrderType.SELL / None（不操作）
        """
        ...

    def on_tick(self) -> Optional[str]:
        """
        主循环调用：检查信号并返回操作描述
        返回: 操作描述字符串，或 None
        """
        self.refresh_data()
        if len(self.candles) < 10:
            logger.warning(f"[{self.name}] K线数据不足: {len(self.candles)}")
            return None

        signal = self.generate_signal()
        if signal:
            return f"信号: {signal.value}"
        return None

    def filter_positions(self, positions: list[Position]) -> dict:
        """统计当前品种的多空持仓"""
        longs = [p for p in positions if p.order_type in ("OP_BUY", "BUY")]
        shorts = [p for p in positions if p.order_type in ("OP_SELL", "SELL")]
        return {"longs": longs, "shorts": shorts, "total": len(positions)}
