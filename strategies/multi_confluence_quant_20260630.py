"""
Multi-Confluence Quant — 14因子综合评分
============================================
来源: TradingView Multi-Confluence Quant Crypto Engine [QuantSovereign]
- 14个技术指标因子, 每位+1分
- 阈值: ≥10/14 = 信号, ≥11/14 = God-Tier
- 覆盖趋势/动量/波动/成交量/结构5大类别
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 661601
STRATEGY_LEGACY_MAGICS: list[int] = []


class MultiConfluenceQuantStrategy(BaseStrategy):
    """Multi-Confluence Quant — 14因子综合评分"""

    name = "multi_confluence_quant"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None

        self.score_threshold = 10
        self.god_threshold = 11
        self.rsi_period = 14
        self.ema_fast = 20
        self.ema_slow = 50
        self.ema_long = 200
        self.atr_period = 14

        # Exit
        self.sl_atr = 2.0
        self.tp1_atr = 2.0
        self.tp2_atr = 4.0
        self.trail_atr = 1.5

    def get_adx_data(self) -> Optional[dict]:
        _adx = self.get_indicator("adx")
        _pdi = self.get_indicator("pdi")
        _ndi = self.get_indicator("ndi")
        if _adx is not None:
            return {"adx": _adx, "pdi": _pdi, "ndi": _ndi}
        return None

    def _calc_ema(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period: return None
        k = 2.0 / (period + 1)
        ema = closes[0]
        for p in closes[1:]:
            ema = (p - ema) * k + ema
        return ema

    def _calc_rsi(self, closes: list[float], period: int = 14) -> Optional[float]:
        if len(closes) < period + 1: return None
        gains, losses = [], []
        for i in range(1, period + 1):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        for i in range(period + 1, len(closes)):
            diff = closes[i] - closes[i - 1]
            gain = max(diff, 0)
            loss = max(-diff, 0)
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0: return 100.0
        return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    def _calc_macd(self, closes: list[float]) -> Optional[float]:
        ema12 = self._calc_ema(closes, 12)
        ema26 = self._calc_ema(closes, 26)
        if ema12 is None or ema26 is None: return None
        return ema12 - ema26

    def _calc_stoch_rsi(self, closes: list[float]) -> Optional[dict]:
        """简化版 Stochastic RSI"""
        rsi_vals = []
        for i in range(len(closes) - 13, len(closes) + 1):
            if i >= 14:
                r = self._calc_rsi(closes[:i])
                if r is not None:
                    rsi_vals.append(r)
        if len(rsi_vals) < 14: return None
        recent = rsi_vals[-14:]
        k = (recent[-1] - min(recent)) / max(max(recent) - min(recent), 0.001) * 100
        return {"k": k}

    def _calc_linear_reg_slope(self, closes: list[float], period: int = 20) -> Optional[float]:
        if len(closes) < period: return None
        y = closes[-period:]
        x = list(range(period))
        n = period
        sx = sum(x); sy = sum(y)
        sxy = sum(x[i]*y[i] for i in range(n))
        sx2 = sum(xi**2 for xi in x)
        slope = (n * sxy - sx * sy) / (n * sx2 - sx * sx) if (n * sx2 - sx * sx) != 0 else 0
        return slope

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 200: return None

        closes = self.get_close_prices()
        close = closes[-1]
        atr_val = self.get_indicator("atr")
        if atr_val is None: return None

        ema20 = self._calc_ema(closes, 20)
        ema50 = self._calc_ema(closes, 50)
        ema200 = self._calc_ema(closes, 200) if len(closes) >= 200 else None
        rsi_val = self.get_indicator("rsi")
        macd_val = self._calc_macd(closes)
        _adx = self.get_indicator("adx")
        _pdi = self.get_indicator("pdi")
        _ndi = self.get_indicator("ndi")
        adx_data = {"adx": _adx, "pdi": _pdi, "ndi": _ndi} if _adx is not None else None
        bb = self.get_indicator("bb")
        stoch_rsi = self._calc_stoch_rsi(closes)

        long_score = 0; long_detail = []
        short_score = 0; short_detail = []

        # ① EMA Ribbon (20/50)
        if ema20 is not None and ema50 is not None:
            if ema20 > ema50:
                long_score += 1; long_detail.append("EMA20>50")
            else:
                short_score += 1; short_detail.append("EMA20<50")

        # ② 长期趋势 (200EMA)
        if ema200 is not None:
            if close > ema200:
                long_score += 1; long_detail.append("EMA200+")
            else:
                short_score += 1; short_detail.append("EMA200-")

        # ③ RSI方向
        if rsi_val is not None:
            if rsi_val > 50:
                long_score += 1; long_detail.append(f"RSI>{rsi_val:.0f}")
            else:
                short_score += 1; short_detail.append(f"RSI<{rsi_val:.0f}")

        # ④ ADX趋势确认
        if adx_data and adx_data["adx"] > 20:
            long_score += 1; long_detail.append("ADX>20")
            # 同时在短侧也加分（表示有趋势，不是震荡）
            short_score += 1; short_detail.append("ADX>20")

        # ⑤ 线性回归斜率
        slope = self._calc_linear_reg_slope(closes)
        if slope is not None:
            if slope > 0:
                long_score += 1; long_detail.append("SLOPE+")
            else:
                short_score += 1; short_detail.append("SLOPE-")

        # ⑥ 成交量
        if len(candles) >= 21:
            avg_vol = sum(c.volume for c in candles[-21:-1]) / 20
            if candles[-1].volume > avg_vol:
                if candles[-1].close > candles[-1].open:
                    long_score += 1; long_detail.append("VOL+")
                else:
                    short_score += 1; short_detail.append("VOL+")

        # ⑦ HTF趋势(H1)
        try:
            h1_raw = self.bridge.get_candles(self.symbol, "H1", 100)
            h1_candles = list(reversed(h1_raw))
            h1_closes = [c.close for c in h1_candles]
            h1_ema50 = self._calc_ema(h1_closes, 50)
            if h1_ema50 is not None:
                if h1_closes[-1] > h1_ema50:
                    long_score += 1; long_detail.append("H1-UP")
                else:
                    short_score += 1; short_detail.append("H1-DN")
        except Exception:
            pass

        # ⑧ Stoch RSI
        if stoch_rsi is not None:
            if stoch_rsi["k"] > 50:
                long_score += 1; long_detail.append(f"SK>{stoch_rsi['k']:.0f}")
            else:
                short_score += 1; short_detail.append(f"SK<{stoch_rsi['k']:.0f}")

        # ⑨ MACD
        if macd_val is not None:
            if macd_val > 0:
                long_score += 1; long_detail.append("MACD+")
            else:
                short_score += 1; short_detail.append("MACD-")

        # ⑩ 波动扩张
        atr_20 = self.get_indicator("atr_20")
        if atr_20 is not None and atr_val > atr_20 * 1.1:
            if long_score >= short_score:
                long_score += 1; long_detail.append("ATR+")
            else:
                short_score += 1; short_detail.append("ATR+")

        # ⑪ BB位置
        if bb:
            price_pos = (close - bb["lower"]) / max(bb["upper"]-bb["lower"], 0.001)
            if price_pos > 0.5:
                long_score += 1; long_detail.append(f"BB>{price_pos:.0%}")
            else:
                short_score += 1; short_detail.append(f"BB<{price_pos:.0%}")

        # ⑫ 结构突破(20根新高/低)
        lookback = min(20, len(closes)-1)
        if close == max(closes[-lookback:]):
            long_score += 1; long_detail.append("HH20")
        elif close == min(closes[-lookback:]):
            short_score += 1; short_detail.append("LL20")

        # ⑬ DI方向
        if adx_data:
            if adx_data["pdi"] > adx_data["ndi"]:
                long_score += 1; long_detail.append("DI+")
            else:
                short_score += 1; short_detail.append("DI-")

        # ⑭ RSI过度延伸(Z-score简化)
        if rsi_val is not None:
            if rsi_val < 30:
                short_score -= 1  # 超卖→不空
                short_detail.append("RSI-OS")
            elif rsi_val > 70:
                long_score -= 1   # 超买→不多
                long_detail.append("RSI-OB")

        # ── 决策 ──
        signal = None
        signal_str = "无信号"
        grade = ""
        if long_score >= self.god_threshold:
            grade = "GOD-TIER"
        elif long_score >= self.score_threshold:
            grade = "SIGNAL"

        if long_score >= self.score_threshold and long_score > short_score:
            signal = OrderType.BUY
            signal_str = f"LONG [{grade}]" if grade else "LONG"
        elif short_score >= self.score_threshold and short_score > long_score:
            signal = OrderType.SELL
            signal_str = f"SELL [{grade}]" if grade else "SELL"

        detail_parts = []
        if long_detail: detail_parts.append("LONG: " + " ".join(long_detail))
        if short_detail: detail_parts.append("SHORT: " + " ".join(short_detail))
        logger.info(
            f"[{self.name}] 评分: {long_score}/{short_score}  {signal_str}  "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )

        indicator_values = {
            "close": round(close, 2), "atr": round(atr_val, 2),
            "rsi": round(rsi_val, 1) if rsi_val is not None else 0,
            "adx": round(adx_data["adx"], 1) if adx_data else 0,
            "ema20": round(ema20, 2) if ema20 else 0,
            "ema50": round(ema50, 2) if ema50 else 0,
            "long_score": long_score, "short_score": short_score,
        }
        return (signal, long_score, short_score, long_detail, short_detail, indicator_values)

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return None
        sl_dist = atr_val * self.sl_atr
        tp_dist = atr_val * self.tp1_atr
        if direction == OrderType.BUY:
            return round(entry_price - sl_dist, 2), round(entry_price + tp_dist, 2)
        else:
            return round(entry_price + sl_dist, 2), round(entry_price - tp_dist, 2)

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")
        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
                "peak_profit": 0.0,
            }
        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return False

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            profit = bid - td["entry"]
            td["peak_profit"] = max(td["peak_profit"], profit)
            # Profit drawdown
            if td["peak_profit"] > atr_val * 0.5:
                ratio = profit / td["peak_profit"]
                if ratio < 0.75:
                    self._last_exit_detail = {"exit_type": "profit_drawdown", "profit": round(profit, 2)}
                    del self._trail_data[ticket]; return True
            drawdown = td["highest"] - bid
            if drawdown > atr_val * self.trail_atr:
                self._last_exit_detail = {"exit_type": "trail_stop", "drawdown": round(drawdown, 2)}
                del self._trail_data[ticket]; return True
            loss = td["entry"] - bid
            if loss > atr_val * self.sl_atr:
                self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss, 2)}
                del self._trail_data[ticket]; return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            profit = td["entry"] - ask
            td["peak_profit"] = max(td["peak_profit"], profit)
            if td["peak_profit"] > atr_val * 0.5:
                ratio = profit / td["peak_profit"]
                if ratio < 0.75:
                    self._last_exit_detail = {"exit_type": "profit_drawdown", "profit": round(profit, 2)}
                    del self._trail_data[ticket]; return True
            rally = ask - td["lowest"]
            if rally > atr_val * self.trail_atr:
                self._last_exit_detail = {"exit_type": "trail_stop", "rally": round(rally, 2)}
                del self._trail_data[ticket]; return True
            loss = ask - td["entry"]
            if loss > atr_val * self.sl_atr:
                self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss, 2)}
                del self._trail_data[ticket]; return True
        self._last_exit_detail = None
        return False
