"""
TradingEngine 线程封装 - 在后台 daemon 线程中运行 main.py 的多策略引擎
"""

import importlib.util
import logging
import os
import sys
import threading
import time
from datetime import datetime
from typing import Optional

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from core.bridge import MT4BridgeBase, OrderType


class EngineRunner:
    """在后台线程中运行 TradingEngine，暴露状态供 API / WebSocket 查询"""

    def __init__(self, config_service=None):
        self.config_service = config_service
        self.bridge: Optional[MT4BridgeBase] = None
        self._engine = None
        self.engine_thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_requested = False
        self._start_time: Optional[datetime] = None
        self.logger = logging.getLogger("engine_runner")

    @property
    def is_running(self) -> bool:
        return self._running and self.engine_thread is not None and self.engine_thread.is_alive()

    @property
    def uptime(self) -> float:
        if self._start_time and self.is_running:
            return (datetime.now() - self._start_time).total_seconds()
        return 0.0

    def start(self) -> bool:
        """启动引擎后台线程"""
        if self.is_running:
            return False

        self._stop_requested = False
        self.engine_thread = threading.Thread(target=self._run, daemon=True)
        self.engine_thread.start()
        time.sleep(3)  # 等待引擎初始化
        return True

    def stop(self):
        """请求引擎停止"""
        self._stop_requested = True
        if self._engine:
            self._engine.running = False
        if self.engine_thread and self.engine_thread.is_alive():
            self.engine_thread.join(timeout=15)

    def get_status(self) -> dict:
        """获取引擎状态"""
        return {
            "status": "running" if self.is_running else "stopped",
            "uptime_seconds": self.uptime,
            "started_at": self._start_time.isoformat() if self._start_time else None,
            "bridge_connected": self.bridge is not None and hasattr(self.bridge, '_connected') and self.bridge._connected,
        }

    # ======================== 引擎主循环 ========================

    def _run(self):
        """后台线程入口 - 运行多策略 TradingEngine"""
        try:
            self._run_impl()
        except Exception as e:
            self.logger.exception(f"引擎线程异常终止: {e}")
            self._running = False
            self._engine = None
            self.bridge = None

    def _run_impl(self):
        """引擎实际运行逻辑，异常由 _run 统一捕获"""
        # 切换到项目根目录，确保日志/配置路径正确
        project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "../.."))
        os.chdir(project_root)
        sys.path.insert(0, project_root)

        self.logger.info("=" * 60)
        self.logger.info("XAUUSD Web Dashboard - 启动多策略交易引擎")
        self.logger.info("=" * 60)

        # 导入多策略引擎（用 importlib 避开 module 缓存冲突 'main'）
        try:
            main_path = os.path.join(project_root, "main.py")
            spec = importlib.util.spec_from_file_location("xauusd_trading_engine", main_path)
            if spec is None or spec.loader is None:
                self.logger.error(f"无法加载 TradingEngine: {main_path} 不存在或格式错误")
                self._running = False
                return
            main_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(main_module)
            TradingEngine = main_module.TradingEngine
        except Exception as e:
            self.logger.error(f"无法导入 TradingEngine: {e}")
            self._running = False
            return

        engine = TradingEngine()
        self._engine = engine

        # 连接 MT4
        if not engine.bridge.connect():
            self.logger.error("无法连接 MT4，请确认 MT4 终端已运行且 EA 已加载")
            self._running = False
            return

        # 暴露 bridge 供 Dashboard WebSocket 轮询使用
        self.bridge = engine.bridge

        # 初始化策略风控状态
        for s in engine.strategies:
            engine._init_risk_state(s.name, s.magic)

        # 接管现有持仓
        from config import settings as _cfg
        for s in engine.strategies:
            existing = engine.bridge.takeover_existing_positions(
                _cfg.SYMBOL, s.magic
            )
            for pos in existing:
                engine._entry_times[pos.ticket] = time.time()

        engine._daily_start_balance = engine._get_balance()
        engine.running = True
        self._start_time = datetime.now()
        self._running = True
        self.logger.info("进入主循环...")

        # 主循环 — 与 TradingEngine.start() 逻辑一致，但支持外部 stop 信号
        while engine.running and not self._stop_requested:
            try:
                engine._tick()
            except Exception as e:
                self.logger.exception(f"主循环异常: {e}")
                time.sleep(60)

        # 清理
        if engine.bridge:
            engine.bridge.disconnect()
        self._running = False
        self._engine = None
        self.bridge = None
        self.logger.info("交易引擎已停止")
