"""WebSocket 广播背压控制模块。

生产者-消费者模式的广播中心：每个频道维护一组有界 asyncio.Queue，
队列满时丢弃最旧消息以保实时性，支持多消费者订阅/退订与断开客户端清理。

设计要点
--------
- 每个频道（prices / positions / account / logs / status）一个订阅者列表，
  每个订阅者持有独立的有界队列（maxsize=50），互不阻塞。
- publish 非阻塞写入：队列满时先 get_nowait 丢弃最旧消息再 put_nowait，
  保证生产者永不被慢消费者拖住（背压降级为“丢旧保新”）。
- subscribe 返回 Queue 供消费者读取；unsubscribe 清理断开客户端。
- publish_sync 提供给非 async 上下文（如同步回调线程）调用，
  依赖 asyncio.Queue 的线程安全 get_nowait/put_nowait。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

logger = logging.getLogger("dashboard.broadcast")

# 各频道默认队列容量：满即丢旧保新
DEFAULT_QUEUE_MAXSIZE: Final[int] = 50

# 约定的频道名集合，便于校验与自省
KNOWN_CHANNELS: Final[tuple[str, ...]] = ("prices", "positions", "account", "logs", "status")


class BroadcastHub:
    """生产者-消费者模式广播中心，队列满时丢弃旧消息保实时性。

    用法
    ----
    >>> hub = BroadcastHub()
    >>> q = await hub.subscribe("prices")          # WebSocket 处理协程
    >>> while True:
    ...     data = await q.get()
    ...     await ws.send_json(data)
    ...
    >>> # 生产端（任意协程）
    >>> await hub.publish("prices", {"price": 2650.1})
    >>> # 或同步上下文
    >>> hub.publish_sync("prices", {"price": 2650.1})
    """

    def __init__(self, queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE) -> None:
        self._channels: dict[str, list[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self._queue_maxsize = queue_maxsize
        # 统计：各频道被丢弃的消息数（仅统计因队列满而丢弃的旧消息）
        self._dropped: dict[str, int] = {}

    # ------------------------------------------------------------------ #
    # 订阅 / 退订
    # ------------------------------------------------------------------ #
    async def subscribe(self, channel: str) -> asyncio.Queue:
        """订阅频道，返回一个有界 Queue 供消费者读取。

        每次调用创建独立队列，同一频道可被多个消费者订阅。
        """
        async with self._lock:
            return self._subscribe_locked(channel)

    def subscribe_sync(self, channel: str) -> asyncio.Queue:
        """同步订阅（需在事件循环线程内调用，如 WebSocket 连接建立回调）。

        与 subscribe 等价，但不 await 锁——适用于确信无并发竞争的快速路径。
        若存在跨协程并发订阅/退订，请改用 async subscribe。
        """
        return self._subscribe_locked(channel)

    def _subscribe_locked(self, channel: str) -> asyncio.Queue:
        if channel not in self._channels:
            self._channels[channel] = []
            self._dropped.setdefault(channel, 0)
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._channels[channel].append(q)
        logger.info(
            "[Broadcast] %s subscriber added, total=%d",
            channel,
            len(self._channels[channel]),
        )
        return q

    async def unsubscribe(self, channel: str, q: asyncio.Queue) -> None:
        """退订并清理指定队列（客户端断开时调用）。

        队列中尚未消费的消息随之丢弃；频道无订阅者时移除频道键。
        """
        async with self._lock:
            self._unsubscribe_locked(channel, q)

    def unsubscribe_sync(self, channel: str, q: asyncio.Queue) -> None:
        """同步退订（需在事件循环线程内调用）。"""
        self._unsubscribe_locked(channel, q)

    def _unsubscribe_locked(self, channel: str, q: asyncio.Queue) -> None:
        subs = self._channels.get(channel)
        if not subs or q not in subs:
            return
        subs.remove(q)
        logger.info(
            "[Broadcast] %s subscriber removed, remaining=%d",
            channel,
            len(subs),
        )
        if not subs:
            del self._channels[channel]

    # ------------------------------------------------------------------ #
    # 发布
    # ------------------------------------------------------------------ #
    async def publish(self, channel: str, data: Any) -> None:
        """异步发布：向频道所有订阅者队列非阻塞写入。

        队列满时丢弃最旧消息，保证生产者不被慢消费者拖住。
        无订阅者时静默返回。
        """
        subs = self._channels.get(channel, [])
        if not subs:
            return
        # 复制引用列表，避免遍历期间被 unsubscribe 修改
        for q in list(subs):
            self._put_drop_oldest(channel, q, data)

    def publish_sync(self, channel: str, data: Any) -> None:
        """同步发布（用于从非 async 上下文调用，如同步回调线程）。

        依赖 asyncio.Queue.get_nowait / put_nowait 的线程安全性。
        """
        subs = self._channels.get(channel, [])
        if not subs:
            return
        for q in list(subs):
            self._put_drop_oldest(channel, q, data)

    def _put_drop_oldest(self, channel: str, q: asyncio.Queue, data: Any) -> None:
        """向单条队列写入：满则丢弃最旧消息，再尝试写入。

        丢弃与写入均为非阻塞，确保调用方永不挂起。
        """
        if q.full():
            try:
                q.get_nowait()
                self._dropped[channel] = self._dropped.get(channel, 0) + 1
            except asyncio.QueueEmpty:
                # 极端竞态：full() 与 get_nowait() 之间被消费空
                pass
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            # 极端竞态：丢弃后仍被并发填满，放弃本条消息
            self._dropped[channel] = self._dropped.get(channel, 0) + 1

    # ------------------------------------------------------------------ #
    # 自省 / 维护
    # ------------------------------------------------------------------ #
    def subscriber_count(self, channel: str) -> int:
        """返回某频道当前订阅者数量。"""
        return len(self._channels.get(channel, []))

    def channels(self) -> list[str]:
        """返回当前有订阅者的频道列表。"""
        return list(self._channels.keys())

    def dropped_count(self, channel: str) -> int:
        """返回某频道累计因队列满而丢弃的消息数（诊断用）。"""
        return self._dropped.get(channel, 0)

    def stats(self) -> dict[str, dict[str, int]]:
        """返回各频道的订阅者数与丢弃数快照（诊断/监控用）。"""
        return {
            ch: {
                "subscribers": len(subs),
                "dropped": self._dropped.get(ch, 0),
            }
            for ch, subs in self._channels.items()
        }

    async def close(self) -> None:
        """清理所有频道与队列（关闭广播中心时调用）。

        清空各队列中未消费消息并移除所有订阅者引用，帮助消费者
        协程及时从 get() 解阻塞（若需要彻底唤醒，可额外向队列 put 哨兵）。
        """
        async with self._lock:
            for channel, subs in list(self._channels.items()):
                for q in subs:
                    drained = 0
                    while not q.empty():
                        try:
                            q.get_nowait()
                            drained += 1
                        except asyncio.QueueEmpty:
                            break
                    if drained:
                        logger.debug(
                            "[Broadcast] %s drained %d pending messages",
                            channel,
                            drained,
                        )
            self._channels.clear()
            self._dropped.clear()
            logger.info("[Broadcast] hub closed, all channels cleared")


__all__ = ["BroadcastHub", "KNOWN_CHANNELS", "DEFAULT_QUEUE_MAXSIZE"]
