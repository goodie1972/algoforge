"""
Entry Score PRO — 5因子加权评分 + 结构/临近/动量/波动
========================================================
来源: TradingView No-Repaint Entry Score Multi-Factor Confluence [LunqFX]
- 5因子加权: 结构(30%), 临近(25%), 动量(15%), 波动(10%), 趋势(20%)
- 评分0-100, 阈值≥75触发
- STRONG(≥85) / PRIME(≥80) / SUSTAINED(≥80连续3根) / ENTRY WINDOW(≥75)
- SL=入场区±0.55ATR, TP=下一摆动点
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 661501
STRATEGY_LEGACY_MAGICS: list[int] = []


class EntryScoreProStrategy(BaseStrategy):
    """Entry Score PRO — 5因子加权评分"""

    name = "entry_score_pro"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None

        # 权重
        self.w_structure = 30
        self.w_proximity = 25
        self.w_momentum = 15
        self.w_volatility = 10
        self.w_trend = 20

        self.score_entry = 75     # ENTRY WINDOW
        self.score_prime = 80     # PRIME
        self._prime_bars = 0       # 连续PRIME计数

        self.rsi_period = 14
        self.atr_period = 14

        # Exit params
        self.sl_atr = 0.55    # ±0.55ATR
        self.trail_atr = 1.5

    def get_adx_data(self) -> Optional[dict]:
        _adx = self.get_indicator("adx")
        _pdi = self.get_indicator("pdi")
        _ndi = self.get_indicator("ndi")
        if _adx is not None:
            return {"adx": _adx, "pdi": _pdi, "ndi": _ndi}
        return None

    # ─────────────── Indicator helpers ───────────────

    def _calc_ema(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period: return None
        k = 2.0 / (period + 1)
        ema = closes[0]
        for p in closes[1:]:
            ema = (p - ema) * k + ema
        return ema

    def _calc_atr(self, period: int = 14, offset: int = 0) -> Optional[float]:
        """标准 Wilder ATR（带 offset 偏移，供波动因子计算历史 ATR 使用）"""
        sub = self.candles[:-offset] if offset > 0 else self.candles
        return self.calc_atr_wilder(sub, period)

    def _find_swing(self, lookback: int = 10) -> Optional[dict]:
        """找最近摆动高点和低点"""
        candles = self.candles
        if len(candles) < lookback * 2 + 1: return None
        highs = [c.high for c in candles[-(lookback*2+1):]]
        lows = [c.low for c in candles[-(lookback*2+1):]]
        mid = lookback
        swing_high = None
        swing_low = None
        if highs[mid] == max(highs):
            swing_high = highs[mid]
        if lows[mid] == min(lows):
            swing_low = lows[mid]
        return {"high": swing_high, "low": swing_low}

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 60: return None

        closes = self.get_close_prices()
        close = closes[-1]
        atr_val = self.get_indicator("atr")
        if atr_val is None: return None

        # ── 计算5因子(每项0-100) ──

        # ① 结构(30%): HTF EMA排列 × K线方向
        ema50 = self._calc_ema(closes, 50)
        ema200 = self._calc_ema(closes, 200) if len(closes) >= 200 else None
        struct_long = 50
        struct_short = 50
        if ema50 is not None:
            if close > ema50:
                struct_long += 25
            else:
                struct_short += 25
        # 趋势强度
        _adx = self.get_indicator("adx")
        _pdi = self.get_indicator("pdi")
        _ndi = self.get_indicator("ndi")
        adx_data = {"adx": _adx, "pdi": _pdi, "ndi": _ndi} if _adx is not None else None
        if adx_data and adx_data["adx"] > 25:
            if adx_data["pdi"] > adx_data["ndi"]:
                struct_long += 25
            else:
                struct_short += 25

        # ② 临近(25%): 距最近摆动点的ATR距离
        swing = self._find_swing()
        prox_long = 50
        prox_short = 50
        if swing and swing["high"] and swing["low"]:
            dist_to_high = (swing["high"] - close) / atr_val if atr_val > 0 else 99
            dist_to_low = (close - swing["low"]) / atr_val if atr_val > 0 else 99
            # 距支撑近 → 做多信号强
            if dist_to_low < 1.0:
                prox_long = 80
            elif dist_to_low < 2.0:
                prox_long = 65
            if dist_to_high < 1.0:
                prox_short = 80
            elif dist_to_high < 2.0:
                prox_short = 65

        # ③ 动量(15%): 实体/范围比
        candle_range = candles[-1].high - candles[-1].low
        body = abs(candles[-1].close - candles[-1].open)
        body_ratio = body / candle_range if candle_range > 0 else 0.5
        mom_long = 50 + body_ratio * 50 if candles[-1].close > candles[-1].open else 50 - body_ratio * 50

        # ④ 波动(10%): 当前ATR vs 30根前ATR，适中波动利于入场（方向无关质量分）
        atr_now = self.get_indicator("atr")
        atr_old = self._calc_atr(period=14, offset=30) if len(closes) >= 50 else None
        vol_score = 50  # 数据不足时中性
        if atr_now and atr_old and atr_old > 0:
            ratio = atr_now / atr_old
            if 0.8 <= ratio <= 1.3:      # 健康波动
                vol_score = 70
            elif ratio > 1.6 or ratio < 0.5:  # 混乱或死寂
                vol_score = 30

        # ⑤ 趋势(20%): MA14 + RSI
        ma14 = sum(closes[-14:]) / 14 if len(closes) >= 14 else close
        trend_long = 50
        trend_short = 50
        if close > ma14:
            trend_long += 30
        else:
            trend_short += 30
        rsi_val = self.get_indicator("rsi")
        if rsi_val is not None:
            if rsi_val > 50:
                trend_long += 20
            else:
                trend_short += 20

        # ── 综合评分(加权) ──
        total_w = self.w_structure + self.w_proximity + self.w_momentum + self.w_volatility + self.w_trend
        score_long = int((
            struct_long * self.w_structure +
            prox_long * self.w_proximity +
            mom_long * self.w_momentum +
            vol_score * self.w_volatility +
            trend_long * self.w_trend
        ) / total_w)
        score_short = int((
            struct_short * self.w_structure +
            prox_short * self.w_proximity +
            (100 - mom_long) * self.w_momentum +
            vol_score * self.w_volatility +
            trend_short * self.w_trend
        ) / total_w)

        long_detail = []
        short_detail = []

        # ── 等级判定 ──
        signal = None
        signal_str = "无信号"
        if score_long >= self.score_prime:
            long_detail.append(f"PRIME({score_long})")
        elif score_long >= self.score_entry:
            long_detail.append(f"ENTRY({score_long})")

        if score_short >= self.score_prime:
            short_detail.append(f"PRIME({score_short})")
        elif score_short >= self.score_entry:
            short_detail.append(f"ENTRY({score_short})")

        if score_long >= self.score_entry and score_long > score_short:
            signal = OrderType.BUY
            signal_str = "LONG"
        elif score_short >= self.score_entry and score_short > score_long:
            signal = OrderType.SELL
            signal_str = "SELL"

        detail_parts = []
        if long_detail: detail_parts.append("LONG: " + " ".join(long_detail))
        if short_detail: detail_parts.append("SHORT: " + " ".join(short_detail))
        logger.info(
            f"[{self.name}] 评分: {score_long}/{score_short}  {signal_str}  "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )

        indicator_values = {
            "close": round(close, 2),
            "atr": round(atr_val, 2),
            "rsi": round(rsi_val, 1) if rsi_val is not None else 0,
            "struct": struct_long, "prox": prox_long,
            "momentum": round(mom_long, 1),
            "trend": trend_long,
            "score_long": score_long, "score_short": score_short,
        }
        return (signal, score_long, score_short, long_detail, short_detail, indicator_values)

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """SL=±0.55ATR, TP=下一摆动点"""
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return None
        sl_dist = atr_val * self.sl_atr
        # TP设为3×SL (默认R:R)
        tp_dist = sl_dist * 3
        if direction == OrderType.BUY:
            return round(entry_price - sl_dist, 2), round(entry_price + tp_dist, 2)
        else:
            return round(entry_price + sl_dist, 2), round(entry_price - tp_dist, 2)

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """移动追踪止损"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
            }

        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return False

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            drawdown = td["highest"] - bid
            if drawdown > atr_val * self.trail_atr:
                self._last_exit_detail = {"exit_type": "trail_stop", "drawdown": round(drawdown, 2)}
                del self._trail_data[ticket]
                return True
            loss = td["entry"] - bid
            if loss > atr_val * self.sl_atr:
                self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss, 2)}
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            rally = ask - td["lowest"]
            if rally > atr_val * self.trail_atr:
                self._last_exit_detail = {"exit_type": "trail_stop", "rally": round(rally, 2)}
                del self._trail_data[ticket]
                return True
            loss = ask - td["entry"]
            if loss > atr_val * self.sl_atr:
                self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss, 2)}
                del self._trail_data[ticket]
                return True

        self._last_exit_detail = None
        return False
