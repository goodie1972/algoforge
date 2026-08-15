"""
BAKOME GoldScalper optimize版 (v2_optimized) — ICT FVG + OB + Silver Bullet
=========================================
ICT 概念: FVG (Fair Value Gap) + Order Block + Silver Bullet session

核心变化 vs v1:
  - 交易session从 6 h扩到 10 h（London 5h + NY 5h）
  - FVG 检测放宽：cancel蜡烛实体方向要求，仅保留缺口件
  - Magic 从 777004 改为 777006

session规则:
  London Silver Bullet: 服务器时间 6,7,8,9,10（5 h）
  NY Silver Bullet:     服务器时间 12,13,14,15,16（5 h）

version履历:
  v1 (777004) — 初始 FVG+OB, Silver Bullet 6h
  v2_optimized (777006) — session扩至 10h, FVG 件放宽
data源: all指标从 DataFactory TA-Lib read
"""

import logging
from datetime import datetime
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v3_optimized"
STRATEGY_MAGIC = 777006
STRATEGY_LEGACY_MAGICS: list[int] = [777004]
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 777004, "date": "2026-06-01",
     "desc": "初始: FVG+OB, Silver Bullet 6h (London 8-10, NY 13-15)"},
    {"version": "v2_optimized", "magic": 777006, "date": "2026-07-11",
     "desc": "optimize: session扩至 10h (London 6-10, NY 12-16), FVG 件放宽(cancel实体方向)"},
    {"version": "v3_optimized", "magic": 777006, "date": "2026-07-21",
     "desc": "ADX自适应出场: trailingtake profit随volatilityadjust, 强趋-trend放宽让profit跑"},
]


