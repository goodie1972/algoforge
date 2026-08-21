"""
GoodMA v1 — 60MA 方向 + 回踩入场
====================================
来源: https://github.com/Yumerain/EA-MQL4  Experts/GoodMA.mq4
核心逻辑：
- 60 SMA 方向（当前均线 > 前一根 → up）
- 多头方向价格回踩 ≤ 60SMA 开多；空头方向价格反弹 ≥ 60SMA 开空
- 方向反转 K 线平仓，其余由 BaseStrategy 统一出场（trail/hard）
"""
import logging
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 880401
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 880401, "date": "2026-08-19",
     "desc": "初始移植：Yumerain/EA-MQL4 GoodMA.mq4 60MA 方向 + 回踩入场"},
]


class GoodMAStrategy(BaseStrategy):
    """GoodMA — 60MA 方向 + 回踩入场"""

    name = "goodma"
    default_timeframe = "H1"
    TIMEFRAME = "H1"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    # ── 参数 ──
    DIR_MA_PERIOD = 60        # 方向均线周期
    ENTRY_MA_PERIOD = 60      # 入场均线周期（与方向共用）
    MIN_TREND_STRENGTH = 0.5  # 最小均线间距（美元）
    MIN_ENTRY_DISTANCE = 0.3  # 最小入场距离（美元）

    # ── 风控 ──
    FIXED_LOTS = 0.01
    MAX_SLIPPAGE = 30

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._last_direction: Optional[str] = None

    # ─────────────── 辅助 ───────────────

    def _get_sma(self, period: int) -> Optional[float]:
        key = f"sma_{period}"
        return self.get_indicator(key)

    def _get_prev_sma(self, period: int) -> Optional[float]:
        """获取前一根 SMA 值（当前 candles[-2] 的 SMA）"""
        if len(self.candles) < 3:
            return None
        # 从 DataFactory 历史缓存获取
        try:
            from services.data_factory import get_cache
            cache = get_cache(self.TIMEFRAME)
            indicator_cache = getattr(cache, "_indicator_cache", None) if cache else None
            if indicator_cache and len(indicator_cache) >= 2:
                prev = indicator_cache[-2]
                if prev and f"sma_{period}" in prev:
                    return prev[f"sma_{period}"]
        except Exception:
            pass
        # 回退：用当前 SMA 近似
        return self._get_sma(period)

    # ─────────────── 入场逻辑 ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < self.DIR_MA_PERIOD + 5:
            return None

        last_candle = candles[-1]
        price = last_candle.close

        # 获取 60 SMA
        ma_dir = self._get_sma(self.DIR_MA_PERIOD)
        if ma_dir is None or ma_dir <= 0:
            return None

        # 判断方向：当前 SMA > 前一根 → UP
        ma_prev = self._get_prev_sma(self.DIR_MA_PERIOD)
        if ma_prev is None or ma_prev <= 0:
            return None

        direction = "UP" if ma_dir > ma_prev else "DOWN"
        self._last_direction = direction

        gap = abs(ma_dir - ma_prev)
        logger.info(f"[{self.name}] SMA{self.DIR_MA_PERIOD}={ma_dir:.2f} 前SMA={ma_prev:.2f} 方向={direction} 间距={gap:.2f}")

        # 趋势强度不足
        if gap < self.MIN_TREND_STRENGTH:
            logger.info(f"[{self.name}] 趋势强度不足，跳过")
            return None

        if direction == "UP":
            # 多头：价格回踩 ≤ 60SMA 时入场
            if price <= ma_dir and price >= ma_dir - self.MIN_ENTRY_DISTANCE:
                logger.info(f"[{self.name}] 信号做多: 价格 {price:.2f} 回踩 SMA{ma_dir:.2f}")
                return (OrderType.BUY, 1, 0, ["GOODMA-LONG"], [], {})
            else:
                logger.debug(f"[{self.name}] 多头方向等待回踩: 价格 {price:.2f} > SMA {ma_dir:.2f}")
        else:
            # 空头：价格反弹 ≥ 60SMA 时入场
            if price >= ma_dir and price <= ma_dir + self.MIN_ENTRY_DISTANCE:
                logger.info(f"[{self.name}] 信号做空: 价格 {price:.2f} 反弹 SMA{ma_dir:.2f}")
                return (OrderType.SELL, 0, 1, [], ["GOODMA-SHORT"], {})
            else:
                logger.debug(f"[{self.name}] 空头方向等待反弹: 价格 {price:.2f} < SMA {ma_dir:.2f}")

        return None

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: str, entry_price: float, atr_val: float,
                          position_type: str = "entry") -> tuple[float, float]:
        """ATR 倍数止损止盈"""
        if atr_val <= 0:
            atr_val = 10.0
        # 原版：SL=200 点 (20美元), TP=500 点 (50美元)
        # 用 ATR 版本替代
        stop_dist = max(atr_val * 2.0, 15.0)
        take_dist = max(atr_val * 3.5, 35.0)
        if direction == "BUY":
            return entry_price - stop_dist, entry_price + take_dist
        else:
            return entry_price + stop_dist, entry_price - take_dist

    # ─────────────── 出场逻辑 ───────────────

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """由引擎依据固定 SL/TP 处理出场"""
        return False

    def mark_extreme_entry(self, ticket: int | str):
        pass