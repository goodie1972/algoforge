"""
broadcast_hub 单元测试 — 验证背压控制、订阅/退订、丢弃机制
"""
import asyncio
import pytest
from dashboard.backend.broadcast_hub import BroadcastHub


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    """基本订阅+发布"""
    hub = BroadcastHub()
    q = await hub.subscribe("prices")
    await hub.publish("prices", {"bid": 4389.0, "ask": 4389.5})
    data = await asyncio.wait_for(q.get(), timeout=1.0)
    assert data["bid"] == 4389.0
    assert data["ask"] == 4389.5
    assert hub.subscriber_count("prices") == 1


@pytest.mark.asyncio
async def test_unsubscribe():
    """退订后不再收到消息"""
    hub = BroadcastHub()
    q = await hub.subscribe("prices")
    await hub.unsubscribe("prices", q)
    await hub.publish("prices", {"bid": 100})
    assert q.empty()
    assert hub.subscriber_count("prices") == 0


@pytest.mark.asyncio
async def test_backpressure_drop_oldest():
    """队列满时丢弃最旧消息"""
    hub = BroadcastHub()
    # 用小队列测试
    import asyncio as _aio
    q = await hub.subscribe("test_drop")
    # 填满队列（maxsize=50）
    for i in range(50):
        await hub.publish("test_drop", f"msg_{i}")
    assert q.full()
    # 再发一条 → 应丢弃 msg_0
    await hub.publish("test_drop", "msg_50")
    first = await asyncio.wait_for(q.get(), timeout=1.0)
    assert first != "msg_0"  # msg_0 被丢弃
    assert first == "msg_1"


@pytest.mark.asyncio
async def test_multiple_subscribers():
    """多订阅者各自独立接收"""
    hub = BroadcastHub()
    q1 = await hub.subscribe("status")
    q2 = await hub.subscribe("status")
    await hub.publish("status", {"running": True})
    d1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    d2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert d1 == {"running": True}
    assert d2 == {"running": True}
    assert hub.subscriber_count("status") == 2


@pytest.mark.asyncio
async def test_publish_no_subscribers():
    """无订阅者时发布不报错"""
    hub = BroadcastHub()
    await hub.publish("nonexistent", "data")  # 不应抛异常


@pytest.mark.asyncio
async def test_publish_sync():
    """同步发布版本"""
    hub = BroadcastHub()
    q = await hub.subscribe("logs")
    hub.publish_sync("logs", {"level": "INFO"})
    data = await asyncio.wait_for(q.get(), timeout=1.0)
    assert data["level"] == "INFO"


@pytest.mark.asyncio
async def test_stats():
    """统计信息"""
    hub = BroadcastHub()
    await hub.subscribe("prices")
    await hub.subscribe("prices")
    stats = hub.stats()
    assert "prices" in stats
    assert stats["prices"]["subscribers"] == 2
