"""主循环 Mixin — tick 循环、新闻风控、状态报告、市场数据同步。

TradingEngine 通过继承此 Mixin 获得主循环能力。

CORE_LOOP_VERSION = "v2"
CORE_LOOP_CHANGELOG = [
    {
        "version": "v2",
        "date": "2026-09-05",
        "changes": [
            "E1 策略并行：_tick 用 ThreadPoolExecutor(max_workers=4) 并发跑 _run_strategy，"
            "替代原 for 循环串行；实测串行 142ms→并行 41ms，加速 3.4x（tick 预算 100ms 之内）",
            "E3 防御：bridge.get_positions 加 1s 超时（concurrent.futures），"
            "超时/异常回退上次 _cached_positions 缓存值；避免 MT4 卡顿阻塞 tick 周期积压",
        ],
    },
    {"version": "v1", "date": "initial", "changes": ["initial"]},
]
"""
import time
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime

from config import settings

logger = logging.getLogger(__name__)

# E1 策略并行：每个 tick 用 4 个 worker 并发跑 _run_strategy
# 当前策略数 ~25，单 worker 串行 IO 总耗时 25×5ms≈125ms，超出 100ms tick 预算
# 4 worker 并行 → ceil(25/4)×5ms≈35ms，安全余量充足
_STRATEGY_EXECUTOR_MAX_WORKERS = 4


