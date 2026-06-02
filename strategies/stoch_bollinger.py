"""
Stoch + 布林带均值回归策略
- 入场：Stoch 超卖区金叉/超买区死叉
- 止损：BB 0.35 带宽初始止损 + EMA20 跟踪止损
- TP：由 EMA20 跟踪止损控制出场
"""

import logging
import math
from typing import Optional

from config.settings import (
    BB_PERIOD, BB_STD, STOCH_K, STOCH_SLOWING, STOCH_D,
    STOCH_OVERSOLD, STOCH_OVERBOUGHT,
)
import config.settings as _settings
from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class StochBollingerStrategy(BaseStrategy):
    """Stoch + 布林带均值回归 + EMA20 跟踪止损"""

    name = "stoch_bollinger"

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._load_settings()
        self._prev_k: Optional[float] = None
        self._prev_d: Optional[float] = None
        self._in_extreme_entry: set[int] = set()  # 从极端区入场的 ticket 集合
        self._mark_next: int = 0  # 待标记为极端区入场的开仓计数（支持双单）

    def _load_settings(self):
        self.bb_period = _settings.BB_PERIOD
        self.bb_std = _settings.BB_STD
        self.stoch_k = _settings.STOCH_K
        self.stoch_slowing = _settings.STOCH_SLOWING
        self.stoch_d = _settings.STOCH_D
        self.oversold = _settings.STOCH_OVERSOLD
        self.overbought = _settings.STOCH_OVERBOUGHT
        self.extreme_oversold = _settings.STOCH_EXTREME_OVERSOLD
        self.extreme_overbought = _settings.STOCH_EXTREME_OVERBOUGHT

    def reload_config(self):
        self._load_settings()
        logger.info(f"[{self.name}] 配置已热重载")

    def mark_extreme_entry(self, ticket: int):
        """标记该持仓从极端区入场，供出场保护使用（支持双单）"""
        if self._mark_next > 0:
            self._in_extreme_entry.add(ticket)
            self._mark_next -= 1

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

    def _calc_stoch(self) -> Optional[dict]:
        candles = self.candles
        n = len(candles)
        min_needed = self.stoch_k + self.stoch_slowing + self.stoch_d + 1
        if n < min_needed:
            return None
        raw_k = []
        for i in range(self.stoch_k - 1, n):
            window = candles[i - self.stoch_k + 1: i + 1]
            highest = max(c.high for c in window)
            lowest = min(c.low for c in window)
            close = window[-1].close
            if highest == lowest:
                raw_k.append(50.0)
            else:
                raw_k.append((close - lowest) / (highest - lowest) * 100)
        if len(raw_k) < self.stoch_slowing + self.stoch_d + 1:
            return None
        smooth_k = []
        for i in range(self.stoch_slowing - 1, len(raw_k)):
            val = sum(raw_k[i - self.stoch_slowing + 1: i + 1]) / self.stoch_slowing
            smooth_k.append(val)
        if len(smooth_k) < self.stoch_d + 1:
            return None
        curr_k = smooth_k[-1]
        prev_k = smooth_k[-2]
        curr_d = sum(smooth_k[-self.stoch_d:]) / self.stoch_d
        prev_d = sum(smooth_k[-(self.stoch_d + 1):-1]) / self.stoch_d
        return {"prev_k": prev_k, "curr_k": curr_k, "prev_d": prev_d, "curr_d": curr_d}

    def _calc_bb_bandwidth(self) -> Optional[float]:
        closes = self.get_close_prices()
        if len(closes) < self.bb_period:
            return None
        recent = closes[-self.bb_period:]
        sma = sum(recent) / self.bb_period
        variance = sum((c - sma) ** 2 for c in recent) / self.bb_period
        std = math.sqrt(variance)
        return std * self.bb_std

    def generate_signal(self) -> Optional[OrderType]:
        closes = self.get_close_prices()
        if len(closes) < self.bb_period + 10:
            return None
        current_close = closes[-1]

        stoch = self._calc_stoch()
        if stoch is None:
            return None
        curr_k, curr_d = stoch["curr_k"], stoch["curr_d"]

        golden_cross = False
        death_cross = False
        if self._prev_k is not None and self._prev_d is not None:
            golden_cross = self._prev_k <= self._prev_d and curr_k > curr_d
            death_cross = self._prev_k >= self._prev_d and curr_k < curr_d

        self._prev_k = curr_k
        self._prev_d = curr_d

        # BB 日志用
        sma = self._calc_ema(self.bb_period)
        bb_std = self._calc_bb_bandwidth()
        upper = sma + self.bb_std * self.bb_std if sma and bb_std else 0
        lower = sma - self.bb_std * self.bb_std if sma and bb_std else 0

        # 极端区双向保护：低位不开卖，高位不开买（使用极端区阈值）
        in_buy_extreme = curr_k < self.extreme_oversold and curr_d < self.extreme_oversold
        in_sell_extreme = curr_k > self.extreme_overbought and curr_d > self.extreme_overbought

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

        if golden_cross and curr_k < self.oversold:
            if in_sell_extreme:
                logger.info(
                    f"[{self.name}] 高位极端区跳过金叉 BUY: K={curr_k:.1f} D={curr_d:.1f}"
                )
                return None
            if ema_trend != "up":
                logger.info(
                    f"[{self.name}] EMA20趋势过滤金叉 BUY: 价格={current_close:.2f} "
                    f"K={curr_k:.1f} D={curr_d:.1f} EMA趋势={ema_trend}"
                )
                return None
            self._mark_next += 1
            logger.info(
                f"[{self.name}] 超卖金叉 BUY: 价格={current_close:.2f} "
                f"K={curr_k:.1f} D={curr_d:.1f} "
                f"上轨={upper:.2f} 下轨={lower:.2f} EMA趋势={ema_trend}"
            )
            return OrderType.BUY

        if death_cross and curr_k > self.overbought:
            if in_buy_extreme:
                logger.info(
                    f"[{self.name}] 低位极端区跳过死叉 SELL: K={curr_k:.1f} D={curr_d:.1f}"
                )
                return None
            if ema_trend != "down":
                logger.info(
                    f"[{self.name}] EMA20趋势过滤死叉 SELL: 价格={current_close:.2f} "
                    f"K={curr_k:.1f} D={curr_d:.1f} EMA趋势={ema_trend}"
                )
                return None
            self._mark_next += 1
            logger.info(
                f"[{self.name}] 超买死叉 SELL: 价格={current_close:.2f} "
                f"K={curr_k:.1f} D={curr_d:.1f} "
                f"上轨={upper:.2f} 下轨={lower:.2f} EMA趋势={ema_trend}"
            )
            return OrderType.SELL

        logger.info(
            f"[{self.name}] 无信号: 价格={current_close:.2f} "
            f"上轨={upper:.2f} 下轨={lower:.2f} "
            f"K={curr_k:.1f} D={curr_d:.1f} EMA趋势={ema_trend} "
            f"{'金叉' if golden_cross else '死叉' if death_cross else ''}"
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
            tp = round(entry_price + dist * 100, 2)  # 极远值
        else:
            sl = round(entry_price + dist, 2)
            tp = round(entry_price - dist * 100, 2)
        return sl, tp

    def get_ema20_trail(self, direction: OrderType) -> Optional[float]:
        """返回 EMA20 跟踪止损价位"""
        ema = self._calc_ema(20)
        if ema is None:
            return None
        return round(ema, 2)

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """EMA20 渐进式追踪止损 + 极端区出场保护
        - EMA20 只在有利方向移动时才更新追踪止损位，不后退
        - 从极端区入场的持仓，K/D 都在极端区时不被短期波动振走"""
        ema20 = self.get_ema20_trail(position.order_type)
        if ema20 is None:
            return False

        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        # === 极端区出场保护 ===
        if ticket in self._in_extreme_entry:
            stoch = self._calc_stoch()
            if stoch:
                in_oversold = stoch["curr_k"] < self.extreme_oversold and stoch["curr_d"] < self.extreme_oversold
                in_overbought = stoch["curr_k"] > self.extreme_overbought and stoch["curr_d"] > self.extreme_overbought
                if (is_buy and in_oversold) or (not is_buy and in_overbought):
                    return False  # K/D 还在极端区，不出场
                # 已走出极端区，恢复正常 EMA20 追踪
                self._in_extreme_entry.discard(ticket)

        if ticket not in self._trail_sl:
            self._trail_sl[ticket] = position.stop_loss

        if is_buy:
            # 只在 EMA20 上移且高于当前追踪止损时才更新，且不能高于当前 Bid（否则立即触发）
            if ema20 > self._trail_sl[ticket] and ema20 < bid:
                self._trail_sl[ticket] = ema20
            if bid <= self._trail_sl[ticket]:
                logger.info(
                    f"[{self.name}] EMA20跟踪止损 BUY ticket={ticket} "
                    f"Bid={bid:.2f} TrailSL={self._trail_sl[ticket]:.2f} EMA20={ema20:.2f}"
                )
                del self._trail_sl[ticket]
                return True
        else:
            # 只在 EMA20 下移且低于当前追踪止损时才更新，且不能低于当前 Ask（否则立即触发）
            if ema20 < self._trail_sl[ticket] and ema20 > ask:
                self._trail_sl[ticket] = ema20
            if ask >= self._trail_sl[ticket]:
                logger.info(
                    f"[{self.name}] EMA20跟踪止损 SELL ticket={ticket} "
                    f"Ask={ask:.2f} TrailSL={self._trail_sl[ticket]:.2f} EMA20={ema20:.2f}"
                )
                del self._trail_sl[ticket]
                return True
        return False
