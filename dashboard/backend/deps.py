"""
deps.py — FastAPI 依赖注入容器

@deprecated: 当前所有路由均通过模块级变量（engine_runner / run_bridge）
直接获取依赖实例，本文件的 lru_cache 容器从未被任何路由使用。
保留此文件仅为兼容历史代码，不建议新路由引用。
如后续重构切换到 Depends() 模式，可恢复使用。
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
