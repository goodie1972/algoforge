"""
deps.py — FastAPI 依赖注入容器

替代 main.py 中的全局变量 + 手动赋值模式。
路由模块通过 Depends(get_xxx) 获取依赖实例。
"""
from functools import lru_cache

from dashboard.backend.config_service import RuntimeConfig
from dashboard.backend.engine_runner import EngineRunner
from dashboard.backend.web_manager import WebSocketManager
from dashboard.backend.broadcast_hub import BroadcastHub
from dashboard.backend.log_service import LogCaptureHandler


@lru_cache
def get_config() -> RuntimeConfig:
    return RuntimeConfig()


@lru_cache
def get_ws_manager() -> WebSocketManager:
    return WebSocketManager()


@lru_cache
def get_broadcast_hub() -> BroadcastHub:
    return BroadcastHub()


@lru_cache
def get_log_handler() -> LogCaptureHandler:
    return LogCaptureHandler()


@lru_cache
def get_engine_runner() -> EngineRunner:
    return EngineRunner(config_service=get_config())
