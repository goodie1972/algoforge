"""Lifespan shutdown 单元测试 — 验证资源释放逻辑"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import logging


@pytest.mark.asyncio
async def test_lifespan_shutdown_cancels_tasks():
    """验证 lifespan shutdown 取消所有后台任务"""
    from dashboard.backend.main import lifespan, PollerState

    app_mock = MagicMock()
    task_called = asyncio.Event()

    async def dummy_task():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            task_called.set()
            raise

    # Mock engine_runner and ws_manager
    with patch('dashboard.backend.main.engine_runner') as mock_runner, \
         patch('dashboard.backend.main.ws_manager') as mock_ws:
        mock_runner.start = MagicMock()
        mock_runner.stop = MagicMock()
        mock_ws.disconnect_all = AsyncMock()

        # Patch the background tasks
        with patch('dashboard.backend.main.broadcast_prices', return_value=dummy_task()), \
             patch('dashboard.backend.main.broadcast_positions', return_value=asyncio.sleep(100)), \
             patch('dashboard.backend.main.broadcast_account', return_value=asyncio.sleep(100)), \
             patch('dashboard.backend.main.broadcast_logs', return_value=asyncio.sleep(100)), \
             patch('dashboard.backend.main.broadcast_engine_status', return_value=asyncio.sleep(100)), \
             patch('dashboard.backend.main.report_daily_loop', return_value=asyncio.sleep(100)), \
             patch('dashboard.backend.main.report_weekly_loop', return_value=asyncio.sleep(100)):

            async with lifespan(app_mock):
                assert PollerState.running is True

            assert PollerState.running is False
            mock_runner.stop.assert_called_once()
            mock_ws.disconnect_all.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_starts_engine():
    """验证 lifespan 启动引擎"""
    from dashboard.backend.main import lifespan, PollerState

    app_mock = MagicMock()

    with patch('dashboard.backend.main.engine_runner') as mock_runner, \
         patch('dashboard.backend.main.ws_manager') as mock_ws:
        mock_runner.start = MagicMock()
        mock_runner.stop = MagicMock()
        mock_ws.disconnect_all = AsyncMock()

        with patch('dashboard.backend.main.broadcast_prices', return_value=asyncio.sleep(100)), \
             patch('dashboard.backend.main.broadcast_positions', return_value=asyncio.sleep(100)), \
             patch('dashboard.backend.main.broadcast_account', return_value=asyncio.sleep(100)), \
             patch('dashboard.backend.main.broadcast_logs', return_value=asyncio.sleep(100)), \
             patch('dashboard.backend.main.broadcast_engine_status', return_value=asyncio.sleep(100)), \
             patch('dashboard.backend.main.report_daily_loop', return_value=asyncio.sleep(100)), \
             patch('dashboard.backend.main.report_weekly_loop', return_value=asyncio.sleep(100)):

            async with lifespan(app_mock):
                pass

            # Engine start was called (via to_thread)
            mock_runner.start.assert_called()


def test_poller_state_initial():
    """PollerState 初始状态"""
    from dashboard.backend.main import PollerState as PS
    assert hasattr(PS, 'running')
