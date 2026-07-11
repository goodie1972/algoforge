"""
SanQing EA v1 原始版 — H1 纯原版
================================
- 6因子评分 + 固定阈值 5
- ATR动态追踪止损 trail=4.0 hard=2.5
- 无任何后加特性（无利润回撤止盈、无保本出场、无门禁、无新闻过滤）
"""
import logging
import math
import time
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1_original"
STRATEGY_MAGIC = 880101
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 880101, "date": "2026-06-08", "desc": "初始上线：6因子评分≥5，ATR跟踪止损 trail=4.0 hard=2.5"},
    {"version": "v1_original", "magic": 880101, "date": "2026-07-11", "desc": "恢复原始v1代码，无任何后期修改，纯净运行"},
]

class SanQingEA_v1(BaseStrategy):
    """SanQing EA 原始v1版本 — 不做任何修改"""

    name = "sanqing_h1_v1"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None

        # 原始v1参数
        self.score_threshold = 5
        self.p_trailing_atr = 4.0
        self.p_hard_atr = 2.5
        self.adx_threshold = 20  # 仅用于评分提示，不做动态阈值调整

    def get_adx_data(self) -> Optional[dict]:
        """供引擎门禁使用"""
        return {
            "adx": self.get_indicator("adx"),
            "pdi": self.get_indicator("pdi"),
            "ndi": self.get_indicator("ndi"),
        }

    def generate_signal(self) -> Optional[OrderType]:
        candles = self.candles
        if len(candles) < 50:
            return None

        closes = self.get_close_prices()
        close = closes[-1]

        bb = self.get_indicator("bb")
        rsi_val = self.get_indicator("rsi")
        atr_val = self.get_indicator("atr_20")
        adx = self.get_indicator("adx")
        if any(x is None for x in (bb, rsi_val, atr_val, adx)):
            return None

        sma14 = self.get_indicator("sma_14")
        ema9 = self.get_indicator("ema_9")
        ema21 = self.get_indicator("ema_21")
        vol_sma = self.get_indicator("volume_sma_20")
        volume = candles[-1].volume if candles else 0

        # 6因子评分
        long_score = 0
        short_score = 0
        long_factors: list[str] = []
        short_factors: list[str] = []

        # 因子1: EMA趋势
        if ema9 and ema21 and ema9 > ema21:
            long_score += 1
            long_factors.append("EMA9>21")
        if ema9 and ema21 and ema9 < ema21:
            short_score += 1
            short_factors.append("EMA9<21")

        # 因子2: BB触碰
        if bb and close <= bb["lower"]:
            long_score += 1
            long_factors.append("BB-BOT")
        if bb and close >= bb["upper"]:
            short_score += 1
            short_factors.append("BB-TOP")

        # 因子3: RSI超买超卖
        if rsi_val <= 30:
            long_score += 1
            long_factors.append(f"RSI-{int(rsi_val)}")
        elif rsi_val >= 70:
            short_score += 1
            short_factors.append(f"RSI-{int(rsi_val)}")

        # 因子4: RSI背离/动量
        if rsi_val <= 50:
            long_score += 1
            long_factors.append(f"RSI<50({int(rsi_val)})")
        else:
            short_score += 1
            short_factors.append(f"RSI>{int(rsi_val)}")

        # 因子5: ATR波动率（高波动时倾向顺势）
        if atr_val and sma14 and close:
            atr_pct = atr_val / close * 100
            if atr_pct > 0.3:
                if close > sma14:
                    long_score += 1
                    long_factors.append("VOL-HIGH")
                else:
                    short_score += 1
                    short_factors.append("VOL-HIGH")

        # 因子6: 成交量放量
        if vol_sma and volume > vol_sma * 1.3:
            if close > (closes[-2] if len(closes) > 1 else close):
                long_score += 1
                long_factors.append("VOL-UP")
            else:
                short_score += 1
                short_factors.append("VOL-DN")

        signal = None
        signal_str = "无信号"
        if long_score >= self.score_threshold:
            signal = OrderType.BUY
            signal_str = "LONG"
        elif short_score >= self.score_threshold:
            signal = OrderType.SELL
            signal_str = "SELL"

        detail = []
        if long_factors: detail.append("LONG: " + " ".join(long_factors))
        if short_factors: detail.append("SHORT: " + " ".join(short_factors))

        logger.info(
            f"[{self.name}] 评分: {long_score}/{short_score}  {signal_str}  "
            f"明细: {' | '.join(detail) if detail else '无'}"
        )

        indicator_values = {
            "close": round(close, 2),
            "rsi": round(rsi_val, 2),
            "atr": round(atr_val, 2),
            "bb_upper": round(bb["upper"], 2) if bb else 0,
            "bb_lower": round(bb["lower"], 2) if bb else 0,
            "bb_mid": round(bb["mid"], 2) if bb else 0,
            "adx": round(adx, 2) if adx else 0,
        }

        return (signal, long_score, short_score, long_factors, short_factors, indicator_values)

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        dist = atr_val * self.p_hard_atr
        if direction == OrderType.BUY:
            sl = round(entry_price - dist, 2)
            tp = round(entry_price + dist * 50, 2)
        else:
            sl = round(entry_price + dist, 2)
            tp = round(entry_price - dist * 50, 2)
        return sl, tp

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """原始v1退出逻辑：纯ATR追踪止盈 + 硬止损，无任何附加"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")
        current_price = bid if is_buy else ask

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "entry": position.open_price,
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
            }

        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return False

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            loss = td["entry"] - bid
            drawdown = td["highest"] - bid
            if drawdown > atr_val * self.p_trailing_atr:
                logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} drawdown={drawdown:.2f}")
                del self._trail_data[ticket]
                return True
            if loss > atr_val * self.p_hard_atr:
                logger.info(f"[{self.name}] BUY HardStop ticket={ticket} loss={loss:.2f}")
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            loss = ask - td["entry"]
            rally = ask - td["lowest"]
            if rally > atr_val * self.p_trailing_atr:
                logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} rally={rally:.2f}")
                del self._trail_data[ticket]
                return True
            if loss > atr_val * self.p_hard_atr:
                logger.info(f"[{self.name}] SELL HardStop ticket={ticket} loss={loss:.2f}")
                del self._trail_data[ticket]
                return True

        return False

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        """简单验证：tick价格在BB范围内即可"""
        direction = signal.get("direction", "BUY")
        bb = latest.get("bb") or {}
        if direction == "BUY":
            if bb.get("lower") and tick_price > bb["lower"] * 1.01:
                return False
        else:
            if bb.get("upper") and tick_price < bb["upper"] * 0.99:
                return False
        return True
