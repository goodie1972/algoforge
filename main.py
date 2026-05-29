"""
实盘交易主循环 — 多策略并行引擎
支持 STRATEGY_POOL 中多个策略同时运行，各自独立 magic/timeframe
"""

import logging
import time
import sys
import os
import importlib
from datetime import datetime

from config import settings
from core.bridge import create_bridge, OrderType
from services.news_filter import NewsFilter
from strategies.double_ma import DoubleMAStrategy
from strategies.atr_breakout import ATRBreakoutStrategy
from strategies.combined import CombinedStrategy
from strategies.rsi_bollinger import RSIBollingerStrategy
from strategies.stoch_bollinger import StochBollingerStrategy

STRATEGY_MAP = {
    "double_ma": DoubleMAStrategy,
    "atr_breakout": ATRBreakoutStrategy,
    "combined": CombinedStrategy,
    "rsi_bollinger": RSIBollingerStrategy,
    "stoch_bollinger": StochBollingerStrategy,
}

# 日志配置
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(f"{settings.LOG_DIR}/trading_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def create_strategies(bridge):
    """从 STRATEGY_POOL 创建策略实例列表"""
    strategies = []
    for name, cfg in settings.STRATEGY_POOL.items():
        cls = STRATEGY_MAP.get(name)
        if cls is None:
            logger.warning(f"未知策略: {name}，跳过")
            continue
        strategy = cls(bridge, magic=cfg["magic"], timeframe=cfg["timeframe"])
        # 附加策略专属配置
        strategy.magic = cfg["magic"]
        strategy.double_first = cfg.get("double_first", False)
        strategy.max_positions = cfg.get("max_positions", 1)
        strategies.append(strategy)
        logger.info(f"[策略加载] {name} Magic={strategy.magic} TF={strategy.timeframe}")
    return strategies


class TradingEngine:
    """多策略交易引擎"""

    def __init__(self):
        self.bridge = create_bridge()
        self.strategies = create_strategies(self.bridge)
        self.news_filter = NewsFilter()
        self.running = False
        self._last_balance_check = 0
        self._daily_start_balance = 0.0
        self._last_report_time = 0
        self._report_interval = 4 * 3600
        self._config_mtime = 0.0
        self._last_news_check = 0.0

    def start(self):
        logger.info("=" * 60)
        logger.info("XAUUSD 多策略交易系统 启动")
        logger.info(f"品种: {settings.SYMBOL} | 手数: {settings.LOT_SIZE}")
        for s in self.strategies:
            logger.info(f"  策略: {s.name} | Magic={s.magic} | TF={s.timeframe} | "
                        f"双倍首单={s.double_first} | 最大仓位={s.max_positions}")
        logger.info("=" * 60)

        if not self.bridge.connect():
            logger.error("无法连接 MT4")
            return

        # 接管所有策略的现有持仓
        for s in self.strategies:
            existing = self.bridge.takeover_existing_positions(settings.SYMBOL, s.magic)

        self._daily_start_balance = self._get_balance()
        self.running = True

        # 新闻过滤初始化加载
        windows = self.news_filter.get_blackout_windows()
        if windows:
            logger.info(f"[新闻过滤] 已加载 {len(windows)} 个禁售窗口:")
            for s, e, t in windows[:5]:
                logger.info(f"  {s.strftime('%m-%d %H:%M')} ~ {e.strftime('%H:%M')} | {t}")

        logger.info("进入主循环...")

        while self.running:
            try:
                self._tick()
            except KeyboardInterrupt:
                logger.info("收到中断信号，停止交易")
                self.running = False
            except Exception as e:
                logger.exception(f"主循环异常: {e}")
                time.sleep(60)

        self.bridge.disconnect()
        logger.info("交易引擎已停止")

    def _tick(self):
        # 配置热重载
        try:
            mtime = os.path.getmtime(settings.__file__)
            if mtime > self._config_mtime:
                self._config_mtime = mtime
                importlib.reload(settings)
                for s in self.strategies:
                    s.reload_config()
                logger.info("[热重载] 配置已更新")
        except OSError:
            pass

        self._check_status_report()

        # 风控
        if self._check_daily_loss():
            for _ in range(3):
                time.sleep(20)
                self.bridge.send_heartbeat()
            return

        # 新闻过滤 — 重大数据发布前后暂停开仓
        if self._check_news_blackout():
            return

        # ---- 遍历每个策略独立运行 ----
        for strategy in self.strategies:
            self._run_strategy(strategy)

    def _run_strategy(self, strategy):
        """单个策略的一次 tick"""
        # 刷新数据
        strategy.refresh_data()

        # 获取该策略的持仓
        positions = self.bridge.get_positions(settings.SYMBOL)
        my_positions = [p for p in positions if p.magic == strategy.magic]
        n_total = len(my_positions)
        n_longs = sum(1 for p in my_positions if p.order_type in ("OP_BUY", "BUY"))
        n_shorts = sum(1 for p in my_positions if p.order_type in ("OP_SELL", "SELL"))
        logger.info(f"[{strategy.name}] 持仓: {n_total} (多:{n_longs} 空:{n_shorts})")

        # --- EMA20 跟踪止损出场 ---
        if my_positions:
            bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
            for pos in my_positions:
                if strategy.check_ema20_exit(pos, bid, ask):
                    logger.info(f"[{strategy.name}] EMA20跟踪止损平仓 Ticket={pos.ticket}")
                    self.bridge.close_order(pos.ticket)

        # 重新获取持仓
        positions = self.bridge.get_positions(settings.SYMBOL)
        my_positions = [p for p in positions if p.magic == strategy.magic]
        n_total = len(my_positions)

        if n_total >= strategy.max_positions:
            return  # 已达上限

        # 已有持仓则不加仓
        if n_total > 0:
            return

        # 生成信号
        signal = strategy.on_tick()
        if not signal:
            return

        logger.info(f"[{strategy.name}] 收到信号: {signal}")

        # 双倍首单
        if signal == "信号: BUY":
            self._execute_buy(strategy)
            if strategy.double_first:
                self._execute_buy(strategy)
        elif signal == "信号: SELL":
            self._execute_sell(strategy)
            if strategy.double_first:
                self._execute_sell(strategy)

    def _execute_buy(self, strategy):
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        if hasattr(strategy, 'get_dynamic_sl_tp'):
            sl, tp = strategy.get_dynamic_sl_tp(OrderType.BUY, ask)
        else:
            sl = ask - settings.STOP_LOSS_PIPS * 0.01
            tp = ask + settings.TAKE_PROFIT_PIPS * 0.01

        ticket = self.bridge.open_order(
            symbol=settings.SYMBOL,
            order_type=OrderType.BUY,
            volume=settings.LOT_SIZE,
            price=ask,
            sl=sl,
            tp=tp,
            comment=strategy.name,
            magic=strategy.magic,
        )
        if ticket:
            logger.info(f"[{strategy.name}] 开多仓 Magic={strategy.magic} "
                        f"{settings.LOT_SIZE}手 @ {ask:.2f} SL={sl:.2f} TP={tp:.2f} Ticket={ticket}")

    def _execute_sell(self, strategy):
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        if hasattr(strategy, 'get_dynamic_sl_tp'):
            sl, tp = strategy.get_dynamic_sl_tp(OrderType.SELL, bid)
        else:
            sl = bid + settings.STOP_LOSS_PIPS * 0.01
            tp = bid - settings.TAKE_PROFIT_PIPS * 0.01

        ticket = self.bridge.open_order(
            symbol=settings.SYMBOL,
            order_type=OrderType.SELL,
            volume=settings.LOT_SIZE,
            price=bid,
            sl=sl,
            tp=tp,
            comment=strategy.name,
            magic=strategy.magic,
        )
        if ticket:
            logger.info(f"[{strategy.name}] 开空仓 Magic={strategy.magic} "
                        f"{settings.LOT_SIZE}手 @ {bid:.2f} SL={sl:.2f} TP={tp:.2f} Ticket={ticket}")

    def _get_balance(self) -> float:
        info = self.bridge.get_account_info()
        return info.balance if info else 0.0

    def _check_daily_loss(self) -> bool:
        now = time.time()
        if now - self._last_balance_check < 300:
            return False
        balance = self._get_balance()
        if balance <= 0:
            return True
        loss_pct = (self._daily_start_balance - balance) / self._daily_start_balance * 100
        if loss_pct >= settings.MAX_DAILY_LOSS_PCT:
            logger.error(f"日亏损达到 {loss_pct:.2f}%，停止交易")
            return True
        self._last_balance_check = now
        return False

    def _check_news_blackout(self) -> bool:
        """检查是否在新闻禁售期，每5分钟刷新一次"""
        now = time.time()
        if now - self._last_news_check < 300:
            return False
        self._last_news_check = now

        blocked, reason = self.news_filter.is_in_blackout()
        if blocked:
            logger.info(f"[新闻过滤] 禁售时段: {reason}，跳过开仓")
            for _ in range(3):
                time.sleep(20)
                self.bridge.send_heartbeat()
            return True
        return False

    def _check_status_report(self):
        now = time.time()
        if now - self._last_report_time < self._report_interval:
            return
        self._last_report_time = now
        self._status_report()

    def _status_report(self):
        info = self.bridge.get_account_info()
        if not info:
            return

        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        all_positions = self.bridge.get_positions(settings.SYMBOL)

        # 按策略统计
        report = (
            f"\n{'='*50}\n"
            f"  XAUUSD 多策略状态  {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"{'='*50}\n"
            f"  余额:     ${info.balance:.2f}\n"
            f"  净值:     ${info.equity:.2f}\n"
            f"{'='*50}\n"
        )

        total_pnl = 0.0
        for s in self.strategies:
            my_pos = [p for p in all_positions if p.magic == s.magic]
            pnl = sum(p.profit for p in my_pos)
            total_pnl += pnl
            report += (f"  [{s.name}] Magic={s.magic} TF={s.timeframe} "
                       f"持仓={len(my_pos)} 盈亏=${pnl:.2f}\n")

        manual = [p for p in all_positions if p.magic not in
                  [s.magic for s in self.strategies]]
        manual_pnl = sum(p.profit for p in manual)
        if manual:
            report += f"  [手工单] 持仓={len(manual)} 盈亏=${manual_pnl:.2f}\n"

        report += (
            f"  ---\n"
            f"  总浮动盈亏: ${total_pnl + manual_pnl:.2f}\n"
            f"  当前价:     Bid={bid:.2f} Ask={ask:.2f}\n"
            f"{'='*50}\n"
        )
        logger.info(report)


def main():
    engine = TradingEngine()
    engine.start()


if __name__ == "__main__":
    main()
