"""
M30 volatility均值回归strategy — v1.0
Entry: 价格触及布林带上lower band + ATR扩 confirm + RSI背离
出场: 回归 轨take profit + ATR动态止损 + 有限 recovery
data源: all指标从 DataFactory TA-Lib read
"""
import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1.0"
STRATEGY_MAGIC = 880302
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1.0", "magic": 880302, "date": "2026-08-01",
     "desc": "M30volatility均值回归: BB触及+ATR扩 +RSI背离;  轨take profit+ATR止损+有限recovery"},
]


class M30VolReturnStrategy(BaseStrategy):
    """M30 volatility均值回归strategy"""

    name = "m30_vol_return"
    display = "M30 volatility均值回归 — BB+ATR+RSI背离"
    MAGIC = 880302
    default_timeframe = "M30"

    def __init__(self, bridge: MT4BridgeBase, **kwargs):
        super().__init__(bridge, **kwargs)
        self.timeframe = self.timeframe or "M30"

        # Entry params
        self.atr_expansion_threshold = 1.2      # ATR 扩 x数（currentATR/均值ATR）
        self.rsi_oversold = 30                   # RSI 超卖
        self.rsi_overbought = 70                 # RSI 超买
        self.bb_deviation = 2.0                  # BB 标准差x数

        # Exit params
        self.profit_atr_mult = 1.0               # 回归 轨take profit（ATRx数）
        self.sl_atr_mult = 1.5                   # 止损 ATR x数
        self.recovery_volume_mult = 1.0          # recovery 加仓x数（=不加仓，只是重开同方向）
        self.max_recovery = 1                    # 最多 recovery 1 次

        # trailing止损
        self.p_trail_chop = 0.8
        self.p_trail_normal = 1.2
        self.p_trail_trend = 1.8

        # 状态跟踪
        self._recovery_used = {}                 # {ticket_parent: count}

    # ─────────────── Signalgenerate ───────────────

    def generate_signal(self):
        candles = self.candles
        if len(candles) < 30:
            return (None, 0, 0, [], [], {})

        close = candles[-1].close
        high = candles[-1].high
        low = candles[-1].low

        # 指标
        bb = self.get_indicator("bb")
        atr_val = self.get_indicator("atr")
        rsi = self.get_indicator("rsi")
        rsi_5 = self.get_indicator("rsi_5")
        ema_mid = self.get_indicator("ema_21")
        bb_width = self.get_indicator("bb_width")

        buy_score = 0
        sell_score = 0
        long_factors = []
        short_factors = []
        iv = {}

        # ATR 扩检测 — 使用 DataFactory 缓存的 atr_list，避免重算 talib.ATR
        atr_expanding = False
        atr_list = self.get_indicator("atr_list")
        if atr_list and len(atr_list) >= 5 and atr_val:
            atr_ma = sum(atr_list[-5:]) / min(5, len(atr_list))
            atr_expanding = atr_val > atr_ma * self.atr_expansion_threshold

        # BB 宽度扩 （volatility放大）
        bb_wide = False
        if bb_width is not None:
            bb_wide = bb_width > 8.0  # XAUUSD 黄金 BB 宽度 > 8 表示volatility大

        # ── BUY 件（均值回归做多） ──
        if bb and close <= bb["lower"] * 1.01:
            # (1) 价格触及或跌破 BB lower band
            long_factors.append("BB-LOWER-TOUCH")
            buy_score += 4

            # (2) RSI 超卖或背离
            if rsi is not None and rsi < self.rsi_oversold:
                long_factors.append(f"RSI-OVERSOLD-{rsi:.0f}")
                buy_score += 3
            elif rsi_5 is not None and rsi_5 < self.rsi_oversold:
                long_factors.append(f"RSI5-OVERSOLD-{rsi_5:.0f}")
                buy_score += 2

            # (3) ATR 扩 confirm（volatility放大说明有回归动力）
            if atr_expanding:
                long_factors.append("ATR-EXPAND")
                buy_score += 2

            # (4) BB 宽度放大（volatility大）
            if bb_wide:
                long_factors.append("BB-WIDE")
                buy_score += 1

            # (5) 价格在 EMA21 下方（乖离大）
            if ema_mid is not None and close < ema_mid:
                long_factors.append("BELOW-EMA")
                buy_score += 1

        # ── SELL 件（均值回归做空） ──
        if bb and close >= bb["upper"] * 0.99:
            # (1) 价格触及或突破 BB upper band
            short_factors.append("BB-UPPER-TOUCH")
            sell_score += 4

            # (2) RSI 超买或背离
            if rsi is not None and rsi > self.rsi_overbought:
                short_factors.append(f"RSI-OVERBOUGHT-{rsi:.0f}")
                sell_score += 3
            elif rsi_5 is not None and rsi_5 > self.rsi_overbought:
                short_factors.append(f"RSI5-OVERBOUGHT-{rsi_5:.0f}")
                sell_score += 2

            # (3) ATR 扩 confirm
            if atr_expanding:
                short_factors.append("ATR-EXPAND")
                sell_score += 2

            # (4) BB 宽度放大
            if bb_wide:
                short_factors.append("BB-WIDE")
                sell_score += 1

            # (5) 价格在 EMA21 上方（乖离大）
            if ema_mid is not None and close > ema_mid:
                short_factors.append("ABOVE-EMA")
                sell_score += 1

        # ── positionGate ──
        lookback_60 = min(60, len(candles))
        recent_high = max(c.high for c in candles[-lookback_60:])
        recent_low = min(c.low for c in candles[-lookback_60:])
        price_position = (close - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5

        threshold = 6
        if price_position < 0.10 and sell_score >= threshold:
            short_factors.append("BOTTOM-GATE")
            sell_score = 0
        elif price_position > 0.90 and buy_score >= threshold:
            long_factors.append("TOP-GATE")
            buy_score = 0

        iv = {
            "close": round(close, 2),
            "bb_upper": round(bb["upper"], 2) if bb else 0,
            "bb_mid": round(bb["mid"], 2) if bb else 0,
            "bb_lower": round(bb["lower"], 2) if bb else 0,
            "bb_width": round(bb_width, 2) if bb_width else 0,
            "atr": round(atr_val, 2) if atr_val else 0,
            "rsi": round(rsi, 1) if rsi else 0,
            "rsi_5": round(rsi_5, 1) if rsi_5 else 0,
            "atr_expanding": atr_expanding,
            "price_position": round(price_position, 3),
        }

        signal = None
        if buy_score >= threshold:
            signal = OrderType.BUY
        elif sell_score >= threshold:
            signal = OrderType.SELL
        return (signal, buy_score, sell_score, long_factors, short_factors, iv)

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr")
        bb = self.get_indicator("bb")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        is_buy = direction == OrderType.BUY
        sl_dist = atr_val * self.sl_atr_mult

        # take profit = 回归 轨（BB  轨）
        tp_price = (bb["mid"] if bb else None) if is_buy else (bb["mid"] if bb else None)
        if tp_price is None:
            ema = self.get_indicator("ema_21")
            tp_price = ema if ema else (entry_price + atr_val * self.profit_atr_mult if is_buy else entry_price - atr_val * self.profit_atr_mult)

        if is_buy:
            return round(entry_price - sl_dist, 2), round(tp_price, 2)
        else:
            return round(entry_price + sl_dist, 2), round(tp_price, 2)

    # ─────────────── 出场 ───────────────

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        self.refresh_data()

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "entry": position.open_price,
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "peak_profit": 0.0,
                "entry_ts": time.time(),
            }

        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr")
        bb = self.get_indicator("bb")
        if atr_val is None or atr_val <= 0:
            return False

        pnl_pts = (bid - td["entry"]) if is_buy else (td["entry"] - ask)
        loss_pts = (td["entry"] - bid) if is_buy else (ask - td["entry"])

        if is_buy:
            td["highest"] = max(td["highest"], bid)
        else:
            td["lowest"] = min(td["lowest"], ask)

        # (1) 硬止损
        if loss_pts > atr_val * self.sl_atr_mult:
            logger.info(f"[{self.name}] HardStop ticket={ticket} loss={loss_pts:.2f}")
            del self._trail_data[ticket]
            return True

        # (2) 回归 轨take profit
        if bb:
            if is_buy and bid >= bb["mid"]:
                logger.info(f"[{self.name}] BB-Mid TP ticket={ticket}")
                del self._trail_data[ticket]
                return True
            elif not is_buy and ask <= bb["mid"]:
                logger.info(f"[{self.name}] BB-Mid TP ticket={ticket}")
                del self._trail_data[ticket]
                return True

        # (3) profitdrawdown保护
        if pnl_pts > 0:
            td["peak_profit"] = max(td["peak_profit"], pnl_pts)
            if time.time() - td["entry_ts"] > 300:
                drawdown = (td["peak_profit"] - pnl_pts) / td["peak_profit"] if td["peak_profit"] > 0 else 0
                if drawdown > 0.60:
                    logger.info(f"[{self.name}] ProfitDrawdown ticket={ticket} drawdown={drawdown:.0%}")
                    del self._trail_data[ticket]
                    return True

        # (4) trailing止损（ATR trailing）
        trail_mult = self.p_trail_normal
        if is_buy:
            trail_level = td["highest"] - atr_val * trail_mult
            if bid < trail_level:
                logger.info(f"[{self.name}] TrailStop ATR ticket={ticket}")
                del self._trail_data[ticket]
                return True
        else:
            trail_level = td["lowest"] + atr_val * trail_mult
            if ask > trail_level:
                logger.info(f"[{self.name}] TrailStop ATR ticket={ticket}")
                del self._trail_data[ticket]
                return True

        return False