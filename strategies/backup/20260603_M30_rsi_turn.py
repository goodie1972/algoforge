"""
M30 RSI 掉头策略 — 只看 M30 RSI 方向，掉头入场/反向掉头出场
- 入场：前 2 根 M30 K 线 RSI 比方向
- 出场：RSI 反向掉头，同时开反向单（引擎自动在下一 tick 开仓）
- 最多 1 单
"""

import logging
from typing import Optional

import config.settings as _settings
from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class RSITurnM30Strategy(BaseStrategy):
    """M30 RSI 掉头策略"""

    name = "M30_rsi_turn"

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self.rsi_period = _settings.RSI_PERIOD

    def reload_config(self):
        self.rsi_period = _settings.RSI_PERIOD
        logger.info(f"[{self.name}] 配置已热重载")

    def _calc_rsi(self, closes: list[float]) -> Optional[float]:
        if len(closes) < self.rsi_period + 1:
            return None
        gains, losses = [], []
        for i in range(-self.rsi_period, 0):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _get_rsi_turn(self) -> Optional[str]:
        """最后 2 根完成的 M30 K 线 RSI 方向: up / down / flat"""
        closes = self.get_close_prices()
        if len(closes) < self.rsi_period + 3:
            return None
        # closes[-1] = 当前 forming K 线，closes[-2] = 上一根完成 K 线
        rsi_prev = self._calc_rsi(closes[:-2])  # 前前根完成 K 线的 RSI
        rsi_curr = self._calc_rsi(closes[:-1])  # 上一根完成 K 线的 RSI
        if rsi_prev is None or rsi_curr is None:
            return None
        if rsi_prev < rsi_curr:
            return "up"
        elif rsi_prev > rsi_curr:
            return "down"
        return "flat"

    def generate_signal(self) -> Optional[OrderType]:
        rsi_turn = self._get_rsi_turn()
        if rsi_turn == "up":
            logger.info(f"[{self.name}] RSI 掉头向上 BUY")
            return OrderType.BUY
        elif rsi_turn == "down":
            logger.info(f"[{self.name}] RSI 掉头向下 SELL")
            return OrderType.SELL
        return None

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """RSI 反向掉头出场"""
        is_buy = position.order_type in ("OP_BUY", "BUY")
        rsi_turn = self._get_rsi_turn()
        if rsi_turn is None:
            return False
        if is_buy and rsi_turn == "down":
            logger.info(f"[{self.name}] RSI 掉头向下平多 ticket={position.ticket}")
            return True
        if not is_buy and rsi_turn == "up":
            logger.info(f"[{self.name}] RSI 掉头向上平空 ticket={position.ticket}")
            return True
        return False

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple:
        """使用引擎默认止损止盈"""
        return None, None
