"""
WebSocket 连接管理器 - 频道广播机制
"""

import asyncio
import json
import logging
from typing import Any, Set

from fastapi import WebSocket

logger = logging.getLogger("web_manager")


class WebSocketManager:
    """管理 WebSocket 连接和频道订阅"""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            self._connections.discard(ws)

    async def broadcast(self, channel: str, data: Any):
        """向所有连接的客户端广播消息"""
        message = json.dumps({"channel": channel, "data": data}, default=str)
        async with self._lock:
            dead = set()
            for ws in self._connections:
                try:
                    await ws.send_text(message)
                except Exception:
                    dead.add(ws)
            for ws in dead:
                self._connections.discard(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)
