"""
MT4 桥接层 - 统一接口，支持 PyTrader（本地）和 MetaApi（云端）两种模式
"""

import abc
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from config.settings import MT4_MODE, SYMBOL, LOT_SIZE, MAGIC_NUMBER

logger = logging.getLogger(__name__)


class OrderType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"


@dataclass
class Position:
    """持仓信息"""
    ticket: int
    symbol: str
    order_type: str  # OP_BUY / OP_SELL
    volume: float
    open_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    profit: float
    swap: float
    commission: float
    magic: int
    comment: str
    open_time: str


@dataclass
class Candle:
    """K线数据"""
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class AccountInfo:
    """账户信息"""
    login: int
    balance: float
    equity: float
    margin: float
    free_margin: float
    currency: str
    leverage: int


class MT4BridgeBase(abc.ABC):
    """MT4 桥接基类"""

    @abc.abstractmethod
    def connect(self) -> bool:
        """连接到 MT4"""
        ...

    @abc.abstractmethod
    def disconnect(self):
        """断开连接"""
        ...

    @abc.abstractmethod
    def get_account_info(self) -> Optional[AccountInfo]:
        """获取账户信息"""
        ...

    @abc.abstractmethod
    def get_positions(self, symbol: str = None) -> list[Position]:
        """获取当前持仓"""
        ...

    @abc.abstractmethod
    def get_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        """获取K线数据"""
        ...

    @abc.abstractmethod
    def get_tick_price(self, symbol: str) -> tuple[float, float]:
        """获取当前买卖价 (bid, ask)"""
        ...

    @abc.abstractmethod
    def open_order(self, symbol: str, order_type: OrderType, volume: float,
                   price: float = 0, sl: float = 0, tp: float = 0,
                   comment: str = "", magic: int = 0) -> Optional[int]:
        """下单，返回 ticket"""
        ...

    @abc.abstractmethod
    def close_order(self, ticket: int, volume: float = 0) -> bool:
        """平仓"""
        ...

    @abc.abstractmethod
    def modify_order(self, ticket: int, sl: float = 0, tp: float = 0) -> bool:
        """修改止损止盈"""
        ...

    def send_heartbeat(self) -> bool:
        """发送心跳保持连接（可选实现，默认 True）"""
        return True

    def takeover_existing_positions(self, symbol: str = None, magic: int = 0) -> list[Position]:
        """接管现有持仓 - 启动时调用，可选按 magic 过滤"""
        positions = self.get_positions(symbol)
        if magic:
            positions = [p for p in positions if p.magic == magic]
        logger.info(f"[持仓接管] Magic={magic} 发现 {len(positions)} 个现有持仓:")
        for pos in positions:
            logger.info(
                f"  Ticket={pos.ticket} {pos.order_type} "
                f"{pos.volume}手 @ {pos.open_price} "
                f"盈亏={pos.profit:.2f} SL={pos.stop_loss} TP={pos.take_profit}"
            )
        return positions


def create_bridge() -> MT4BridgeBase:
    """工厂方法：根据配置创建桥接实例"""
    if MT4_MODE == "pytrader":
        from core.pytrader_bridge import PyTraderBridge
        return PyTraderBridge()
    elif MT4_MODE == "metaapi":
        from core.metaapi_bridge import MetaApiBridge
        return MetaApiBridge()
    else:
        raise ValueError(f"不支持的 MT4_MODE: {MT4_MODE}")
