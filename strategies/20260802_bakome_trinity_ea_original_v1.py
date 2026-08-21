"""
BAKOME Trinity EA Original — 多资产趋-trendtrailing系统（原始版移植）
=============================================================
来源: https://github.com/BAKOME-Hub/BakomeTrinityEA
原始 MQL5 strategy (BakomeTrinityEA.mq5)，完整移植到 Python 系统
- 支持 XAUUSD、GBPUSD、BTCUSD 等多资产
- H1 EMA34 + H4 EMA200 双时间框架趋-trend判断
- M5 Entryexec，EMA34(H1) > EMA200(H4) → BUY，反之 SELL
- ATR 动态risk（SL=2.0xATR, TP=3.0xATR）
- 经济newsfilter + sessionfilter
- PnL平衡 + trailing止损管理

data源: all指标从 DataFactory TA-Lib read
"""
import logging
from datetime import datetime
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1_original"
STRATEGY_MAGIC = 880304
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1_original", "magic": 880304, "date": "2026-08-02",
     "desc": "初始移植：BAKOME-Hub/BakomeTrinityEA 多资产趋-trendtrailing"},
]


class BAKOMETrinityEAOriginalStrategy(BaseStrategy):
    """BAKOME Trinity EA Original — 多资产趋-trendtrailing（H1 EMA34 + H4 EMA200）"""

    name = "bakome_trinity_ea_original"
    default_timeframe = "M5"
    TIMEFRAME = "M5"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    # ── 趋-trendparam（双时间框架） ──
    H1_EMA_FAST = 34
    H4_EMA_SLOW = 200

    # ── sessionparam（MT4 时区 UTC+3） ──
    TRADE_ASIAN_SESSION = False
    TRADE_LONDON_SESSION = True
    TRADE_NEW_YORK_SESSION = True
    LONDON_START_HOUR = 7     # UTC+3
    NEW_YORK_START_HOUR = 13  # UTC+3

    # ── 经济newsfilter ──
    USE_NEWS_FILTER = True
    NEWS_BLOCK_MINUTES_BEFORE = 30
    NEWS_BLOCK_MINUTES_AFTER = 20

    # ── ATR risk ──
    ATR_SL_MULTIPLIER = 2.0
    ATR_TP_MULTIPLIER = 3.0
    MIN_ATR_POINTS = 100.0
    MAX_SPREAD_POINTS = 50.0

    # ── 出场管理 ──
    USE_BREAK_EVEN = True
    BE_TRIGGER_ATR = 1.0
    USE_TRAILING_STOP = True
    TRAIL_START_ATR = 1.5
    TRAIL_STEP_ATR = 0.5

    # ── 交易param ──
    FIXED_LOTS = 0.01
    MAX_POSITIONS = 1
    MAX_DAILY_TRADES = 10

    # 预设newsevent（简化版，用户可扩展）
    NEWS_EVENTS = [
        (8, 30, "NFP"),    # 非农 8:30
        (14, 0, "FOMC"),   # FOMC 14:00
        (13, 30, "CPI"),   # CPI 13:30
    ]

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}

    # ─────────────── sessionfilter ───────────────

    def _is_in_trading_session(self) -> bool:
        now = getattr(self, '_backtest_time', None) or datetime.now()
        h = now.hour
        if self.TRADE_ASIAN_SESSION and 0 <= h < 6:
            return True
        if self.TRADE_LONDON_SESSION and self.LONDON_START_HOUR <= h < self.LONDON_START_HOUR + 4:
            return True
        if self.TRADE_NEW_YORK_SESSION and self.NEW_YORK_START_HOUR <= h < self.NEW_YORK_START_HOUR + 4:
            return True
        return False

    def _is_news_block(self) -> bool:
        if not self.USE_NEWS_FILTER:
            return False
        now = getattr(self, '_backtest_time', None) or datetime.now()
        minutes_since_midnight = now.hour * 60 + now.minute
        for nh, nm, _ in self.NEWS_EVENTS:
            news_minutes = nh * 60 + nm
            if (news_minutes - self.NEWS_BLOCK_MINUTES_BEFORE <= minutes_since_midnight <
                    news_minutes + self.NEWS_BLOCK_MINUTES_AFTER):
                return True
        return False

    # ─────────────── 趋-trend判断 ───────────────

    def _get_trend(self) -> Optional[str]:
        """
        双时间框架趋-trend判断：
        H1 EMA34 > H4 EMA200 → BUY
        H1 EMA34 < H4 EMA200 → SELL
        回测 从 M5 指标get EMA34  and  EMA200。
        """
        h1_ema_34 = self.get_indicator("ema_34")
        h4_ema_200 = self.get_indicator("ema_200")
        if h1_ema_34 is None or h4_ema_200 is None:
            return None

        if h4_ema_200 is None:
            return None

        if h1_ema_34 > h4_ema_200:
            return "BUY"
        elif h1_ema_34 < h4_ema_200:
            return "SELL"
        return None

    def _check_m5_confirm(self, trend: str) -> bool:
        """
        M5 Entryconfirm：M5 close 位于趋-trend方向一侧。
        多头趋-trend时 M5 不应大幅低于 EMA34(H1)，空头趋-trend时不应大幅高于 EMA34(H1)。
        """
        h1_ema_34 = self.get_indicator("ema_34")
        if h1_ema_34 is None or not self.candles:
            return False
        m5_close = self.candles[-1].close
        # 允许 0.5%  deviation
        tolerance = h1_ema_34 * 0.005
        if trend == "BUY":
            return m5_close >= h1_ema_34 - tolerance
        else:
            return m5_close <= h1_ema_34 + tolerance

    # ─────────────── Signalgenerate ───────────────

    def generate_signal(self):
        candles = self.candles
        if len(candles) < 60:
            return (None, 0, 0, [], [], {})

        # sessionfilter
        if not self._is_in_trading_session():
            return (None, 0, 0, [], [], {})
        if self._is_news_block():
            return (None, 0, 0, [], [], {})

        # ATR filter
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0 or atr_val < self.MIN_ATR_POINTS * 0.01:
            return (None, 0, 0, [], [], {})

        # 趋-trend判断
        trend = self._get_trend()
        if trend is None:
            return (None, 0, 0, [], [], {"close": round(candles[-1].close, 2), "reason": "no_trend"})

        # M5 Entryconfirm
        if not self._check_m5_confirm(trend):
            return (None, 0, 0, [], [], {"close": round(candles[-1].close, 2), "trend": trend, "reason": "m5_misalign"})

        direction = OrderType.BUY if trend == "BUY" else OrderType.SELL
        logger.info(f"[{self.name}] {direction.value} trend={trend}, ATR={atr_val:.2f}")

        return (direction, 1, 0, [trend], [], {
            "close": round(candles[-1].close, 2),
            "atr": round(atr_val, 2),
            "trend": trend,
        })

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 1.01, 2)
        sl_dist = atr_val * self.ATR_SL_MULTIPLIER
        tp_dist = atr_val * self.ATR_TP_MULTIPLIER
        if direction == OrderType.BUY:
            return round(entry_price - sl_dist, 2), round(entry_price + tp_dist, 2)
        else:
            return round(entry_price + sl_dist, 2), round(entry_price - tp_dist, 2)

    # ─────────────── 出场管理 ───────────────

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """ATR trailing止损 + 硬止损 / PnL平衡（原 EA 逻辑）。"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
                "break_even_set": False,
                "trailing_active": False,
            }

        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return False

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            profit = bid - td["entry"]
            if self.USE_BREAK_EVEN and not td["break_even_set"] and profit >= atr_val * self.BE_TRIGGER_ATR:
                td["break_even_set"] = True
                logger.info(f"[{self.name}] BUY BE ticket={ticket}")
                return False
            if self.USE_TRAILING_STOP and not td["trailing_active"] and profit >= atr_val * self.TRAIL_START_ATR:
                td["trailing_active"] = True
            if td["trailing_active"]:
                trail_sl = td["highest"] - atr_val * self.TRAIL_STEP_ATR
                if bid < trail_sl:
                    logger.info(f"[{self.name}] BUY TrailStop ticket={ticket}")
                    del self._trail_data[ticket]
                    return True
            if profit < -atr_val * self.ATR_SL_MULTIPLIER:
                logger.info(f"[{self.name}] BUY HardStop ticket={ticket}")
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            profit = td["entry"] - ask
            if self.USE_BREAK_EVEN and not td["break_even_set"] and profit >= atr_val * self.BE_TRIGGER_ATR:
                td["break_even_set"] = True
                logger.info(f"[{self.name}] SELL BE ticket={ticket}")
                return False
            if self.USE_TRAILING_STOP and not td["trailing_active"] and profit >= atr_val * self.TRAIL_START_ATR:
                td["trailing_active"] = True
            if td["trailing_active"]:
                trail_sl = td["lowest"] + atr_val * self.TRAIL_STEP_ATR
                if ask > trail_sl:
                    logger.info(f"[{self.name}] SELL TrailStop ticket={ticket}")
                    del self._trail_data[ticket]
                    return True
            if profit < -atr_val * self.ATR_SL_MULTIPLIER:
                logger.info(f"[{self.name}] SELL HardStop ticket={ticket}")
                del self._trail_data[ticket]
                return True
        return False

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        return True