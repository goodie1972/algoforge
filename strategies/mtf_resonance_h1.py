"""
MTF 共振策略 — H1+M15 TA-Lib 形态共振开仓
========================================
- 入场：H1 K 线收盘后检测 TA-Lib 形态 + 质量过滤器，同窗口 M15 有同向信号则开仓
- 止损：2× H1 ATR
- 止盈：ATR 移动跟踪止损（trail=1.0 hard=2.0）
"""

import logging
import math
from typing import Optional

import numpy as np
import talib

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 660801
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 660801, "date": "2026-06-15", "desc": "初始上线：H1+M15 TA-Lib 形态共振开仓，SL=2×ATR，TP=ATR跟踪"},
]

LOOKAHEAD = 3
BULL_FILTERS = ["rsi_mid_oversold", "trend_down"]
BEAR_FILTERS = ["rsi_mid_overbought", "trend_up"]


class MTFResonanceStrategy(BaseStrategy):
    """H1+M15 TA-Lib 形态共振策略"""

    name = "mtf_resonance_h1"

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None
        self._last_h1_ts: int = 0  # 上次处理的 H1 K线时间戳
        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

        # Exit params
        self.p_trailing_atr = 1.0   # 盈利后回调超过 1 ATR 止盈
        self.p_hard_atr = 2.0       # 亏损超过 2 ATR 硬止损

        # 新闻风控（引擎直接设置此属性）
        self.tight_exit_mode: bool = False

    def refresh_data(self, count: int = 200):
        self._cached_atr_key = 0
        self._cached_atr_values = None
        super().refresh_data(count)

    # ─────────────── ATR 计算 ───────────────

    def _calc_atr_values(self, period: int = 14) -> Optional[list[float]]:
        cache_key = len(self.candles)
        if self._cached_atr_key == cache_key and self._cached_atr_values is not None:
            return self._cached_atr_values

        candles = self.candles
        if len(candles) < period + 2:
            return None
        tr_values = []
        for i in range(1, len(candles)):
            h, l, pc = candles[i].high, candles[i].low, candles[i - 1].close
            tr_values.append(max(h - l, abs(h - pc), abs(l - pc)))
        if len(tr_values) < period:
            return None
        atr_list = [sum(tr_values[:period]) / period]
        for i in range(period, len(tr_values)):
            atr_list.append((atr_list[-1] * (period - 1) + tr_values[i]) / period)
        self._cached_atr_values = atr_list
        self._cached_atr_key = cache_key
        return atr_list

    def _calc_atr(self, period: int = 14) -> Optional[float]:
        vals = self._calc_atr_values(period)
        return vals[-1] if vals else None

    # ─────────────── 共振检测（复用 mtf_coordinator 逻辑） ───────────────

    def _detect_resonance(self) -> Optional[str]:
        """检测 H1+M15 共振，返回 'BUY' / 'SELL' / None"""
        h1_candles = self.candles
        if len(h1_candles) < 10:
            return None

        n = len(h1_candles)
        completed_idx = n - 2  # [-1] 形成中, [-2] 最近完整收盘
        h1_ts = int(h1_candles[completed_idx].time)

        # 同一根 K 线不重复检测
        if h1_ts == self._last_h1_ts:
            return None
        self._last_h1_ts = h1_ts

        # H1 信号检测
        h1_dir = self._detect_h1(h1_candles)
        if not h1_dir:
            return None

        # M15 共振确认
        m15_candles = self._load_m15()
        if not m15_candles or len(m15_candles) < 50:
            return None

        if not self._check_m15_confluence(m15_candles, h1_ts, h1_dir):
            return None

        return "BUY" if h1_dir == "bull" else "SELL"

    def _detect_h1(self, candles):
        o = np.array([c.open for c in candles], dtype=float)
        h = np.array([c.high for c in candles], dtype=float)
        l = np.array([c.low for c in candles], dtype=float)
        c_arr = np.array([c.close for c in candles], dtype=float)

        ind = self._compute_indicators(o, h, l, c_arr)
        patterns = self._detect_patterns(o, h, l, c_arr)

        idx = len(candles) - 2
        if idx < LOOKAHEAD + 2:
            return None

        for pname, sig_arr in patterns.items():
            raw = sig_arr[idx]
            if raw == 0:
                continue
            sig_dir = "bull" if raw > 0 else "bear"
            filters = BULL_FILTERS if sig_dir == "bull" else BEAR_FILTERS
            for fname in filters:
                if self._check_filter(idx, ind, c_arr, fname, sig_dir):
                    return sig_dir
        return None

    def _check_m15_confluence(self, m15_candles, h1_ts, h1_dir):
        window = [c for c in m15_candles if h1_ts <= int(c.time) < h1_ts + 3600]
        if len(window) < 3:
            return False

        o = np.array([c.open for c in window], dtype=float)
        h = np.array([c.high for c in window], dtype=float)
        l = np.array([c.low for c in window], dtype=float)
        c_arr = np.array([c.close for c in window], dtype=float)

        ind = self._compute_indicators(o, h, l, c_arr)
        patterns = self._detect_patterns(o, h, l, c_arr)

        for pname, sig_arr in patterns.items():
            for i in range(LOOKAHEAD + 2, len(sig_arr) - LOOKAHEAD - 2):
                raw = sig_arr[i]
                if raw == 0:
                    continue
                sig_dir = "bull" if raw > 0 else "bear"
                if sig_dir != h1_dir:
                    continue
                filters = BULL_FILTERS if sig_dir == "bull" else BEAR_FILTERS
                for fname in filters:
                    if self._check_filter(i, ind, c_arr, fname, sig_dir):
                        return True
        return False

    def _load_m15(self):
        try:
            raw = self.bridge.get_candles(self.symbol, "M15", 200)
            return list(reversed(raw))
        except Exception as e:
            logger.warning(f"[{self.name}] M15 获取失败: {e}")
            return []

    # ─────────────── 指标 & 过滤器 ───────────────

    def _compute_indicators(self, o, h, l, c):
        return {
            "rsi": talib.RSI(c, timeperiod=14),
            "ema20": talib.EMA(c, timeperiod=20),
        }

    def _detect_patterns(self, o, h, l, c):
        patterns = {}
        for pname in dir(talib):
            if not pname.startswith("CDL"):
                continue
            fn = getattr(talib, pname)
            try:
                sig = fn(o, h, l, c)
            except TypeError:
                try:
                    sig = fn(h, l, c)
                except TypeError:
                    continue
            if np.any(sig != 0):
                patterns[pname] = sig
        return patterns

    def _check_filter(self, idx, ind, close_arr, filter_name, sig_dir):
        rsi = ind["rsi"][idx]
        ema20 = ind["ema20"][idx]
        if filter_name == "rsi_mid_oversold":
            return not np.isnan(rsi) and 30 <= rsi <= 50 and sig_dir == "bull"
        if filter_name == "rsi_mid_overbought":
            return not np.isnan(rsi) and 50 <= rsi <= 70 and sig_dir == "bear"
        if filter_name == "trend_up":
            return not np.isnan(ema20) and close_arr[idx] > ema20
        if filter_name == "trend_down":
            return not np.isnan(ema20) and close_arr[idx] < ema20
        return False

    # ─────────────── 信号生成 ───────────────

    def generate_signal(self):
        """
        共振检测 → 信号
        返回: (signal, score_long, score_short, factors_long, factors_short, indicator_values)
        """
        # 始终计算当前 H1 指标（即使没信号也返回，便于监控）
        indicator_values = {}
        if len(self.candles) >= 20:
            atr_val = self._calc_atr(14)
            if atr_val is not None:
                indicator_values["atr"] = round(atr_val, 2)
            o = np.array([c.open for c in self.candles], dtype=float)
            h = np.array([c.high for c in self.candles], dtype=float)
            l = np.array([c.low for c in self.candles], dtype=float)
            c_arr = np.array([c.close for c in self.candles], dtype=float)
            if len(c_arr) >= 14:
                rsi_arr = talib.RSI(c_arr, timeperiod=14)
                ema20_arr = talib.EMA(c_arr, timeperiod=20)
                indicator_values["close"] = round(float(c_arr[-1]), 2)
                indicator_values["h1_rsi"] = round(float(rsi_arr[-1]) if not np.isnan(rsi_arr[-1]) else 50, 1)
                indicator_values["h1_ema20"] = round(float(ema20_arr[-1]) if not np.isnan(ema20_arr[-1]) else 0, 2)
                indicator_values["h1_trend"] = "up" if float(c_arr[-1]) > float(ema20_arr[-1]) else "down"

        direction = self._detect_resonance()
        if direction is None:
            return None, 0, 0, [], [], indicator_values

        if direction == "BUY":
            return OrderType.BUY, 1, 0, ["h1_m15_resonance"], [], {
                **indicator_values,
                "resonance": "BUY",
            }
        else:
            return OrderType.SELL, 0, 1, [], ["h1_m15_resonance"], {
                **indicator_values,
                "resonance": "SELL",
            }

    # ─────────────── 动态 SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self._calc_atr(14)
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        dist = atr_val * self.p_hard_atr
        if direction == OrderType.BUY:
            tp = round(entry_price + dist * 50, 2)
            return round(entry_price - dist, 2), tp
        else:
            tp = round(entry_price - dist * 50, 2)
            if tp <= 0:
                tp = 0
            return round(entry_price + dist, 2), tp

    # ─────────────── 出场（ATR 跟踪） ───────────────

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """ATR 移动止盈 + 2× ATR 硬止损"""
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
        atr_val = self._calc_atr(14)
        if atr_val is None or atr_val <= 0:
            return False

        trail_mult = self.p_trailing_atr
        hard_mult = self.p_hard_atr

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - td["entry"]
            loss = td["entry"] - bid

            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)

            if current_profit > 0:
                # 盈利 → 跟踪止盈
                drawdown = td["highest"] - bid
                if drawdown > atr_val * trail_mult:
                    logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} drawdown={drawdown:.2f} trail={trail_mult}")
                    self._last_exit_detail = {"exit_type": "trail_stop", "direction": "BUY", "drawdown": round(drawdown, 2), "atr": round(atr_val, 2)}
                    del self._trail_data[ticket]
                    return True
            else:
                # 亏损 → 硬止损
                if loss > atr_val * hard_mult:
                    logger.info(f"[{self.name}] BUY HardStop ticket={ticket} loss={loss:.2f} hard={hard_mult}")
                    self._last_exit_detail = {"exit_type": "hard_stop", "direction": "BUY", "loss": round(loss, 2), "atr": round(atr_val, 2)}
                    del self._trail_data[ticket]
                    return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            current_profit = td["entry"] - ask
            loss = ask - td["entry"]

            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)

            if current_profit > 0:
                # 盈利 → 跟踪止盈
                rally = ask - td["lowest"]
                if rally > atr_val * trail_mult:
                    logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} rally={rally:.2f} trail={trail_mult}")
                    self._last_exit_detail = {"exit_type": "trail_stop", "direction": "SELL", "rally": round(rally, 2), "atr": round(atr_val, 2)}
                    del self._trail_data[ticket]
                    return True
            else:
                # 亏损 → 硬止损
                if loss > atr_val * hard_mult:
                    logger.info(f"[{self.name}] SELL HardStop ticket={ticket} loss={loss:.2f} hard={hard_mult}")
                    self._last_exit_detail = {"exit_type": "hard_stop", "direction": "SELL", "loss": round(loss, 2), "atr": round(atr_val, 2)}
                    del self._trail_data[ticket]
                    return True

        return False
