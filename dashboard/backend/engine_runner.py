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
        # K 线实时缓存：按 timeframe 缓存，最后一根 K 线由实时价格扩展
        self._cached_candles: dict[str, list] = {}
        self._cached_candles_ts: dict[str, float] = {}
        self._cached_mid: float = 0.0

    @property
    def is_running(self) -> bool:
        return self._running and self.engine_thread is not None and self.engine_thread.is_alive()

    @property
    def mt4_offset(self) -> float:
        """MT4 服务器时间与 UTC 的偏移秒数（引擎校准后的值）"""
        if self._engine and hasattr(self._engine, '_mt4_offset'):
            return self._engine._mt4_offset
        return 0.0

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

    # ======================== 策略版本写入数据库 ========================

    def _sync_strategy_versions(self):
        """将各策略文件中的 STRATEGY_CHANGELOG 写入 strategy_versions 表"""
        try:
            from data.database import upsert_strategy_version
            import importlib
            strategy_modules = [
                ("strategies.m30_rsi", "M30_rsi_bb"),
                ("strategies.v6_hybrid", "H1_v6_hybrid"),
                ("strategies.sanqing_h1", "sanqing_h1"),
                ("strategies.gold_autoresearch_h1", "gold_auto_research"),
            ]
            total = 0
            for mod_name, strat_name in strategy_modules:
                try:
                    mod = importlib.import_module(mod_name)
                    changelog = getattr(mod, "STRATEGY_CHANGELOG", [])
                    for entry in changelog:
                        upsert_strategy_version(
                            magic=entry["magic"],
                            strategy_name=strat_name,
                            version=entry["version"],
                            date=entry["date"],
                            description=entry["desc"],
                        )
                        total += 1
                except Exception as e:
                    self.logger.warning(f"[版本同步] {mod_name} 失败: {e}")
            self.logger.info(f"[版本同步] 写入 {total} 条版本记录")
        except Exception as e:
            self.logger.warning(f"[版本同步] 跳过: {e}")

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

    # ======================== 缓存更新（引擎线程调用，避免与广播任务抢 bridge socket） ========================

    def _fresh_positions(self):
        """用最新 cached_price 刷新持仓的 current_price（避免主循环缓存滞后）"""
        positions = list(self._cached_positions)
        price = self._cached_price
        if not positions or not price:
            return positions
        bid = price.get("bid", 0)
        ask = price.get("ask", 0)
        fresh = []
        for p in positions:
            p = dict(p)
            p["current_price"] = bid if "SELL" in p.get("order_type", "") else ask
            fresh.append(p)
        return fresh

    def _update_caches(self, engine):
        """从引擎线程更新 dashboard 缓存，消除并发 bridge 访问"""
        from config import settings as _cfg
        # 价格
        try:
            bid, ask = engine.bridge.get_tick_price(_cfg.SYMBOL)
            if bid > 0:
                self._cached_price = {"bid": bid, "ask": ask}
        except Exception:
            pass
        # 持仓
        try:
            positions = engine.bridge.get_positions(_cfg.SYMBOL)
            _bid = self._cached_price.get("bid", 0) if self._cached_price else 0
            _ask = self._cached_price.get("ask", 0) if self._cached_price else 0
            self._cached_positions = [
                {
                    "ticket": p.ticket,
                    "order_type": p.order_type,
                    "volume": p.volume,
                    "open_price": p.open_price,
                    "current_price": _bid if p.order_type == "SELL" else _ask,
                    "profit": round(p.profit, 2),
                    "stop_loss": p.stop_loss,
                    "take_profit": p.take_profit,
                    "magic": p.magic,
                    "comment": getattr(p, "comment", ""),
                    "open_time": getattr(p, "open_time", ""),
                    "strategy": getattr(p, "comment", ""),
                }
                for p in positions
            ]
        except Exception:
            pass
        # 账户
        try:
            info = engine.bridge.get_account_info()
            if info:
                self._cached_account = {
                    "login": info.login,
                    "balance": info.balance,
                    "equity": info.equity,
                    "margin": info.margin,
                    "free_margin": info.free_margin,
                    "currency": info.currency,
                    "leverage": info.leverage,
                }
        except Exception:
            pass

    # ======================== K 线实时缓存 ========================

    _TF_SECS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}

    def get_cached_candles(self, timeframe: str, count: int = 500) -> Optional[list]:
        """返回缓存的 K 线（最后一根已用实时价格扩展），None 表示缓存未就绪"""
        candles = self._cached_candles.get(timeframe)
        if not candles or len(candles) < 3:
            return None
        # 用最新中间价扩展最后一根 K 线
        result = list(candles)
        last = dict(result[-1])
        mid = self._cached_mid
        if mid > 0:
            last["high"] = round(max(last["high"], mid), 2)
            last["low"] = round(min(last["low"], mid), 2)
            last["close"] = round(mid, 2)
        result[-1] = last
        return result[-count:]

    def _refresh_candle_cache(self, engine):
        """从桥接刷新 K 线缓存（仅在数据过期时真正拉取）"""
        from config import settings as _cfg
        now = time.time()
        # 无论哪个 timeframe 过期都一起刷
        for tf, interval in self._TF_SECS.items():
            last_ts = self._cached_candles_ts.get(tf, 0)
            # 首次缓存或超过 120s 刷新
            if now - last_ts < 120 and tf in self._cached_candles:
                continue
            try:
                raw = engine.bridge.get_candles(_cfg.SYMBOL, tf, 500)
                raw_rev = list(reversed(raw))
                offset = int(self.mt4_offset)
                self._cached_candles[tf] = [
                    {
                        "time": int(c.time) - offset,
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "volume": c.volume,
                    }
                    for c in raw_rev
                ]
                self._cached_candles_ts[tf] = now
            except Exception:
                pass

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

        engine = TradingEngine(config_service=self.config_service)
        self._engine = engine

        # 连接 MT4（带重试）
        if not engine.bridge.connect():
            self.logger.warning("无法连接 MT4，每 10 秒重试...")
            for attempt in range(30):
                time.sleep(10)
                if engine.bridge.connect():
                    self.logger.info(f"第 {attempt+1} 次重试后连接成功")
                    break
            else:
                self.logger.error("重试 30 次仍无法连接 MT4")
                self._running = False
                return

        # 暴露 bridge 供 Dashboard WebSocket 轮询使用
        self.bridge = engine.bridge

        # 校准 MT4 服务器时间 vs 本机 UTC
        engine._calibrate_mt4_time()

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

        # 自动补充遗漏历史成交
        engine._recover_missing_trades()

        # 引擎启动后检查数据库数据完整性，自动补漏
        self._sync_data_after_start(engine)

        # 将各策略 STRATEGY_CHANGELOG 写入数据库 strategy_versions 表
        self._sync_strategy_versions()

        # 主循环 — 与 TradingEngine.start() 逻辑一致，但支持外部 stop 信号
        from config import settings as _cfg_fast
        while engine.running and not self._stop_requested:
            try:
                # 桥接保活检测
                try:
                    engine.bridge.send_heartbeat()
                except Exception:
                    self.logger.warning("[桥接] 心跳失败，尝试重连...")
                    try:
                        engine.bridge.disconnect()
                        time.sleep(2)
                        engine.bridge.connect()
                    except Exception as e2:
                        self.logger.error(f"[桥接] 重连失败: {e2}")

                engine._tick()
                self._update_caches(engine)
                # K 线缓存也在此周期刷新（120s 过期）
                self._refresh_candle_cache(engine)
            except Exception as e:
                self.logger.exception(f"主循环异常: {e}")
                time.sleep(60)

            # 高频价格采样：_tick() 处理策略逻辑较慢，
            # 每个 tick 后快速补采几次价格，使前端 ~1s 更新而非 ~N 秒
            for _ in range(3):
                if not engine.running or self._stop_requested:
                    break
                time.sleep(0.3)
                try:
                    _b, _a = engine.bridge.get_tick_price(_cfg_fast.SYMBOL)
                    if _b > 0:
                        self._cached_price = {"bid": _b, "ask": _a}
                        self._cached_mid = round((_b + _a) / 2, 2)
                except Exception:
                    pass

        # 清理
        if engine.bridge:
            engine.bridge.disconnect()
        self._running = False
        self._engine = None
        self.bridge = None
        self.logger.info("交易引擎已停止")
