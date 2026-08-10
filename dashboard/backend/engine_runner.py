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
        self._cached_bid: float = 0.0
        # 独立价格轮询线程（不受 _tick 阻塞影响）
        self._price_thread: Optional[threading.Thread] = None
        self._bias_thread: Optional[threading.Thread] = None

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

    @property
    def supervisor(self):
        """获取引擎的监督者实例"""
        if self._engine and hasattr(self._engine, 'supervisor'):
            return self._engine.supervisor
        return None

    def start(self) -> bool:
        """启动引擎后台线程"""
        if self.is_running:
            return False

        self._stop_requested = False
        self.engine_thread = threading.Thread(target=self._run, daemon=False)
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

    def close_position(self, ticket: int | str, volume: float = 0) -> bool:
        """平仓并记录到数据库 + 更新引擎风险状态"""
        if not self._engine or not self.bridge:
            return False

        # 获取平仓前持仓信息（用于判断方向）
        pos_info = None
        try:
            positions = self.bridge.get_positions("XAUUSD")
            for p in positions:
                if str(p.ticket) == str(ticket):
                    pos_info = p
                    break
        except Exception:
            pass

        ok = self.bridge.close_order(ticket, volume)
        if not ok:
            return False

        # 从 bridge 的已平仓列表（_closed 是 list）中查找刚平仓的记录
        closed_list = getattr(self.bridge, '_closed', [])
        closed_record = None
        for rec in reversed(closed_list):
            if str(rec.get("ticket", "")) == str(ticket):
                closed_record = rec
                break

        if not closed_record and pos_info:
            # 用持仓信息兜底构造记录
            direction = "BUY" if pos_info.order_type in ("OP_BUY", "BUY") else "SELL"
            closed_record = {
                "pnl": 0,
                "magic": pos_info.magic,
                "direction": direction,
                "symbol": pos_info.symbol,
                "volume": pos_info.volume,
                "entry_price": pos_info.open_price,
                "exit_price": 0,
                "stop_loss": pos_info.stop_loss,
                "take_profit": pos_info.take_profit,
                "strategy": pos_info.comment,
                "commission": 0,
            }

        if closed_record and self._engine:
            pnl = closed_record.get("pnl", 0)
            magic = closed_record.get("magic", 0)
            direction = closed_record.get("direction", "")

            # 更新引擎风险状态（realized_pnl / 连续亏损 / 快速出场等）
            self._engine._record_close(ticket, pnl, magic, direction)

            # 写入 trades 表
            try:
                from data import database as db
                record = {
                    "ticket": ticket,
                    "symbol": closed_record.get("symbol", "XAUUSD"),
                    "order_type": "BUY" if direction == "BUY" else "SELL",
                    "volume": closed_record.get("volume", 0.01),
                    "entry_price": closed_record.get("entry_price", 0),
                    "exit_price": closed_record.get("exit_price", 0),
                    "pnl": round(pnl, 2),
                    "stop_loss": closed_record.get("stop_loss", 0),
                    "take_profit": closed_record.get("take_profit", 0),
                    "swap": 0,
                    "commission": closed_record.get("commission", 0),
                    "magic": magic,
                    "strategy": closed_record.get("strategy", ""),
                    "open_time": "",
                    "close_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "hold_seconds": 0,
                    "exit_reason": "manual_close",
                }
                db.insert_trade(record)
            except Exception as e:
                self.logger.error(f"Failed to log manual close ticket={ticket}: {e}")

        # 立即刷新缓存
        self._update_positions_cache()
        return True
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
            from strategies.scanner import scan_strategies
            strategy_modules = []
            for name, cls in scan_strategies().items():
                strategy_modules.append((cls.__module__, name))
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
                    self.logger.warning(f"[VersionSync] {mod_name} failed: {e}")
            self.logger.info(f"[VersionSync] Wrote {total} version records")
        except Exception as e:
            self.logger.warning(f"[VersionSync] Skipped: {e}")

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
                self.logger.info("[DataSync] No active strategies, skipped")
                return

            self.logger.info(f"[DataSync] Checking timeframes: {active_tfs}")
            for tf in sorted(active_tfs):
                try:
                    latest = db.get_latest_timestamp(tf)
                    now_ts = int(time.time())
                    tf_sec = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                              "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}
                    interval = tf_sec.get(tf, 3600)

                    if latest is None:
                        self.logger.info(f"[DataSync] {tf} no data, starting download")
                        n = download_timeframe(engine.bridge, tf)
                        self.logger.info(f"[DataSync] {tf} download complete, wrote {n} candles")
                    else:
                        gap = now_ts - latest
                        if gap > interval * 3:  # 缺失超过 3 根
                            self.logger.info(f"[DataSync] {tf} latest data {datetime.fromtimestamp(latest).strftime('%Y-%m-%d %H:%M')}, gap {gap//interval} candles, starting backfill")
                            n = download_timeframe(engine.bridge, tf)
                            self.logger.info(f"[DataSync] {tf} backfill complete, wrote {n} candles")
                        else:
                            self.logger.info(f"[DataSync] {tf} data is complete (latest {datetime.fromtimestamp(latest).strftime('%Y-%m-%d %H:%M')})")
                except Exception as e:
                    self.logger.error(f"[DataSync] {tf} processing failed: {e}")

            # 打印汇总
            stats = db.get_db_stats()
            for tf, info in stats.items():
                if info["count"] > 0:
                    self.logger.info(f"[DataSync] {tf}: {info['count']} candles ({info['from']} ~ {info['to']})")
        except Exception as e:
            self.logger.warning(f"[DataSync] Skipped (module not ready: {e})")

    # ======================== 缓存更新（仅从价格轮询线程调用，消除主线程 bridge 竞争） ========================

    def _fresh_positions(self):
        """用最新 cached_price 刷新持仓盈亏（每 0.1s 价格采样实时重算）"""
        positions = list(self._cached_positions)
        price = self._cached_price
        if not positions or not price:
            return positions
        bid = price.get("bid", 0)
        ask = price.get("ask", 0)
        fresh = []
        for p in positions:
            p = dict(p)
            entry = p.get("open_price", 0)
            volume = p.get("volume", 0.01)
            is_sell = "SELL" in p.get("order_type", "")
            current = bid if is_sell else ask
            p["current_price"] = current
            if entry > 0 and current > 0:
                diff = (entry - current) if is_sell else (current - entry)
                p["profit"] = round(diff * volume * 100, 2)
            fresh.append(p)
        return fresh

    def _update_positions_cache(self):
        """从 bridge 更新持仓缓存（仅从价格轮询线程调用，无 lock 竞争）"""
        from config import settings as _cfg
        try:
            positions = self.bridge.get_positions(_cfg.SYMBOL)
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

    def _update_account_cache(self):
        """从 bridge 更新账户缓存（仅从价格轮询线程调用）"""
        try:
            info = self.bridge.get_account_info()
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
        """返回缓存的 K 线（最后一根已用实时中间价扩展），None 表示缓存未就绪"""
        candles = self._cached_candles.get(timeframe)
        if not candles or len(candles) < 3:
            return None
        # 用最新中间价 (bid+ask)/2 扩展最后一根 K 线，与页面"现价"一致
        result = [dict(c) for c in candles]
        last = result[-1]
        price = self._cached_price
        if price and price.get("bid", 0) > 0 and price.get("ask", 0) > 0:
            mid = round((price["bid"] + price["ask"]) / 2, 2)
            last["high"] = round(max(last["high"], mid), 2)
            last["low"] = round(min(last["low"], mid), 2)
            last["close"] = mid
        result[-1] = last
        # 按时间戳去重（保留最后出现的一条），轻量级图表不允许重复时间戳
        seen: set = set()
        deduped = []
        for c in reversed(result[-count:]):
            t = c["time"]
            if t not in seen:
                seen.add(t)
                deduped.append(c)
        deduped.reverse()
        # 过滤无效值，防止轻量级图表报错
        _valid = all(
            isinstance(c.get(k), (int, float))
            for c in result for k in ("open", "high", "low", "close")
        )
        if not _valid:
            return None
        return deduped

    def _refresh_candle_cache(self, engine):
        """从数据工厂缓存刷新 K 线缓存（每 tick 最多刷一个周期，避免堵塞快速采样）"""
        now = time.time()
        # 按优先级依次刷新：H1 > M30 > M15 > M5 > H4 > D1 > W1 > M1
        priority = ["H1", "M30", "M15", "M5", "H4", "D1", "W1", "M1"]
        for tf in priority:
            last_ts = self._cached_candles_ts.get(tf, 0)
            if now - last_ts >= 120 or tf not in self._cached_candles:
                try:
                    # 三轨：从数据工厂缓存读取（避免直接调桥接）
                    df = getattr(engine, '_data_factory', None)
                    if df:
                        from services.data_factory import get_cache
                        cache = get_cache(tf)
                        raw = cache.get("candles", [])
                        if raw:
                            offset = int(getattr(engine, '_mt4_offset', 0))
                            self._cached_candles[tf] = [
                                {"time": int(c.time) - offset,
                                 "open": c.open, "high": c.high, "low": c.low,
                                 "close": c.close, "volume": c.volume}
                                for c in raw
                            ]
                            self._cached_candles_ts[tf] = now
                    else:
                        # 回退：旧模式从桥接获取
                        from config import settings as _cfg
                        raw = engine.bridge.get_candles(_cfg.SYMBOL, tf, 200)
                        raw_rev = list(reversed(raw))
                        offset = int(getattr(engine, '_mt4_offset', 0))
                        self._cached_candles[tf] = [
                            {"time": int(c.time) - offset, "open": c.open,
                             "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
                            for c in raw_rev
                        ]
                        self._cached_candles_ts[tf] = now
                except Exception:
                    pass
                return  # 只刷一个周期就退出，下个 tick 再刷下一个


    # ======================== DataFactory 健康监控 ========================

    def _check_data_factory_health(self, engine):
        """检查 DataFactory 数据健康状况，发现异常时报警"""
        df = getattr(engine, '_data_factory', None)
        if not df or not df._running:
            return
        now = time.time()
        if now - getattr(self, '_last_df_health_check', 0) < 60:
            return
        self._last_df_health_check = now

        try:
            from services.data_factory import get_health
            health = get_health()
            tfs = health.get("tfs", {})

            for tf, status in tfs.items():
                if not status.get("ok", False):
                    self.logger.warning(f"[DataFactoryMonitor] {tf} sync failed")
                    continue
                age = now - status.get("last_sync", 0)
                if age > 60:
                    self.logger.warning(f"[DataFactoryMonitor] {tf} data stale {age:.0f}s (over 60s since last sync)")
                if status.get("candles", 0) < 30:
                    self.logger.warning(f"[DataFactoryMonitor] {tf} insufficient data: {status.get('candles', 0)} candles")

            tick_age = now - health.get("last_tick_time", 0)
            if tick_age > 60 and health.get("bridging", False):
                self.logger.warning(f"[DataFactoryMonitor] Quotes stale {tick_age:.0f}s")

            if not health.get("bridging", False):
                self.logger.error("[DataFactoryMonitor] Bridge not connected!")

            errs = health.get("sync_errors", [])
            if errs:
                last = errs[-1]
                self.logger.warning(f"[DataFactoryMonitor] Recent sync error: {last.get('tf','?')} - {last.get('err','?')[:60]}")
        except Exception as e:
            self.logger.warning(f"[DataFactoryMonitor] Check failed: {e}")


    # ======================== 独立价格轮询线程 ========================

    def _start_price_poller(self, engine):
        """启动独立价格轮询线程（1s 间隔，匹配 EA OnTimer 处理能力）
        也在此线程中定期更新持仓/账户缓存，避免主线程与 poller 争 bridge 锁。"""
        if self._price_thread and self._price_thread.is_alive():
            return
        from config import settings as _cfg
        def _poll():
            tick_count = 0
            while not self._stop_requested:
                try:
                    _b, _a = engine.bridge.get_tick_price(_cfg.SYMBOL)
                    if _b > 0:
                        self._cached_price = {"bid": _b, "ask": _a}
                        self._cached_bid = _b
                except Exception:
                    pass
                # 每 5 tick (~5s) 更新持仓和账户缓存，与价格更新复用同个线程，
                # 避免主循环 _tick() 中的 heartbeat 与 poller 争 bridge 锁
                tick_count += 1
                if tick_count % 5 == 0:
                    self._update_positions_cache()
                    self._update_account_cache()
                time.sleep(1.0)
        self._price_thread = threading.Thread(target=_poll, daemon=True, name="price_poller")
        self._price_thread.start()

    # ======================== News-Bias 缓存刷新线程 ========================

    def _start_bias_refresher(self):
        """定期从核心 bias_state 刷新新闻偏向缓存（策略层读取）。
        bias_state.refresh_from_db() 已改为读取新的 gold_news 方向。"""
        if getattr(self, '_bias_thread', None) and self._bias_thread.is_alive():
            return

        def _refresh():
            try:
                from core import bias_state
                bias_state.refresh_from_db()
            except Exception as e:
                self.logger.warning(f"[bias_refresher] First refresh failed: {e}")

            while not self._stop_requested:
                for _ in range(60):
                    if self._stop_requested:
                        return
                    time.sleep(1)
                try:
                    from core import bias_state
                    bias_state.refresh_from_db()
                except Exception as e:
                    self.logger.debug(f"[bias_refresher] Refresh failed: {e}")

        self._bias_thread = threading.Thread(target=_refresh, daemon=True, name="bias_refresher")
        self._bias_thread.start()

    # ======================== 引擎主循环 ========================

    def _run(self):
        """后台线程入口 - 运行多策略 TradingEngine"""
        try:
            self._run_impl()
        except Exception as e:
            self.logger.exception(f"Engine thread terminated abnormally: {e}")
            self._stop_requested = True
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
        self.logger.info("XAUUSD Web Dashboard - Starting multi-strategy trading engine")
        self.logger.info("=" * 60)

        # 强制重载配置，确保引擎使用最新的 settings.py
        import config.settings as _cfg_reload
        importlib.reload(_cfg_reload)
        self.logger.info(f"[Config] STRATEGY_POOL: {list(_cfg_reload.STRATEGY_POOL.keys())}")

        # 导入多策略引擎（用 importlib 避开 module 缓存冲突 'main'）
        try:
            # main.py 已移至 engine_standalone/ 子目录
            main_path = os.path.join(project_root, "engine_standalone", "main.py")
            spec = importlib.util.spec_from_file_location("xauusd_trading_engine", main_path)
            if spec is None or spec.loader is None:
                self.logger.error(f"Failed to load TradingEngine: {main_path} does not exist or is malformed")
                self._running = False
                return
            main_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(main_module)
            TradingEngine = main_module.TradingEngine
        except Exception as e:
            self.logger.error(f"Failed to import TradingEngine: {e}")
            self._running = False
            return

        engine = TradingEngine(config_service=self.config_service)
        self._engine = engine

        # 连接 MT4（带重试）
        if not engine.bridge.connect():
            self.logger.warning("Failed to connect to MT4, retrying every 10 seconds...")
            for attempt in range(30):
                time.sleep(10)
                if engine.bridge.connect():
                    self.logger.info(f"Connected after {attempt+1} retries")
                    break
            else:
                self.logger.error("Failed to connect to MT4 after 30 retries")
                self._running = False
                return

        # 暴露 bridge 供 Dashboard WebSocket 轮询使用
        self.bridge = engine.bridge

        # 启动独立价格轮询（0.1s 间隔，不受 _tick 阻塞）
        self._start_price_poller(engine)

        # 启动新闻偏向缓存刷新（写入 core.bias_state，策略层读取）
        self._start_bias_refresher()

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
        self.logger.info("Entering main loop...")

        # 连接数据桥接 + 启动数据工厂独立线程
        try:
            if getattr(engine, '_data_factory', None):
                engine._data_factory.connect()
                engine._data_factory.start()
                self.logger.info("[DataFactory] Started (data bridge mode)")
        except Exception as e:
            self.logger.warning(f"[DataFactory] Start failed: {e}")

        # 自动补充遗漏历史成交
        engine._recover_missing_trades()

        # 引擎启动后检查数据库数据完整性，自动补漏
        self._sync_data_after_start(engine)

        # 将各策略 STRATEGY_CHANGELOG 写入数据库 strategy_versions 表
        self._sync_strategy_versions()

        # 主循环 — 与 TradingEngine.start() 逻辑一致，但支持外部 stop 信号
        # 价格/持仓/账户采样由独立线程 _price_poller 负责（1s 间隔）
        while engine.running and not self._stop_requested:
            try:
                engine._tick()  # 内含心跳、策略处理、执行
            except Exception as e:
                self.logger.exception(f"Main loop exception: {e}")
                time.sleep(60)

            # K 线缓存后台刷新（低频率，与 _tick 串行避免桥接冲突）
            try:
                self._refresh_candle_cache(engine)
            except Exception:
                pass

            # DataFactory 健康检查（每 60 秒一次）
            self._check_data_factory_health(engine)

        # 清理
        if engine.bridge:
            engine.bridge.disconnect()
        self._running = False
        self._engine = None
        self.bridge = None
        self.logger.info("Trading engine stopped")
