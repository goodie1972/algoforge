"""
TradingEngine 线程封装 - 在后台 daemon 线程中运行原始引擎
"""

import logging
import os
import sys
import threading
import time
from datetime import datetime
from typing import Optional

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
from core.bridge import create_bridge, MT4BridgeBase, Position, AccountInfo, Candle, OrderType
from config import settings


class EngineRunner:
    """在后台线程中运行 TradingEngine，暴露状态供 API 查询"""

    def __init__(self, config_service=None):
        self.config_service = config_service
        self.bridge: Optional[MT4BridgeBase] = None
        self.engine_thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_requested = False
        self._start_time: Optional[datetime] = None

        # 运行时参数（从 config_service 或 settings 默认值加载）
        self._lot_size = settings.LOT_SIZE
        self._sl_pips = settings.STOP_LOSS_PIPS
        self._tp_pips = settings.TAKE_PROFIT_PIPS
        self._max_positions = settings.MAX_POSITIONS

        self.logger = logging.getLogger("engine_runner")
        self._strategy = None

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
        # 等待引擎启动完成（连接 MT4）
        time.sleep(2)
        return True

    def stop(self):
        """请求引擎停止"""
        self._stop_requested = True
        if self.engine_thread and self.engine_thread.is_alive():
            self.engine_thread.join(timeout=10)

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
        """后台线程入口 - 连接 MT4 并进入交易循环"""
        self.logger.info("=" * 60)
        self.logger.info("XAUUSD Web Dashboard - 启动交易引擎")
        self.logger.info(f"策略: {settings.STRATEGY}")
        self.logger.info(f"品种: {settings.SYMBOL} | 手数: {self._lot_size} | 周期: {settings.TIMEFRAME}")
        self.logger.info("=" * 60)

        # 1. 连接 MT4
        self.bridge = create_bridge()
        if not self.bridge.connect():
            self.logger.error("无法连接 MT4，请确认 MT4 终端已运行且 EA 已加载")
            self._running = False
            return

        # 2. 初始化策略
        self._init_strategy()
        if not self._strategy:
            self.logger.error("策略初始化失败")
            self.bridge.disconnect()
            return

        # 3. 接管现有持仓
        existing = self.bridge.takeover_existing_positions(settings.SYMBOL)
        self._start_time = datetime.now()
        self._running = True
        self.logger.info("进入主循环...")

        # 3. 主循环
        while not self._stop_requested:
            try:
                self._tick()
            except Exception as e:
                self.logger.exception(f"主循环异常: {e}")
                time.sleep(60)

        # 4. 清理
        if self.bridge:
            self.bridge.disconnect()
        self._running = False
        self.logger.info("交易引擎已停止")

    def _tick(self):
        """单次循环 - 精简版，主要关注交易信号"""
        # 同步运行时配置
        self._sync_config()

        # 检查持仓数上限
        positions = self.bridge.get_positions(settings.SYMBOL)
        my_positions = [p for p in positions if p.magic == settings.MAGIC_NUMBER]

        if len(my_positions) >= self._max_positions:
            self.logger.info(f"达到最大持仓数 {self._max_positions}，跳过信号")
            self._idle_sleep()
            return

        # 获取策略信号
        signal = self._get_signal()
        if not signal:
            self._idle_sleep()
            return

        self.logger.info(f"收到信号: {signal}")

        # 执行信号
        if signal == OrderType.BUY:
            self._execute_buy()
        elif signal == OrderType.SELL:
            self._execute_sell()

    def _sync_config(self):
        """从配置服务同步运行时参数"""
        if not self.config_service:
            return
        params = self.config_service.get_engine_params()
        self._lot_size = params.get("lot_size", settings.LOT_SIZE)
        self._sl_pips = params.get("stop_loss_pips", settings.STOP_LOSS_PIPS)
        self._tp_pips = params.get("take_profit_pips", settings.TAKE_PROFIT_PIPS)
        self._max_positions = params.get("max_positions", settings.MAX_POSITIONS)
        self._sync_strategy_params()

    def _idle_sleep(self):
        """空闲等待（每 20 秒发心跳）"""
        for _ in range(3):
            if self._stop_requested:
                return
            time.sleep(20)
            try:
                if self.bridge:
                    self.bridge.send_heartbeat()
            except Exception:
                pass

    def _init_strategy(self):
        """初始化并持久化策略实例"""
        from strategies.double_ma import DoubleMAStrategy
        from strategies.atr_breakout import ATRBreakoutStrategy
        from strategies.combined import CombinedStrategy
        from strategies.rsi_bollinger import RSIBollingerStrategy
        from strategies.stoch_bollinger import StochBollingerStrategy

        strategy_map = {
            "double_ma": DoubleMAStrategy,
            "atr_breakout": ATRBreakoutStrategy,
            "combined": CombinedStrategy,
            "rsi_bollinger": RSIBollingerStrategy,
            "stoch_bollinger": StochBollingerStrategy,
        }
        cls = strategy_map.get(settings.STRATEGY)
        self._strategy = cls(self.bridge) if cls else None

        if self._strategy:
            self._sync_strategy_params()

    def _sync_strategy_params(self):
        """同步运行时配置到策略"""
        if not self.config_service or not self._strategy:
            return
        sp = self.config_service.get_strategy_params()
        for k, v in sp.items():
            if hasattr(self._strategy, k):
                setattr(self._strategy, k, v)

    def _get_signal(self) -> Optional[OrderType]:
        """获取当前策略信号"""
        if not self._strategy:
            return None
        self._sync_strategy_params()
        self._strategy.refresh_data()
        if len(self._strategy.candles) < 10:
            return None
        return self._strategy.generate_signal()

    def _execute_buy(self):
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        if hasattr(self._strategy, 'get_dynamic_sl_tp'):
            sl, tp = self._strategy.get_dynamic_sl_tp(OrderType.BUY, ask)
        else:
            sl = ask - self._sl_pips * 0.01
            tp = ask + self._tp_pips * 0.01
        ticket = self.bridge.open_order(
            symbol=settings.SYMBOL,
            order_type=OrderType.BUY,
            volume=self._lot_size,
            price=ask,
            sl=sl,
            tp=tp,
            comment=settings.STRATEGY,
        )
        if ticket:
            self.logger.info(f"开多仓: {settings.SYMBOL} {self._lot_size}手 @ {ask} "
                            f"SL={sl} TP={tp} Ticket={ticket}")

    def _execute_sell(self):
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        if hasattr(self._strategy, 'get_dynamic_sl_tp'):
            sl, tp = self._strategy.get_dynamic_sl_tp(OrderType.SELL, bid)
        else:
            sl = bid + self._sl_pips * 0.01
            tp = bid - self._tp_pips * 0.01
        ticket = self.bridge.open_order(
            symbol=settings.SYMBOL,
            order_type=OrderType.SELL,
            volume=self._lot_size,
            price=bid,
            sl=sl,
            tp=tp,
            comment=settings.STRATEGY,
        )
        if ticket:
            self.logger.info(f"开空仓: {settings.SYMBOL} {self._lot_size}手 @ {bid} "
                            f"SL={sl} TP={tp} Ticket={ticket}")
