"""
MTF 共振协调器 — H1+M15 TA-Lib 形态方向门禁
=============================================
功能：当 H1 与 M15 同时出现 TA-Lib 形态信号（同向）时，
      限制所有策略只能朝共振方向开仓。

工作原理:
  1. 每次 H1 K线收盘后，检测61种TA-Lib形态 + 质量过滤器
  2. 同时检查 M15 在同一时间窗口内是否有同向信号
  3. 共振 → 锁定方向（BUY/SELL），直到下一根H1K线重新评估
  4. 无共振 → BOTH（不限制）

用法:
  from services.mtf_coordinator import MTFResonanceCoordinator
  coord = MTFResonanceCoordinator(bridge)
  allowed = coord.get_allowed_direction()
"""

import logging
import numpy as np
import talib

from config import settings

logger = logging.getLogger(__name__)

LOOKAHEAD = 3

# 质量过滤器（来自回测结论: ta_lib_findings.md）
BULL_FILTERS = ["rsi_mid_oversold", "trend_down"]
BEAR_FILTERS = ["rsi_mid_overbought", "trend_up"]


class MTFResonanceCoordinator:
    """H1+M15 TA-Lib 共振协调器 — 方向门禁"""

    def __init__(self, bridge):
        self.bridge = bridge
        self._last_h1_ts: int = 0  # 上次处理的 H1 K线时间戳
        self._allowed: str = "BOTH"  # 缓存: BUY / SELL / BOTH

    def get_allowed_direction(self) -> str:
        """
        返回当前允许的交易方向。
        每次 H1 新K线收盘时重新评估，其余时间返回缓存。
        """
        coord_cfg = dict(settings.COORDINATOR_CONFIG)
        if not coord_cfg.get("enabled", False) or not coord_cfg.get("mtf_resonance_enabled", False):
            return "BOTH"

        # 从桥接获取最新 H1 K线
        h1_raw = self.bridge.get_candles(settings.SYMBOL, "H1", 100)
        if not h1_raw or len(h1_raw) < 5:
            return "BOTH"
        h1_candles = list(reversed(h1_raw))

        # 定位最后完整的 H1 K线
        n = len(h1_candles)
        completed_idx = n - 2  # [-1] 形成中, [-2] 最近完整收盘
        h1_ts = int(h1_candles[completed_idx].time)

        # 同一根K线只评估一次
        if h1_ts == self._last_h1_ts:
            return self._allowed
        self._last_h1_ts = h1_ts

        # 重新评估
        self._allowed = self._evaluate(h1_candles, h1_ts)
        if self._allowed != "BOTH":
            logger.info(f"[MTF共振协调器] 方向锁定: {self._allowed} (H1 K线 {self._fmt(h1_ts)})")
        return self._allowed

    # ------------------------------------------------------------------
    # 内部评估
    # ------------------------------------------------------------------

    def _evaluate(self, h1_candles, h1_ts):
        """评估 H1 + M15 共振方向"""
        # ---- H1 信号检测 ----
        h1_dir = self._detect_h1(h1_candles)
        if not h1_dir:
            return "BOTH"

        # ---- M15 共振检测 ----
        m15_candles = self._load_m15()
        if not m15_candles or len(m15_candles) < 50:
            return "BOTH"

        if not self._check_m15_confluence(m15_candles, h1_ts, h1_dir):
            return "BOTH"

        return "BUY" if h1_dir == "bull" else "SELL"

    def _detect_h1(self, candles):
        """检测最近完整 H1 K线的 TA-Lib 信号"""
        o = np.array([c.open for c in candles], dtype=float)
        h = np.array([c.high for c in candles], dtype=float)
        l = np.array([c.low for c in candles], dtype=float)
        c_arr = np.array([c.close for c in candles], dtype=float)

        ind = self._compute_indicators(o, h, l, c_arr)
        patterns = self._detect_patterns(o, h, l, c_arr)

        idx = len(candles) - 2  # 最近完整收盘
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
        """检查 H1 窗口内 M15 是否有同向信号"""
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
        """从 MT4 桥接获取 M15 数据"""
        try:
            raw = self.bridge.get_candles(settings.SYMBOL, "M15", 200)
            return list(reversed(raw))
        except Exception as e:
            logger.warning(f"[MTF协调器] M15 获取失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 指标 & 过滤器
    # ------------------------------------------------------------------

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

    @staticmethod
    def _fmt(ts):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%m-%d %H:%M")
