"""
KISS v1 — H4 MACD 定向 + H1 均线组 + 枢轴支阻
===============================================
来源: https://github.com/Yumerain/EA-MQL4  Indicators/KISS.mq4
核心逻辑：
- H4 MACD(12,26,9) 主线>信号 → 多头；主线<信号 → 空头
- H1 均线组 37/60 SMA 确认方向一致性
- 多头趋势价格回踩 H1 60SMA 进多；空头趋势反弹 H1 60SMA 进空
- 日线枢轴（PP/S1/R1）作为阻力参考，不直接拦截
"""
import logging
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 880501
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 880501, "date": "2026-08-19",
     "desc": "初始移植：Yumerain/EA-MQL4 KISS.mq4 H4 MACD + H1 MA 组 + 枢轴支阻"},
]


class KISSStrategy(BaseStrategy):
    """KISS — H4 MACD 定向 + H1 均线组 + 枢轴支阻"""

    name = "kiss"
    default_timeframe = "H1"
    TIMEFRAME = "H1"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    # ── H4 MACD 参数 ──
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9

    # ── H1 均线组 ──
    MA_FAST = 37
    MA_SLOW = 60

    # ── 入场 ──
    ENTRY_MA_PERIOD = 60    # 回踩均线
    MIN_ENTRY_DISTANCE = 0.3  # 最小入场距离（美元）
    MIN_MA_GAP = 0.3        # 最小均线间距（美元）

    # ── 风控 ──
    FIXED_LOTS = 0.01
    MAX_SLIPPAGE = 30

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._last_trend: Optional[str] = None

    # ─────────────── 辅助 ───────────────

    def _get_sma(self, period: int) -> Optional[float]:
        key = f"sma_{period}"
        return self.get_indicator(key)

    def _get_macd_h4(self) -> tuple[Optional[float], Optional[float]]:
        """获取 H4 级别 MACD"""
        try:
            from services.data_factory import get_cache
            h4 = get_cache("H4")
            if h4 and "macd" in h4:
                macd = h4["macd"]
                return macd.get("macd"), macd.get("signal")
        except Exception:
            pass
        return None, None

    def _get_h4_sma(self, period: int) -> Optional[float]:
        """获取 H4 级别 SMA 值"""
        try:
            from services.data_factory import get_cache
            h4 = get_cache("H4")
            if h4:
                key = f"sma_{period}"
                if key in h4:
                    return h4[key]
        except Exception:
            pass
        return None

    def _get_daily_pivot(self) -> dict:
        """从 H4 数据估计日线枢轴（最近 24h 近似）"""
        try:
            from services.data_factory import get_cache
            h4 = get_cache("H4")
            candles = h4.get("candles", []) if h4 else []
            if len(candles) >= 6:
                recent = candles[-6:]
                high = max(c.high for c in recent)
                low = min(c.low for c in recent)
                close = recent[-1].close
                pp = (high + low + close) / 3
                r1 = 2 * pp - low
                s1 = 2 * pp - high
                return {"pp": pp, "r1": r1, "s1": s1, "high": high, "low": low}
        except Exception:
            pass
        return {"pp": 0, "r1": 0, "s1": 0, "high": 0, "low": 0}

    # ─────────────── 趋势判断 ───────────────

    def _check_trend(self) -> Optional[str]:
        """H4 MACD 定方向 + H1 均线组确认"""
        # H4 MACD
        macd_val, macd_sig = self._get_macd_h4()
        if macd_val is None or macd_sig is None:
            logger.debug(f"[{self.name}] H4 MACD 不可用")
            return None

        h4_trend = "UP" if macd_val > macd_sig else "DOWN"
        logger.info(f"[{self.name}] H4 MACD: {macd_val:.2f} / {macd_sig:.2f} → {h4_trend}")

        # H1 均线组确认
        ma_fast = self._get_sma(self.MA_FAST)
        ma_slow = self._get_sma(self.MA_SLOW)
        if ma_fast is None or ma_slow is None or ma_fast <= 0 or ma_slow <= 0:
            logger.debug(f"[{self.name}] H1 均线组不可用")
            return h4_trend  # 仅用 H4 MACD

        ma_gap = abs(ma_fast - ma_slow)
        h1_trend = "UP" if ma_fast > ma_slow else "DOWN"

        logger.info(f"[{self.name}] H1 SMA{self.MA_FAST}={ma_fast:.2f} SMA{self.MA_SLOW}={ma_slow:.2f} → {h1_trend}")

        # H4 与 H1 方向一致才确认趋势
        if h4_trend == h1_trend and ma_gap >= self.MIN_MA_GAP:
            return h4_trend
        elif h4_trend != h1_trend:
            logger.info(f"[{self.name}] H4({h4_trend}) vs H1({h1_trend}) 方向不一致，保持中性")
            return "NEUTRAL"
        else:
            # 方向一致但间距不足
            logger.info(f"[{self.name}] 均线间距 {ma_gap:.2f} 不足，跳过")
            return "NEUTRAL"

    # ─────────────── 入场逻辑 ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < self.MA_SLOW + 5:
            return None

        # 趋势判断
        trend = self._check_trend()
        if trend is None or trend == "NEUTRAL":
            return None

        last_candle = candles[-1]
        price = last_candle.close

        # 获取入场均线
        ma_entry = self._get_sma(self.ENTRY_MA_PERIOD)
        if ma_entry is None or ma_entry <= 0:
            return None

        # 获取枢轴参考
        pivot = self._get_daily_pivot()
        logger.info(f"[{self.name}] 枢轴: PP={pivot['pp']:.2f} R1={pivot['r1']:.2f} S1={pivot['s1']:.2f}")

        if trend == "UP":
            # 多头：价格回踩 ≤ 60SMA 入场
            if price <= ma_entry and price >= ma_entry - self.MIN_ENTRY_DISTANCE:
                detail = f"KISS-LONG {price:.2f} SMA60={ma_entry:.2f} PP={pivot['pp']:.2f}"
                logger.info(f"[{self.name}] 信号做多: {detail}")
                return (OrderType.BUY, 1, 0, [detail], [], {})
            else:
                logger.debug(f"[{self.name}] 多头等待回踩: 价格 {price:.2f} > SMA60 {ma_entry:.2f}")
        else:
            # 空头：价格反弹 ≥ 60SMA 入场
            if price >= ma_entry and price <= ma_entry + self.MIN_ENTRY_DISTANCE:
                detail = f"KISS-SHORT {price:.2f} SMA60={ma_entry:.2f} PP={pivot['pp']:.2f}"
                logger.info(f"[{self.name}] 信号做空: {detail}")
                return (OrderType.SELL, 0, 1, [], [detail], {})
            else:
                logger.debug(f"[{self.name}] 空头等待反弹: 价格 {price:.2f} < SMA60 {ma_entry:.2f}")

        return None

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: str, entry_price: float, atr_val: float,
                          position_type: str = "entry") -> tuple[float, float]:
        """ATR 倍数止损止盈"""
        if atr_val <= 0:
            atr_val = 10.0
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