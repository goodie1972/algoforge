"""
Multi-Confluence Quant — 14因子综合Score
============================================
来源: TradingView Multi-Confluence Quant Crypto Engine [QuantSovereign]
- 14技术指标因子, 每位+1分
- threshold: ≥10/14 = Signal, ≥11/14 = God-Tier
- 覆盖趋-trend/动量/波动/成交量/结构5大类别
data源: all指标从 DataFactory TA-Lib read
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
    """Multi-Confluence Quant — 14因子综合Score"""

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

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 200: return (None, 0, 0, [], [], {})

        closes = self.get_close_prices()
        close = closes[-1]
        atr_val = self.get_indicator("atr")
        if atr_val is None: return (None, 0, 0, [], [], {})

        ema20 = self.get_indicator("ema_21")
        ema50 = self.get_indicator("ema_50")
        ema200 = self.get_indicator("ema_200")
        rsi_val = self.get_indicator("rsi")
        macd_data = self.get_indicator("macd") or {}
        macd_val = macd_data.get("macd")
        _adx = self.get_indicator("adx")
        _pdi = self.get_indicator("pdi")
        _ndi = self.get_indicator("ndi")
        adx_data = {"adx": _adx, "pdi": _pdi, "ndi": _ndi} if _adx is not None else None
        bb = self.get_indicator("bb")
        stoch_rsi_data = self.get_indicator("stoch_rsi") or {}
        stoch_rsi = {"k": stoch_rsi_data.get("k")} if stoch_rsi_data.get("k") is not None else None

        long_score = 0; long_detail = []
        short_score = 0; short_detail = []

        # ① EMA Ribbon (20/50)
        if ema20 is not None and ema50 is not None:
            if ema20 > ema50:
                long_score += 1; long_detail.append("EMA20>50")
            else:
                short_score += 1; short_detail.append("EMA20<50")

        # ② 长期趋-trend (200EMA)
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

        # ④ ADX趋-trendconfirm
        if adx_data and adx_data["adx"] > 20:
            long_score += 1; long_detail.append("ADX>20")
            # 同时在短侧也加分（表示有趋-trend，不是震荡）
            short_score += 1; short_detail.append("ADX>20")

        # ⑤ 线性回归斜率
        slope = self.get_indicator("linear_reg_slope")
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

        # ⑦ HTF趋-trend(H1) — 从 DataFactory H1 缓存读取
        try:
            from services.data_factory import get_cache
            h1_cache = get_cache("H1") or {}
            h1_ema50 = h1_cache.get("ema_50")
            h1_candles = h1_cache.get("candles") or []
            h1_close = h1_candles[-1].close if h1_candles else None
            if h1_ema50 is not None and h1_close is not None:
                if h1_close > h1_ema50:
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

        # ⑩ 波动扩 
        atr_20 = self.get_indicator("atr_20")
        if atr_20 is not None and atr_val > atr_20 * 1.1:
            if long_score >= short_score:
                long_score += 1; long_detail.append("ATR+")
            else:
                short_score += 1; short_detail.append("ATR+")

        # ⑪ BBposition
        if bb:
            price_pos = (close - bb["lower"]) / max(bb["upper"]-bb["lower"], 0.001)
            if price_pos > 0.5:
                long_score += 1; long_detail.append(f"BB>{price_pos:.0%}")
            else:
                short_score += 1; short_detail.append(f"BB<{price_pos:.0%}")

        # ⑫ 结构突破(20 candles新高/低)
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
        signal_str = "No signal"
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
            f"[{self.name}] Score: {long_score}/{short_score}  {signal_str}  "
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
            return (0, 0)  # ATR 缺失时return (0,0) 让engine走 fallback
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

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        """defaultverify：tick 价不跑出 BB bound"""
        direction = signal.get("direction", "BUY")
        bb = latest.get("bb") or signal.get("indicator_values", {}).get("bb") or {}
        if direction == "BUY":
            if bb.get("lower") and tick_price > bb["lower"] * 1.005:
                return False
        else:
            if bb.get("upper") and tick_price < bb["upper"] * 0.995:
                return False
        return True
