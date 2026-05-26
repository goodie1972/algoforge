"""
实盘交易主循环
"""

import logging
import time
import sys
from datetime import datetime

from config import settings
from core.bridge import create_bridge, OrderType
from strategies.double_ma import DoubleMAStrategy
from strategies.atr_breakout import ATRBreakoutStrategy

STRATEGY_MAP = {
    "double_ma": DoubleMAStrategy,
    "atr_breakout": ATRBreakoutStrategy,
}


def create_strategy(name: str, bridge):
    """策略工厂"""
    cls = STRATEGY_MAP.get(name)
    if cls is None:
        raise ValueError(f"未知策略: {name}. 可选: {list(STRATEGY_MAP.keys())}")
    return cls(bridge)

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


class TradingEngine:
    """交易引擎 - 核心循环"""

    def __init__(self):
        self.bridge = create_bridge()
        self.strategy = create_strategy(settings.STRATEGY, self.bridge)
        self.running = False
        self._last_balance_check = 0
        self._daily_start_balance = 0.0

    def start(self):
        """启动交易引擎"""
        logger.info("=" * 60)
        logger.info("XAUUSD 量化交易系统 启动")
        logger.info(f"策略: {self.strategy.name}")
        logger.info(f"品种: {settings.SYMBOL} | 手数: {settings.LOT_SIZE} | 周期: {settings.TIMEFRAME}")
        if hasattr(self.strategy, 'ma_fast_period'):
            logger.info(f"快线: MA{self.strategy.ma_fast_period} | 慢线: MA{self.strategy.ma_slow_period}")
        if hasattr(self.strategy, 'breakout_period'):
            logger.info(f"突破周期: {self.strategy.breakout_period} | ATR 周期: {self.strategy.atr_period}")
        logger.info("=" * 60)

        # 1. 连接 MT4
        if not self.bridge.connect():
            logger.error("无法连接 MT4，请确认:")
            logger.error("  1. MT4 终端已运行")
            logger.error("  2. PyTrader EA 已加载到图表")
            logger.error("  3. EA 监听的端口与配置一致")
            return

        # 2. 接管现有持仓
        existing = self.bridge.takeover_existing_positions(settings.SYMBOL)
        self._daily_start_balance = self._get_balance()

        self.running = True
        logger.info("进入主循环...")

        # 3. 主循环
        while self.running:
            try:
                self._tick()
            except KeyboardInterrupt:
                logger.info("收到中断信号，停止交易")
                self.running = False
            except Exception as e:
                logger.exception(f"主循环异常: {e}")
                time.sleep(60)  # 异常后等待1分钟再重试

        self.bridge.disconnect()
        logger.info("交易引擎已停止")

    def _tick(self):
        """单次循环"""
        # 风控：检查日亏损
        if self._check_daily_loss():
            time.sleep(60)
            return

        # 检查持仓数上限
        positions = self.bridge.get_positions(settings.SYMBOL)
        position_info = self.strategy.filter_positions(positions)
        logger.debug(f"当前持仓: {position_info['total']} (多:{len(position_info['longs'])} 空:{len(position_info['shorts'])})")

        if position_info["total"] >= settings.MAX_POSITIONS:
            logger.info(f"达到最大持仓数 {settings.MAX_POSITIONS}，跳过信号")
            time.sleep(60)
            return

        # 生成信号
        signal = self.strategy.on_tick()
        if not signal:
            time.sleep(60)
            return

        logger.info(f"收到信号: {signal}")

        # 执行信号
        if signal == "信号: BUY":
            self._execute_buy(positions)
        elif signal == "信号: SELL":
            self._execute_sell(positions)

    def _execute_buy(self, positions):
        """执行买入"""
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        # 使用策略的动态止损止盈（如果有）
        if hasattr(self.strategy, 'get_dynamic_sl_tp'):
            sl, tp = self.strategy.get_dynamic_sl_tp(OrderType.BUY, ask)
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
            comment=self.strategy.name,
        )
        if ticket:
            logger.info(f"开多仓: {settings.SYMBOL} {settings.LOT_SIZE}手 @ {ask} "
                        f"SL={sl} TP={tp} Ticket={ticket}")

    def _execute_sell(self, positions):
        """执行卖出"""
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        if hasattr(self.strategy, 'get_dynamic_sl_tp'):
            sl, tp = self.strategy.get_dynamic_sl_tp(OrderType.SELL, bid)
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
            comment=self.strategy.name,
        )
        if ticket:
            logger.info(f"开空仓: {settings.SYMBOL} {settings.LOT_SIZE}手 @ {bid} "
                        f"SL={sl} TP={tp} Ticket={ticket}")

    def _get_balance(self) -> float:
        info = self.bridge.get_account_info()
        return info.balance if info else 0.0

    def _check_daily_loss(self) -> bool:
        """日亏损检查"""
        now = time.time()
        if now - self._last_balance_check < 300:  # 每5分钟检查一次
            return False

        balance = self._get_balance()
        if balance <= 0:
            return True

        loss_pct = (self._daily_start_balance - balance) / self._daily_start_balance * 100
        if loss_pct >= settings.MAX_DAILY_LOSS_PCT:
            logger.error(
                f"日亏损达到 {loss_pct:.2f}% (上限 {settings.MAX_DAILY_LOSS_PCT}%)，"
                f"停止交易直到明天"
            )
            return True

        self._last_balance_check = now
        return False


def main():
    engine = TradingEngine()
    engine.start()


if __name__ == "__main__":
    main()