class BakomeBackupOptimized(BaseStrategy):
    """BAKOME GoldScalper — ICT FVG + OB + Silver Bullet (v3_optimized)"""

    name = "bakome_backup_optimized"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}

        # Exit params (ADX 自适应trailing/take profit，硬止损固定不变)
        self.p_hard_atr = 1.5       # 硬止损: 固定 1.5 ATR，不随 ADX 变化（最后防线）
        self.p_trail_chop = 1.0     # 震荡: 窄trailing
        self.p_trail_normal = 2.0   #  等: 正常trailing
        self.p_trail_trend = 3.0    # 强趋-trend: 宽trailing让profit跑
        self.p_profit_chop = 1.5    # 震荡: 小目标落袋
        self.p_profit_normal = 3.0  #  等: 正常take profit
        self.p_profit_trend = 5.0   # 强趋-trend: 大目标让profit跑

    def refresh_data(self, count: int = 200):
        super().refresh_data(count)

    # ─────────────── ICT Detection ───────────────

    def _is_silver_bullet(self) -> Optional[str]:
        """Check if current candle is in a Silver Bullet session.
        Hours: London 11-15, NY 17-21 (local UTC+8, converted from MT4 UTC+3)."""
        if not self.candles:
            return None
        now = datetime.now()
        h = now.hour
        # London session (UTC+3 6-10 → UTC+8 11-15)
        if h in [11, 12, 13, 14, 15]:
            return 'london'
        # NY session (UTC+3 12-16 → UTC+8 17-21)
        if h in [17, 18, 19, 20, 21]:
            return 'ny'
        return None

    def _detect_fvg(self) -> Optional[OrderType]:
        """Detect Fair Value Gap (3-candle pattern).
        Relaxed: only requires gap condition (midpoint comparison),
        no longer requires candle body direction."""
        candles = self.candles
        if len(candles) < 4:
            return None
        c0 = candles[-3]  # prev.prev
        c2 = candles[-1]  # current

        # Bullish FVG: prev.prev.low > current.high (gap)
        if c0.low > c2.high:
            return OrderType.BUY
        # Bearish FVG: prev.prev.high < current.low (gap)
        if c0.high < c2.low:
            return OrderType.SELL
        return None

    def _detect_order_block(self) -> Optional[OrderType]:
        """Detect Order Block: strong breakout preceded by opposite candle."""
        candles = self.candles
        if len(candles) < 6:
            return None
        n = len(candles)
        c1 = candles[-1]
        c2 = candles[-2]
        c3 = candles[-3]

        avg_body = sum(abs(candles[i].close - candles[i].open) for i in range(max(0, n - 10), n)) / min(10, n)

        # BUY OB: 2 big bullish candles → find previous bearish candle
        if c1.close > c1.open and c2.close > c2.open:
            body1 = abs(c1.close - c1.open)
            body2 = abs(c2.close - c2.open)
            if body2 > avg_body * 1.2 and body1 > avg_body * 1.5:
                for j in range(n - 3, max(0, n - 7), -1):
                    if candles[j].close < candles[j].open:
                        # Price returned to OB zone
                        ob_price = candles[j].close
                        if c1.low <= ob_price * 1.003:
                            return OrderType.BUY

        # SELL OB: 2 big bearish candles → find previous bullish candle
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

    # ─────────────── Signal generation ───────────────

    def generate_signal(self):
        candles = self.candles
        if len(candles) < 30:
            return (None, 0, 0, [], [], {})

        # 1. Silver Bullet session check
        session = self._is_silver_bullet()
        if not session:
            return (None, 0, 0, [], [], {})

        # 2. ATR filter
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return (None, 0, 0, [], [], {})

        # 3. BB expand  + MFI方向一致拦截（防趋-trend加速接飞刀）
        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _bb = self.get_indicator("bb")
        if _bwr is not None and _bwd is not None and _mfi is not None and _mfi_dir and _bb:
            _close = candles[-1].close
            _score = 0
            if _bwr > 1.05: _score += 1
            if _bwd == "up": _score += 1
            if _close > _bb["mid"] and _mfi_dir in ("up", "flat"): _score += 1
            if _close < _bb["mid"] and _mfi_dir in ("down", "flat"): _score += 1
            if _score >= 2:
                if _close > _bb["mid"] and _mfi_dir in ("up", "flat"):
                    logger.info(f"[{self.name}] BB expand (2/3) + price > mid + MFI rising({_mfi:.0f})，block short，skip FVG/OB")
                    return (None, 0, 0, [], [], {})
                if _close < _bb["mid"] and _mfi_dir in ("down", "flat"):
                    logger.info(f"[{self.name}] BB expand (2/3) + price < mid + MFI falling({_mfi:.0f})，block long，skip FVG/OB")
                    return (None, 0, 0, [], [], {})

        # 4. FVG check — NY session 禁FVG，其他session加ADX/MFIScoreconfirm
        indicator_values = {"close": round(self.candles[-1].close, 2), "atr": round(atr_val, 2)}
        fvg_sig = self._detect_fvg()
        if fvg_sig is not None:
            # NY session FVG win rate极低，直接disabled
            if session == 'ny':
                logger.info(f"[{self.name}] NY session skip FVG {fvg_sig.value}，NY session FVG win rate too low")
            else:
                # London/Asia session 加趋-trendconfirm
                _adx = self.get_indicator("adx")
                _mfi = self.get_indicator("mfi")
                _mfi_dir = self.get_indicator("mfi_direction")
                fvg_score = 0
                if _adx is not None and _adx > 20: fvg_score += 1
                if _mfi is not None and _mfi_dir:
                    if fvg_sig == OrderType.BUY and _mfi_dir in ("up", "flat"): fvg_score += 1
                    if fvg_sig == OrderType.SELL and _mfi_dir in ("down", "flat"): fvg_score += 1
                if fvg_score >= 1:
                    logger.info(f"[{self.name}] FVG {fvg_sig.value} in {session} session, ADX={_adx:.0f} MFI={_mfi:.0f} score={fvg_score}/2")
                    indicator_values["pattern"] = "FVG"
                    indicator_values["session"] = session
                    return (fvg_sig, 1, 0, [session, "FVG"], [], indicator_values)
                else:
                    logger.info(f"[{self.name}] FVG {fvg_sig.value} Score insufficient({fvg_score}/2) ADX={_adx:.0f} MFI={_mfi:.0f}，skip")

        # 5. Check Order Block
        ob_sig = self._detect_order_block()
        if ob_sig is not None:
            # OB 也加ADXconfirm
            _adx = self.get_indicator("adx")
            if _adx is not None and _adx > 20:
                logger.info(f"[{self.name}] OB {ob_sig.value} in {session} session, ADX={_adx:.0f}")
                indicator_values["pattern"] = "OB"
                indicator_values["session"] = session
                return (ob_sig, 1, 0, [session, "OB"], [], indicator_values)
            else:
                logger.info(f"[{self.name}] OB {ob_sig.value} ADX insufficient({_adx:.0f})，skip")

        return (None, 0, 0, [], [], indicator_values)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        dist = atr_val * 2.0
        if direction == OrderType.BUY:
            return round(entry_price - dist, 2), round(entry_price + dist * 50, 2)
        else:
            return round(entry_price + dist, 2), round(entry_price - dist * 50, 2)

    def _get_adx_multipliers(self):
        """ADX 自适应：return (trail_atr, profit_atr, hard_atr)"""
        adx = self.get_indicator("adx")
        if adx is None or adx <= 25:
            return self.p_trail_chop, self.p_profit_chop
        if adx > 35:
            return self.p_trail_trend, self.p_profit_trend
        return self.p_trail_normal, self.p_profit_normal

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        # 确保指标缓存update（_run_exits 在 _run_strategy 之前调用）
        self.refresh_data()

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

        trail_mult, profit_mult = self._get_adx_multipliers()

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            drawdown = td["highest"] - bid
            loss = td["entry"] - bid
            profit = bid - td["entry"]
            td["peak_profit"] = max(td["peak_profit"], profit)

            # take profit: profit达标主动出场
            if profit > atr_val * profit_mult:
                logger.info(f"[{self.name}] BUY TakeProfit ticket={ticket} profit=${profit:.2f} mult={profit_mult:.1f}")
                del self._trail_data[ticket]
                return True
            # trailing止损
            if drawdown > atr_val * trail_mult:
                logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} drawdown={drawdown:.2f} mult={trail_mult:.1f}")
                del self._trail_data[ticket]
                return True
            # 硬止损（固定 1.5 ATR，不随 ADX 变化）
            if loss > atr_val * self.p_hard_atr:
                logger.info(f"[{self.name}] BUY HardStop ticket={ticket} loss={loss:.2f}")
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            rally = ask - td["lowest"]
            loss = ask - td["entry"]
            profit = td["entry"] - ask
            td["peak_profit"] = max(td["peak_profit"], profit)

            # take profit
            if profit > atr_val * profit_mult:
                logger.info(f"[{self.name}] SELL TakeProfit ticket={ticket} profit=${profit:.2f} mult={profit_mult:.1f}")
                del self._trail_data[ticket]
                return True
            # trailing止损
            if rally > atr_val * trail_mult:
                logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} rally={rally:.2f} mult={trail_mult:.1f}")
                del self._trail_data[ticket]
                return True
            # 硬止损（固定 1.5 ATR，不随 ADX 变化）
            if loss > atr_val * self.p_hard_atr:
                logger.info(f"[{self.name}] SELL HardStop ticket={ticket} loss={loss:.2f}")
                del self._trail_data[ticket]
                return True

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