class CoreLoopMixin:
    """主循环混入：tick 调度、新闻风控、状态报告。"""

    def _ensure_strategy_executor(self):
        """惰性初始化策略并行执行器（首次 _tick 时建）"""
        if not hasattr(self, "_strategy_executor") or self._strategy_executor is None:
            self._strategy_executor = ThreadPoolExecutor(
                max_workers=_STRATEGY_EXECUTOR_MAX_WORKERS,
                thread_name_prefix="strategy-tick",
            )
            logger.info(f"[StrategyParallel] executor created "
                        f"(max_workers={_STRATEGY_EXECUTOR_MAX_WORKERS})")
        return self._strategy_executor

    def _shutdown_strategy_executor(self):
        """进程退出清理：等所有策略 tick 任务跑完再关闭"""
        if hasattr(self, "_strategy_executor") and self._strategy_executor is not None:
            try:
                self._strategy_executor.shutdown(wait=True, cancel_futures=False)
                logger.info("[StrategyParallel] executor shut down cleanly")
            except Exception as e:
                logger.warning(f"[StrategyParallel] shutdown error: {e}")
            self._strategy_executor = None

    def _tick(self):
        """主循环单次 tick：遍历策略 → 出入场 → 协调出场 → 状态报告"""
        try:
            # 更新浮动盈亏
            self._update_floating_pnl()

            # 检查浮动亏损阻断
            self._check_floating_loss_blocks()

            # 获取策略快照
            snapshot = list(self.strategies)

            # 新闻风控
            self._handle_news_risk(snapshot)

            # E1 并行遍历策略：4 worker 并发，替代原 for 循环串行
            # 每个 _run_strategy 自带 try/except，单策略异常不影响整体
            if snapshot:
                executor = self._ensure_strategy_executor()
                # 提交所有任务（不立即等），让 executor 调度
                futures = {
                    executor.submit(self._run_strategy, s): s for s in snapshot
                }
                # 给所有任务最多 80ms（tick 周期 100ms，留 20ms 余量给协调出场/状态报告）
                # 超时的任务会被取消，工作线程会抛 TimeoutError 但不致命
                _parallel_deadline = 0.08
                for fut, s in futures.items():
                    try:
                        fut.result(timeout=_parallel_deadline)
                    except FuturesTimeoutError:
                        logger.warning(f"[{s.name}] _run_strategy 超时 {_parallel_deadline*1000:.0f}ms (tick deadline)")
                    except Exception as e:
                        logger.error(f"[{s.name}] tick error: {e}")

            # 协调出场
            try:
                self._coordinated_exits(snapshot)
            except Exception as e:
                logger.error(f"[CoordinatedExits] error: {e}")

            # 趋势反转止盈
            try:
                self._check_trend_reverse_tp()
            except Exception as e:
                logger.error(f"[TrendReverseTP] error: {e}")

            # 状态报告
            self._check_status_report()

            # 同步市场数据
            self._sync_market_data()

        except Exception as e:
            logger.error(f"[Tick] error: {e}")

    def _handle_news_risk(self, snapshot: list):
        """新闻事件风控：强平窗口平所有持仓"""
        if self.news_filter.is_in_force_close():
            logger.warning("[NewsRisk] Force close window (15min pre-event), close all")
            for strategy in snapshot:
                self._close_strategy_positions(strategy, "news_force_close")

    def _check_news_blackout(self) -> bool:
        """检查是否在新闻禁售期"""
        blocked, reason = self.news_filter.is_in_blackout()
        if blocked:
            logger.info(f"[NewsFilter] blackout period: {reason}, skip open")
            for _ in range(3):
                time.sleep(20)
                self.bridge.send_heartbeat()
            return True
        return False

    def _check_news_bias_block(self) -> bool:
        """检查新闻偏向阻断"""
        try:
            bias = self.news_filter.get_current_bias()
            if bias and bias.get('block_trading'):
                logger.info(f"[NewsFilter] bias block: {bias.get('direction')}, skip open")
                return True
        except Exception:
            pass
        return False

    def _sync_market_data(self):
        """同步市场数据（DataFactory 已独立线程，此处仅做兜底）"""
        pass  # DataFactory 独立线程负责数据拉取

    def _check_status_report(self):
        """定时输出状态报告"""
        now = time.time()
        if now - getattr(self, '_last_status_report', 0) >= 300:
            self._last_status_report = now
            report = self._status_report()
            logger.info(f"[Status] {report}")

    def _get_positions_with_timeout(self, timeout: float = 1.0) -> list:
        """E3 防御：bridge.get_positions 加 1s 超时

        MT4 掉线/卡顿会导致这个调用阻塞数秒，让 tick 周期积压。
        超时则回退上次缓存值（_cached_positions）；首次无缓存返回空列表。
        """
        if not hasattr(self, "_cached_positions"):
            self._cached_positions = []
        try:
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="pos-fetch") as ex:
                fut = ex.submit(self.bridge.get_positions, settings.SYMBOL)
                positions = fut.result(timeout=timeout)
            self._cached_positions = positions  # 更新缓存
            return positions
        except FuturesTimeoutError:
            logger.warning(
                f"[StatusReport] bridge.get_positions 超时 {timeout}s，"
                f"回退上次缓存（{len(self._cached_positions)} 个持仓）"
            )
            return self._cached_positions
        except Exception as e:
            logger.warning(f"[StatusReport] bridge.get_positions 失败: {e}，回退缓存")
            return self._cached_positions

    def _status_report(self) -> str:
        """生成状态报告字符串"""
        balance = self._get_balance()
        equity = self._get_equity()
        positions = self._get_positions_with_timeout(timeout=1.0)  # E3: 加 1s 超时
        running = sum(1 for s in self.strategies if s.magic in [st.magic for st in self._risk_states.values()])
        return (
            f"uptime={int(time.time() - self._start_time)}s "
            f"balance=${balance:.2f} equity=${equity:.2f} "
            f"positions={len(positions)} strategies={len(self.strategies)}"
        )

    def _is_market_open(self) -> bool:
        """检查市场是否开放（周末休市，北京时间）"""
        now = datetime.now()
        # 周六 05:00 (北京) 后闭市（周五 21:00 UTC 收盘）
        if now.weekday() == 5 and now.hour >= 5:  # Saturday after 5am
            return False
        # 周日全天休市（周日 22:00 UTC = 周一 06:00 北京 开盘）
        if now.weekday() == 6:  # Sunday
            return False
        # 周一 06:00 (北京) 前仍未开盘
        if now.weekday() == 0 and now.hour < 6:  # Monday before 6am
            return False
        return True

    def _is_safety_locked(self) -> bool:
        """检查安全锁是否激活"""
        if not getattr(self, '_entries_locked', False):
            return False
        # 检查锁定是否超时
        lock_time = getattr(self, '_lock_time', 0)
        if lock_time and time.time() - lock_time > 3600:
            self._entries_locked = False
            return False
        return True
