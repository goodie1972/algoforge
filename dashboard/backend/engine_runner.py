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

        # 缓存由后台广播任务更新的最近数据，避免 REST API 与广播抢桥接锁
        self._cached_account: Optional[dict] = None
        self._cached_price: Optional[dict] = None
        self._cached_positions: list = []

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

    def add_strategy(self, name: str, cfg: dict) -> bool:
        """动态添加策略"""
        if self._engine:
            return self._engine.add_strategy(name, cfg)
        return False

    def remove_strategy(self, name: str, close_positions: bool = True) -> bool:
        """动态移除策略"""
        if self._engine:
            return self._engine.remove_strategy(name, close_positions)
        return False

    # ======================== 数据库数据完整性检查 ========================

    def _sync_data_after_start(self, engine):
        """引擎启动后检查数据库数据，按活跃策略的周期自动补漏"""
        try:
            from data import database as db
            from data.downloader import download_timeframe

            db.init_db()  # 确保表存在

            # 获取活跃策略的周期列表
            pool = {}
            if self.config_service:
                pool = self.config_service.get_strategy_pool()
            active_tfs = set()
            for name, cfg in pool.items():
                if cfg.get("enabled", False):
                    tf = cfg.get("timeframe", "H1")
                    active_tfs.add(tf)

            if not active_tfs:
                self.logger.info("[数据同步] 无活跃策略，跳过")
                return

            self.logger.info(f"[数据同步] 检查周期: {active_tfs}")
            for tf in sorted(active_tfs):
                try:
                    latest = db.get_latest_timestamp(tf)
                    now_ts = int(time.time())
                    tf_sec = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                              "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}
                    interval = tf_sec.get(tf, 3600)

                    if latest is None:
                        self.logger.info(f"[数据同步] {tf} 无数据，开始下载")
                        n = download_timeframe(engine.bridge, tf)
                        self.logger.info(f"[数据同步] {tf} 下载完成，写入 {n} 条")
                    else:
                        gap = now_ts - latest
                        if gap > interval * 3:  # 缺失超过 3 根
                            self.logger.info(f"[数据同步] {tf} 最新数据 {datetime.fromtimestamp(latest).strftime('%Y-%m-%d %H:%M')}，缺口 {gap//interval} 根，开始补漏")
                            n = download_timeframe(engine.bridge, tf)
                            self.logger.info(f"[数据同步] {tf} 补漏完成，写入 {n} 条")
                        else:
                            self.logger.info(f"[数据同步] {tf} 数据完整（最新 {datetime.fromtimestamp(latest).strftime('%Y-%m-%d %H:%M')}）")
                except Exception as e:
                    self.logger.error(f"[数据同步] {tf} 处理失败: {e}")

            # 打印汇总
            stats = db.get_db_stats()
            for tf, info in stats.items():
                if info["count"] > 0:
                    self.logger.info(f"[数据同步] {tf}: {info['count']} 条 ({info['from']} ~ {info['to']})")
        except Exception as e:
            self.logger.warning(f"[数据同步] 跳过（模块未就绪: {e}）")

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

        # 强制重载配置，确保引擎使用最新的 settings.py
        import config.settings as _cfg_reload
        importlib.reload(_cfg_reload)
        self.logger.info(f"[配置] STRATEGY_POOL: {list(_cfg_reload.STRATEGY_POOL.keys())}")

        # 导入多策略引擎（用 importlib 避开 module 缓存冲突 'main'）
        try:
            # main.py 已移至 engine_standalone/ 子目录
            main_path = os.path.join(project_root, "engine_standalone", "main.py")
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

        # 引擎启动后检查数据库数据完整性，自动补漏
        self._sync_data_after_start(engine)

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
