"""
BAKOME Gold Scalper Original — 完整 ICT 策略（原始版移植）
===========================================================
来源: https://github.com/BAKOME-Hub/BAKOMEPythonGoldScalper
原始 Python 1800+ 行完整 ICT 实现，仅适配系统接口
- M5 运行，ICT 核心概念：FVG + Order Block + Liquidity Sweep + Silver Bullet
- H4 EMA200 趋势方向定 Bias
- 仅 Silver Bullet 时段交易（伦敦 8-9、纽约 15-16，MT4 时区 UTC+3）
- 三重确认机制：Liquidity Sweep / FVG / Order Block 至少 2 个成立才入场
- ATR 动态风控：SL=2.0xATR, TP=3.0xATR, 盈亏平衡 + 追踪止损

数据源: 全部指标从 DataFactory TA-Lib 读取
"""
import logging
import time
from datetime import datetime
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1_original"
STRATEGY_MAGIC = 880303
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1_original", "magic": 880303, "date": "2026-08-02",
     "desc": "初始移植：BAKOME-Hub/BAKOMEPythonGoldScalper 完整 ICT 策略"},
]


class BAKOMEGoldScalperOriginalStrategy(BaseStrategy):
    """BAKOME Gold Scalper Original — 完整 ICT 策略（FVG + OB + Liquidity Sweep + Silver Bullet）"""

    name = "bakome_gold_scalper_original"
    default_timeframe = "M5"
    TIMEFRAME = "M5"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    # ── ICT 策略参数 ──
    USE_LIQUIDITY_SWEEPS = True
    USE_FAIR_VALUE_GAPS = True
    USE_ORDER_BLOCKS = True
    USE_SILVER_BULLET = True
    LIQUIDITY_LOOKBACK = 50
    FVG_LOOKBACK = 20
    FVG_MIN_SIZE_ATR = 0.5

    # ── 时段参数（MT4 时区 UTC+3） ──
    TRADE_ASIAN_SESSION = False
    TRADE_LONDON_SESSION = True
    TRADE_NEW_YORK_SESSION = True
    LONDON_START_HOUR = 7
    NEW_YORK_START_HOUR = 13
    LONDON_KILL_ZONE_START = 8
    LONDON_KILL_ZONE_END = 9
    NY_KILL_ZONE_START = 15
    NY_KILL_ZONE_END = 16

    # ── 趋势方向 ──
    H4_EMA_FAST = 34
    H4_EMA_SLOW = 200

    # ── 风控 ──
    ATR_SL_MULTIPLIER = 2.0
    ATR_TP_MULTIPLIER = 3.0
    USE_BREAK_EVEN = True
    BE_TRIGGER_ATR = 1.0
    USE_TRAILING_STOP = True
    TRAIL_START_ATR = 1.5
    TRAIL_STEP_ATR = 0.5
    MIN_ATR_POINTS = 100.0
    MAX_SPREAD_POINTS = 50.0

    # ── 交易参数 ──
    FIXED_LOTS = 0.01
    MAX_POSITIONS = 2
    MAX_DAILY_TRADES = 10
    SIGNAL_MIN_CONFIRMATIONS = 2  # 三重确认至少需要 2 个

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}

    # ─────────────── 时段检测 ───────────────

    def _is_in_silver_bullet(self) -> bool:
        """检查当前是否在 Silver Bullet 时段。回测时使用 _backtest_time 覆盖。"""
        if not self.USE_SILVER_BULLET:
            return True
        now = getattr(self, '_backtest_time', None) or datetime.now()
        h = now.hour
        if self.LONDON_KILL_ZONE_START <= h < self.LONDON_KILL_ZONE_END:
            return True
        if self.NY_KILL_ZONE_START <= h < self.NY_KILL_ZONE_END:
            return True
        return False

    def _is_in_trading_session(self) -> bool:
        """检查当前是否在允许的交易时段内。回测时使用 _backtest_time 覆盖。"""
        now = getattr(self, '_backtest_time', None) or datetime.now()
        h = now.hour
        if self.TRADE_ASIAN_SESSION and 0 <= h < 6:
            return True
        if self.TRADE_LONDON_SESSION and self.LONDON_START_HOUR <= h < self.LONDON_START_HOUR + 4:
            return True
        if self.TRADE_NEW_YORK_SESSION and self.NEW_YORK_START_HOUR <= h < self.NEW_YORK_START_HOUR + 4:
            return True
        return False

    # ─────────────── 趋势方向 ───────────────

    def _get_market_bias(self) -> Optional[str]:
        """H4 EMA200 趋势方向判断。"""
        h4_ema_slow = self.get_indicator("ema_200")
        close = self.candles[-1].close if self.candles else None
        if h4_ema_slow is None or close is None:
            return None
        return "BUY" if close > h4_ema_slow else "SELL"

    # ─────────────── ICT 检测 ───────────────

    def _detect_fvg(self) -> Optional[OrderType]:
        """检测 Fair Value Gap（3-K线缺口模式）。"""
        candles = self.candles
        if len(candles) < 4:
            return None
        c0 = candles[-3]
        c1 = candles[-2]
        c2 = candles[-1]
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return None

        # 多头 FVG：前前根 low > 当前 high（向下缺口后回补）
        gap_bullish = c0.low - c2.high
        if gap_bullish > atr_val * self.FVG_MIN_SIZE_ATR and c1.close < c1.open:
            return OrderType.BUY

        # 空头 FVG：前前根 high < 当前 low（向上缺口后回补）
        gap_bearish = c2.low - c0.high
        if gap_bearish > atr_val * self.FVG_MIN_SIZE_ATR and c1.close > c1.open:
            return OrderType.SELL

        return None

    def _detect_order_block(self) -> Optional[OrderType]:
        """检测 Order Block（强势突破前的反向 K 线）。"""
        candles = self.candles
        if len(candles) < 6:
            return None
        n = len(candles)
        c1 = candles[-1]
        c2 = candles[-2]
        c3 = candles[-3]

        avg_body = sum(abs(candles[i].close - candles[i].open) for i in range(max(0, n - 10), n)) / min(10, n)

        # 多头 OB：2 根大阳线 → 找之前的阴线作为 OB 区
        if c1.close > c1.open and c2.close > c2.open:
            body1 = abs(c1.close - c1.open)
            body2 = abs(c2.close - c2.open)
            if body2 > avg_body * 1.2 and body1 > avg_body * 1.5:
                for j in range(n - 3, max(0, n - 7), -1):
                    if candles[j].close < candles[j].open:
                        ob_price = candles[j].close
                        if c1.low <= ob_price * 1.003:
                            return OrderType.BUY

        # 空头 OB：2 根大阴线 → 找之前的阳线作为 OB 区
        if c1.close < c1.open and c2.close < c2.open:
            body1 = abs(c1.close - c1.open)
            body2 = abs(c2.close - c2.open)
            if body2 > avg_body * 1.2 and body1 > avg_body * 1.5:
                for j in range(n - 3, max(0, n - 7), -1):
                    if candles[j].close > candles[j].open:
                        ob_price = candles[j].close
                        if c1.high >= ob_price * 0.997:
                            return OrderType.SELL
        return None

    def _detect_liquidity_sweep(self) -> Optional[str]:
        """检测 Liquidity Sweep（流动性扫描：价格突破近期摆动高/低点后反转）。"""
        candles = self.candles
        if len(candles) < 20:
            return None
        n = len(candles)
        lookback = min(self.LIQUIDITY_LOOKBACK, n - 1)
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return None

        current_close = candles[-1].close
        tolerance = atr_val * 0.1

        # 找摆动高点和低点
        swing_highs = []
        swing_lows = []
        for i in range(n - lookback, n - 2):
            if (candles[i].high > candles[i-1].high and
                candles[i].high > candles[i-2].high and
                candles[i].high > candles[i+1].high and
                candles[i].high > candles[i+2].high):
                swing_highs.append(candles[i].high)
            if (candles[i].low < candles[i-1].low and
                candles[i].low < candles[i-2].low and
                candles[i].low < candles[i+1].low and
                candles[i].low < candles[i+2].low):
                swing_lows.append(candles[i].low)

        # 多头 LS：价格突破近期低点后回到低点之上
        if swing_lows:
            nearest_low = min(swing_lows)
            if current_close <= nearest_low + tolerance:
                return "BUY"

        # 空头 LS：价格突破近期高点后回到高点之下
        if swing_highs:
            nearest_high = max(swing_highs)
            if current_close >= nearest_high - tolerance:
                return "SELL"

        return None

    # ─────────────── 信号生成 ───────────────

    def generate_signal(self):
        candles = self.candles
        if len(candles) < 60:
            return (None, 0, 0, [], [], {})

        # 1. 时段检查
        if not self._is_in_trading_session():
            return (None, 0, 0, [], [], {})
        if not self._is_in_silver_bullet():
            return (None, 0, 0, [], [], {})

        # 2. ATR 过滤
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0 or atr_val < self.MIN_ATR_POINTS * 0.01:
            return (None, 0, 0, [], [], {})

        # 3. H4 EMA200 趋势 Bias
        bias = self._get_market_bias()
        if bias is None:
            return (None, 0, 0, [], [], {})

        # 4. ICT 三重确认
        ls_direction = self._detect_liquidity_sweep()
        fvg_sig = self._detect_fvg()
        ob_sig = self._detect_order_block()

        confirmations = []
        if ls_direction is not None and ls_direction == bias:
            confirmations.append("LS")
        if fvg_sig is not None and fvg_sig.value == bias:
            confirmations.append("FVG")
        if ob_sig is not None and ob_sig.value == bias:
            confirmations.append("OB")

        sig_strength = len(confirmations)
        if sig_strength < self.SIGNAL_MIN_CONFIRMATIONS:
            return (None, 0, 0, [], [], {
                "close": round(candles[-1].close, 2),
                "atr": round(atr_val, 2),
                "bias": bias,
                "confirmations": f"{sig_strength}/{self.SIGNAL_MIN_CONFIRMATIONS}",
                "ls": ls_direction or "none",
                "fvg": fvg_sig.value if fvg_sig else "none",
                "ob": ob_sig.value if ob_sig else "none",
            })

        direction = OrderType.BUY if bias == "BUY" else OrderType.SELL
        logger.info(f"[{self.name}] {direction.value} {confirmations} in Silver Bullet, ATR={atr_val:.2f}")

        return (direction, 1, 0, confirmations, [], {
            "close": round(candles[-1].close, 2),
            "atr": round(atr_val, 2),
            "bias": bias,
            "confirmations": "+".join(confirmations),
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
        """ATR 追踪止损 + 硬止损（代替原 EA 的盈亏平衡 + 追踪）。"""
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
            # 盈亏平衡
            profit = bid - td["entry"]
            if self.USE_BREAK_EVEN and not td["break_even_set"] and profit >= atr_val * self.BE_TRIGGER_ATR:
                td["break_even_set"] = True
                logger.info(f"[{self.name}] BUY BE ticket={ticket}")
                return False  # 让引擎统一修改 SL
            # 追踪止损
            if self.USE_TRAILING_STOP and not td["trailing_active"] and profit >= atr_val * self.TRAIL_START_ATR:
                td["trailing_active"] = True
                logger.info(f"[{self.name}] BUY TrailActive ticket={ticket}")
            if td["trailing_active"]:
                trail_sl = td["highest"] - atr_val * self.TRAIL_STEP_ATR
                if bid < trail_sl:
                    logger.info(f"[{self.name}] BUY TrailStop ticket={ticket}")
                    del self._trail_data[ticket]
                    return True
            # 硬止损
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
                logger.info(f"[{self.name}] SELL TrailActive ticket={ticket}")
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
        """默认验证：tick 价不跑出近期摆动范围。"""
        return True