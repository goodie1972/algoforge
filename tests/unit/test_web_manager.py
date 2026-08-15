"""WebSocketManager 单元测试"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from dashboard.backend.web_manager import WebSocketManager


@pytest.mark.asyncio
async def test_connect_adds_connection():
    mgr = WebSocketManager()
    ws = AsyncMock()
    await mgr.connect(ws)
    assert mgr.connection_count == 1
    ws.accept.assert_called_once()


@pytest.mark.asyncio
async def test_disconnect_removes_connection():
    mgr = WebSocketManager()
    ws = AsyncMock()
    await mgr.connect(ws)
    assert mgr.connection_count == 1
    await mgr.disconnect(ws)
    assert mgr.connection_count == 0


@pytest.mark.asyncio
async def test_broadcast_sends_to_all():
    mgr = WebSocketManager()
    ws1, ws2 = AsyncMock(), AsyncMock()
    await mgr.connect(ws1)
    await mgr.connect(ws2)
    await mgr.broadcast("prices", {"bid": 4350.0, "ask": 4350.5})
    assert ws1.send_text.called
    assert ws2.send_text.called
    sent = json.loads(ws1.send_text.call_args[0][0])
    assert sent["channel"] == "prices"
    assert sent["data"]["bid"] == 4350.0


@pytest.mark.asyncio
async def test_broadcast_removes_dead_connections():
    mgr = WebSocketManager()
    ws_good = AsyncMock()
    ws_dead = AsyncMock()
    ws_dead.send_text.side_effect = Exception("connection closed")
    await mgr.connect(ws_good)
    await mgr.connect(ws_dead)
    assert mgr.connection_count == 2
    await mgr.broadcast("positions", [])
    assert mgr.connection_count == 1  # dead removed


@pytest.mark.asyncio
async def test_broadcast_no_connections():
    mgr = WebSocketManager()
    # Should not raise
    await mgr.broadcast("account", {"balance": 5000})
    assert mgr.connection_count == 0


@pytest.mark.asyncio
async def test_disconnect_all_closes_all():
    mgr = WebSocketManager()
    ws1, ws2, ws3 = AsyncMock(), AsyncMock(), AsyncMock()
    for ws in [ws1, ws2, ws3]:
        await mgr.connect(ws)
    assert mgr.connection_count == 3
    await mgr.disconnect_all()
    assert mgr.connection_count == 0
    ws1.close.assert_called_once()
    ws2.close.assert_called_once()
    ws3.close.assert_called_once()


@pytest.mark.asyncio
async def test_disconnect_all_with_already_closed():
    mgr = WebSocketManager()
    ws = AsyncMock()
    ws.close.side_effect = Exception("already closed")
    await mgr.connect(ws)
    # Should not raise
    await mgr.disconnect_all()
    assert mgr.connection_count == 0


@pytest.mark.asyncio
async def test_disconnect_already_removed():
    mgr = WebSocketManager()
    ws = AsyncMock()
    await mgr.connect(ws)
    await mgr.disconnect(ws)
    # Double disconnect should not raise
    await mgr.disconnect(ws)
    assert mgr.connection_count == 0
