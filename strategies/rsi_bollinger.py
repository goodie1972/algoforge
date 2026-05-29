"""
RSI + 布林带均值回归策略 + EMA20 跟踪止损
- 入场：价格触轨 + RSI 超卖/超买确认
- 止损：BB 0.35 带宽初始止损 + EMA20 跟踪止损
- TP：由 EMA20 跟踪止损控制出场
"""

import logging
import math
from typing import Optional

from config.settings import (
    BB_PERIOD, BB_STD, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
)
import config.settings as _settings
from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class RSIBollingerStrategy(BaseStrategy):
    """RSI + 布林带均值回归 + EMA20 跟踪止损"""

    name = "rsi_bollinger"

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._load_settings()

    def _load_settings(self):
        self.bb_period = _settings.BB_PERIOD
        self.bb_std = _settings.BB_STD
        self.rsi_period = _settings.RSI_PERIOD
        self.rsi_oversold = _settings.RSI_OVERSOLD
        self.rsi_overbought = _settings.RSI_OVERBOUGHT

    def reload_config(self):
        self._load_settings()
        logger.info(f"[{self.name}] 配置已热重载")

    def _calc_ema(self, period: int) -> Optional[float]:
        closes = self.get_close_prices()
        if len(closes) < period:
            return None
        k = 2.0 / (period + 1)
        ema = closes[0]
        for p in closes[1:]:
            ema = (p - ema) * k + ema
        return ema

    def _calc_rsi(self, period: int) -> Optional[float]:
        closes = self.get_close_prices()
        if len(closes) < period + 1:
            return None
        gains, losses = [], []
        for i in range(-period, 0):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _calc_bb_bandwidth(self) -> Optional[float]:
        closes = self.get_close_prices()
        if len(closes) < self.bb_period:
            return None
        recent = closes[-self.bb_period:]
        sma = sum(recent) / self.bb_period
        variance = sum((c - sma) ** 2 for c in recent) / self.bb_period
        std = math.sqrt(variance)
        return std * self.bb_std

    def _calc_sma(self, period: int) -> Optional[float]:
        closes = self.get_close_prices()
        if len(closes) < period:
            return None
        return sum(closes[-period:]) / period

    def _calc_stddev(self, period: int, mean: float) -> Optional[float]:
        closes = self.get_close_prices()
        if len(closes) < period:
            return None
        variance = sum((c - mean) ** 2 for c in closes[-period:]) / period
        return math.sqrt(variance)

    def generate_signal(self) -> Optional[OrderType]:
        closes = self.get_close_prices()
        if len(closes) < max(self.bb_period, self.rsi_period) + 10:
            return None

        # 布林带
        sma = self._calc_sma(self.bb_period)
        if sma is None:
            return None
        std = self._calc_stddev(self.bb_period, sma)
        if std is None:
            return None

        upper = sma + self.bb_std * std
        lower = sma - self.bb_std * std
        current_close = closes[-1]

        # RSI
        rsi = self._calc_rsi(self.rsi_period)
        if rsi is None:
            return None

        if current_close <= lower and rsi < self.rsi_oversold:
            logger.info(
                f"[{self.name}] 超卖反弹 BUY: 价格={current_close:.2f} "
                f"下轨={lower:.2f} RSI={rsi:.1f} "
                f"上轨={upper:.2f}"
            )
            return OrderType.BUY

        if current_close >= upper and rsi > self.rsi_overbought:
            logger.info(
                f"[{self.name}] 超买回调 SELL: 价格={current_close:.2f} "
                f"上轨={upper:.2f} RSI={rsi:.1f} "
                f"下轨={lower:.2f}"
            )
            return OrderType.SELL

        logger.info(
            f"[{self.name}] 无信号: 价格={current_close:.2f} "
            f"上轨={upper:.2f} 下轨={lower:.2f} RSI={rsi:.1f}"
        )
        return None

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """初始 SL = BB 带宽 × 0.35；TP 设极远值由 EMA20 跟踪止损出场"""
        bandwidth = self._calc_bb_bandwidth()
        if bandwidth is None or bandwidth <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        dist = bandwidth * 0.35
        if direction == OrderType.BUY:
            sl = round(entry_price - dist, 2)
            tp = round(entry_price + dist * 100, 2)
        else:
            sl = round(entry_price + dist, 2)
            tp = round(entry_price - dist * 100, 2)
        return sl, tp

    def get_ema20_trail(self, direction: OrderType) -> Optional[float]:
        ema = self._calc_ema(20)
        if ema is None:
            return None
        return round(ema, 2)

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        trail = self.get_ema20_trail(position.order_type)
        if trail is None:
            return False

        is_buy = position.order_type in ("OP_BUY", "BUY")
        if is_buy:
            if bid <= trail:
                logger.info(
                    f"[{self.name}] EMA20跟踪止损 BUY ticket={position.ticket} "
                    f"Bid={bid:.2f} EMA20={trail:.2f}"
                )
                return True
        else:
            if ask >= trail:
                logger.info(
                    f"[{self.name}] EMA20跟踪止损 SELL ticket={position.ticket} "
                    f"Ask={ask:.2f} EMA20={trail:.2f}"
                )
                return True
        return False
