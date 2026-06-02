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
    BB_PERIOD, BB_STD, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT, SYMBOL,
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

    def _calc_ema(self, period: int, shift: int = 0) -> Optional[float]:
        closes = self.get_close_prices()
        needed = period + shift
        if len(closes) < needed:
            return None
        if shift:
            closes = closes[:-shift]
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

    def _calc_m30_rsi(self, closes_slice) -> Optional[float]:
        """计算一组收盘价的 RSI 值"""
        if len(closes_slice) < self.rsi_period + 1:
            return None
        gains, losses = [], []
        for i in range(-self.rsi_period, 0):
            diff = closes_slice[i] - closes_slice[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / self.rsi_period
        avg_loss = sum(losses) / self.rsi_period
        if avg_loss == 0:
            return 100.0
        return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    def _calc_m30_rsi_direction(self) -> Optional[str]:
        """入场方向判断：取最近 3 根 M30 的 RSI，连续递增→up，连续递减→down"""
        raw = self.bridge.get_candles(self.symbol, "M30", self.rsi_period + 10)
        if not raw or len(raw) < self.rsi_period + 4:
            return None
        candles = list(reversed(raw))
        closes = [c.close for c in candles]

        rsi_oldest = self._calc_m30_rsi(closes[:-2])  # 前前一根
        rsi_mid = self._calc_m30_rsi(closes[:-1])     # 前一根
        rsi_newest = self._calc_m30_rsi(closes)       # 当前一根

        if rsi_oldest is None or rsi_mid is None or rsi_newest is None:
            return None

        if rsi_oldest < rsi_mid < rsi_newest:
            return "up"
        elif rsi_oldest > rsi_mid > rsi_newest:
            return "down"
        return "flat"

    def _calc_m30_rsi_exit(self) -> Optional[str]:
        """出场方向判断：取最近 2 根 M30 的 RSI，上升→up，下降→down"""
        raw = self.bridge.get_candles(self.symbol, "M30", self.rsi_period + 10)
        if not raw or len(raw) < self.rsi_period + 3:
            return None
        candles = list(reversed(raw))
        closes = [c.close for c in candles]

        rsi_prev = self._calc_m30_rsi(closes[:-1])  # 前一根 M30
        rsi_curr = self._calc_m30_rsi(closes)       # 当前一根 M30

        if rsi_prev is None or rsi_curr is None:
            return None

        if rsi_prev < rsi_curr:
            return "up"
        elif rsi_prev > rsi_curr:
            return "down"
        return "flat"

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

        # H1 RSI
        rsi = self._calc_rsi(self.rsi_period)
        if rsi is None:
            return None

        # M30 RSI 方向
        m30_rsi_dir = self._calc_m30_rsi_direction()

        # EMA20 趋势方向过滤
        ema20 = self._calc_ema(20)
        ema20_2 = self._calc_ema(20, shift=2)
        ema_trend = None
        if ema20 is not None and ema20_2 is not None:
            if ema20 > ema20_2:
                ema_trend = "up"
            elif ema20 < ema20_2:
                ema_trend = "down"
            else:
                ema_trend = "flat"

        if current_close <= lower and rsi < self.rsi_oversold:
            # if ema_trend != "up":
            #     logger.info(
            #         f"[{self.name}] EMA20趋势过滤 BUY: 价格={current_close:.2f} "
            #         f"下轨={lower:.2f} RSI={rsi:.1f} EMA趋势={ema_trend}"
            #     )
            #     return None
            if m30_rsi_dir != "up":
                logger.info(
                    f"[{self.name}] M30 RSI方向过滤 BUY: 价格={current_close:.2f} "
                    f"下轨={lower:.2f} RSI={rsi:.1f} M30 RSI方向={m30_rsi_dir}"
                )
                return None
            logger.info(
                f"[{self.name}] 超卖反弹 BUY: 价格={current_close:.2f} "
                f"下轨={lower:.2f} RSI={rsi:.1f} "
                f"上轨={upper:.2f} EMA趋势={ema_trend} M30 RSI方向={m30_rsi_dir}"
            )
            return OrderType.BUY

        if current_close >= upper and rsi > self.rsi_overbought:
            # if ema_trend != "down":
            #     logger.info(
            #         f"[{self.name}] EMA20趋势过滤 SELL: 价格={current_close:.2f} "
            #         f"上轨={upper:.2f} RSI={rsi:.1f} EMA趋势={ema_trend}"
            #     )
            #     return None
            if m30_rsi_dir != "down":
                logger.info(
                    f"[{self.name}] M30 RSI方向过滤 SELL: 价格={current_close:.2f} "
                    f"上轨={upper:.2f} RSI={rsi:.1f} M30 RSI方向={m30_rsi_dir}"
                )
                return None
            logger.info(
                f"[{self.name}] 超买回调 SELL: 价格={current_close:.2f} "
                f"上轨={upper:.2f} RSI={rsi:.1f} "
                f"下轨={lower:.2f} EMA趋势={ema_trend} M30 RSI方向={m30_rsi_dir}"
            )
            return OrderType.SELL

        logger.info(
            f"[{self.name}] 无信号: 价格={current_close:.2f} "
            f"上轨={upper:.2f} 下轨={lower:.2f} RSI={rsi:.1f} "
            f"EMA趋势={ema_trend} M30 RSI方向={m30_rsi_dir}"
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

    # def get_ema20_trail(self, direction: OrderType) -> Optional[float]:
    #     ema = self._calc_ema(20)
    #     if ema is None:
    #         return None
    #     return round(ema, 2)

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """M30 RSI 反转出场 — 替代原 EMA20 跟踪止损
        多空逻辑对称：连续 2 根 M30 RSI 反向即出场"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        m30_exit = self._calc_m30_rsi_exit()
        if m30_exit is None:
            return False

        if is_buy:
            # BUY 入场后，最近 2 根 M30 RSI 连续下降 → 反转出场
            if m30_exit == "down":
                logger.info(
                    f"[{self.name}] M30 RSI反转出场 BUY ticket={ticket} "
                    f"M30 RSI出场方向={m30_exit}"
                )
                return True
        else:
            # SELL 入场后，最近 2 根 M30 RSI 连续上升 → 反转出场
            if m30_exit == "up":
                logger.info(
                    f"[{self.name}] M30 RSI反转出场 SELL ticket={ticket} "
                    f"M30 RSI出场方向={m30_exit}"
                )
                return True
        return False
