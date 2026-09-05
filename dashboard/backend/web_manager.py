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
        """向所有连接的客户端广播消息。

        修复「Dashboard 假死」：原实现在持锁状态下 `await ws.send_text()` 且无超时，
        一旦某个被浏览器节流/网络抖动的客户端发送缓冲被占满，该 await 会阻塞整个
        asyncio 事件循环，导致所有 REST 请求（切导航拉数据）与所有 WS 推送卡死
        （K 线冻结、导航无反应），客户端恢复后又一次性涌来积压消息（图表漂移/跳动）。

        现改为：快照连接列表后立即释放全局锁，再用并发任务按连接分别发送，
        单个慢客户端 1s 超时即放弃并断开，绝不拖累事件循环与其他客户端。
        """
        message = json.dumps({"channel": channel, "data": data}, default=str)
        async with self._lock:
            targets = list(self._connections)
        if not targets:
            return

        dead: set = set()

        async def _safe_send(ws: WebSocket) -> None:
            try:
                # 1s 超时：客户端发送缓冲满（被节流/弱网）即放弃并标记断开，
                # 避免阻塞事件循环。wait_for 超时抛 TimeoutError → 进入 except。
                await asyncio.wait_for(ws.send_text(message), timeout=1.0)
            except Exception:
                dead.add(ws)

        # 并发发送：某连接阻塞时事件循环可切换去服务 REST/其他 WS，不再全局卡死
        await asyncio.gather(*[_safe_send(ws) for ws in targets], return_exceptions=True)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def disconnect_all(self):
        """关闭所有 WebSocket 连接（用于 shutdown）"""
        async with self._lock:
            for ws in list(self._connections):
                try:
                    await ws.close()
                except Exception:
                    pass
            self._connections.clear()
