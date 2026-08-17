"""主循环 Mixin — tick 循环、新闻风控、状态报告、市场数据同步。

TradingEngine 通过继承此 Mixin 获得主循环能力。
"""
import time
import logging
from datetime import datetime

from config import settings

logger = logging.getLogger(__name__)


class CoreLoopMixin:
    """主循环混入：tick 调度、新闻风控、状态报告。"""

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

            # 遍历策略运行
            for strategy in snapshot:
                try:
                    self._run_strategy(strategy)
                except Exception as e:
                    logger.error(f"[{strategy.name}] tick error: {e}")

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

    def _status_report(self) -> str:
        """生成状态报告字符串"""
        balance = self._get_balance()
        equity = self._get_equity()
        positions = self.bridge.get_positions(settings.SYMBOL)
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
