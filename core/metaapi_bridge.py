"""
MetaApi 云端桥接实现 - 通过 REST API 连接 MT4
文档: https://metaapi.cloud/docs/client/
安装: pip install metaapi-cloud-sdk
"""

import logging
from typing import Optional

from config.settings import METAAPI_TOKEN, METAAPI_ACCOUNT_ID
from core.bridge import (
    MT4BridgeBase, Position, Candle, AccountInfo, OrderType
)

logger = logging.getLogger(__name__)


class MetaApiBridge(MT4BridgeBase):
    """通过 MetaApi 云端服务连接 MT4"""

    def __init__(self):
        self._account = None
        self._connected = False

    def connect(self) -> bool:
        try:
            import metaapi_cloud_sdk as metaapi
            api = metaapi.MetatraderApi(METAAPI_TOKEN)
            self._account = api.metatrader_account_api.create_account(METAAPI_ACCOUNT_ID)
            # 等待连接就绪
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            connected = loop.run_until_complete(self._wait_connected())
            if connected:
                self._connected = True
                logger.info("[MetaApi] 连接成功")
            return connected
        except Exception as e:
            logger.error(f"[MetaApi] 连接失败: {e}")
            return False

    async def _wait_connected(self):
        try:
            await self._account.connect()
            return True
        except Exception:
            return False

    def disconnect(self):
        if self._account:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._account.disconnect())
        self._connected = False

    def get_account_info(self) -> Optional[AccountInfo]:
        if not self._connected:
            return None
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            info = loop.run_until_complete(self._account.get_account_information())
            return AccountInfo(
                login=int(info.login),
                balance=float(info.balance),
                equity=float(info.equity),
                margin=float(info.margin),
                free_margin=float(info.free_margin),
                currency=info.currency,
                leverage=int(info.leverage),
            )
        except Exception as e:
            logger.error(f"[MetaApi] 获取账户信息失败: {e}")
            return None

    def get_positions(self, symbol: str = None) -> list[Position]:
        if not self._connected:
            return []
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            positions = loop.run_until_complete(self._account.get_positions())
            result = []
            for p in positions:
                if symbol and p.symbol != symbol:
                    continue
                result.append(Position(
                    ticket=int(p.ticket),
                    symbol=p.symbol,
                    order_type=p.type,
                    volume=float(p.volume),
                    open_price=float(p.open_price),
                    current_price=float(p.current_price),
                    stop_loss=float(p.stop_loss),
                    take_profit=float(p.take_profit),
                    profit=float(p.profit),
                    swap=float(p.swap),
                    commission=float(p.commission),
                    magic=int(getattr(p, 'magic', 0)),
                    comment=getattr(p, 'comment', ''),
                    open_time=str(getattr(p, 'open_time', '')),
                ))
            return result
        except Exception as e:
            logger.error(f"[MetaApi] 获取持仓失败: {e}")
            return []

    def get_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        if not self._connected:
            return []
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            tf_map = {"M1": "M1", "M5": "M5", "M15": "M15", "H1": "H1", "H4": "H4", "D1": "D1"}
            candles = loop.run_until_complete(
                self._account.get_candles(symbol, tf_map.get(timeframe, "H1"), count)
            )
            return [
                Candle(
                    time=str(c.get("time", "")),
                    open=float(c.get("open", 0)),
                    high=float(c.get("high", 0)),
                    low=float(c.get("low", 0)),
                    close=float(c.get("close", 0)),
                    volume=float(c.get("tickVolume", 0)),
                )
                for c in candles
            ]
        except Exception as e:
            logger.error(f"[MetaApi] 获取K线失败: {e}")
            return []

    def get_tick_price(self, symbol: str) -> tuple[float, float]:
        if not self._connected:
            return (0.0, 0.0)
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            symbol_info = loop.run_until_complete(self._account.get_symbol_info(symbol))
            return float(symbol_info.bid), float(symbol_info.ask)
        except Exception:
            return (0.0, 0.0)

    def open_order(self, symbol: str, order_type: OrderType, volume: float,
                   price: float = 0, sl: float = 0, tp: float = 0,
                   comment: str = "", magic: int = 0) -> Optional[int]:
        # MetaApi 下单实现略，需根据 MetaApi SDK 文档适配
        logger.warning("[MetaApi] open_order 需根据 MetaApi SDK 文档适配")
        return None

    def close_order(self, ticket: int, volume: float = 0) -> bool:
        logger.warning("[MetaApi] close_order 需根据 MetaApi SDK 文档适配")
        return False

    def modify_order(self, ticket: int, sl: float = 0, tp: float = 0) -> bool:
        logger.warning("[MetaApi] modify_order 需根据 MetaApi SDK 文档适配")
        return False
