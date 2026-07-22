"""
Stoch 回调顺势策略 (v8_upgraded)
==================================
大师理论: ADX>25 趋势确认 + Stoch 超买超卖回调入场
XAUUSD 专用参数: Stoch(14,3,3) 更快信号响应

核心变化 vs v7:
  - ADX 阈值从 20 提到 25，只在较强趋势中交易
  - Stoch 极端不再独立给分，有金叉/死叉时额外 +1
  - 金叉/死叉本身 +2 分不变

运动员验证:
  SELL: K>80(极端)→直接入场; K=60~80→需>=65
  BUY:  K<20(极端)→直接入场; K=20~40→需<=35

出场:
  - 硬止损: 1.5 ATR
  - 止盈: 3.0 ATR (止损×2)
  - DI反转: 趋势方向变化
  - ADX<20: 趋势衰竭
  - 趋势走完: Stoch 反向交叉确认
    - SELL死叉入场 → 金叉 或 K回到超卖区(<20) → 平
    - BUY金叉入场  → 死叉 或 K回到超买区(>80) → 平

数据源: 全部指标从 DataFactory TA-Lib 读取
"""
import logging
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy
from services.data_factory import get_cache

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v8_upgraded"
STRATEGY_MAGIC = 661203
STRATEGY_LEGACY_MAGICS: list[int] = [661201, 661202]
STRATEGY_CHANGELOG = [
    {"version": "v8_upgraded", "magic": 661203, "date": "2026-07-19",
     "desc": "升级版: ADX>25; 极端不独立给分; 1.5ATR止损3.0ATR止盈; Stoch交叉趋势走完出场"},
]


class StochTrendH1Upgraded(BaseStrategy):
    """Stoch 多周期回调顺势策略 — v8_upgraded"""

    name = "stoch_trend_h1_upgraded"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)

        # 参数
        self.adx_threshold = 25          # 从 20 提到 25
        self.sl_atr = 1.5                # 硬止损 1.5 ATR
        self.tp_atr = 3.0                # 止盈 3.0 ATR（2×止损）

        # 评分系统参数
        self.score_threshold = 4         # 满分 8 分，4 分及格

        # 持仓跟踪
        self._pos_data: dict[int, dict] = {}
        self._pending_entry_info: dict = {}
        self._last_exit_detail: Optional[dict] = None

        # Stoch 交叉检测：记录上一次的值（来自 DataFactory）
        self._prev_stoch_k: float = 50.0
        self._prev_stoch_d: float = 50.0

    def refresh_data(self, count: int = 350):
        super().refresh_data(count)
        # 多周期数据全部从 DataFactory 缓存读取，无需额外加载

    def get_adx_data(self) -> Optional[dict]:
        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        if adx is None:
            return None
        return {"adx": adx, "pdi": pdi, "ndi": ndi}

    def _get_h4_trend(self) -> Optional[str]:
        """从 DataFactory 缓存读取 H4 EMA21 判断趋势"""
        try:
            h4 = get_cache("H4")
            if not h4:
                return None
            ema21 = h4.get("ema_21")
            candles = h4.get("candles", [])
            if ema21 is None or not candles:
                return None
            close = candles[-1].close
            return 'UP' if close > ema21 else 'DOWN' if close < ema21 else None
        except Exception:
            return None

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 100:
            return None

        closes = self.get_close_prices()
        close = closes[-1]

        # ── 全部从 DataFactory 读取 ──
        stoch = self.get_indicator("stoch_5_3_3")
        if stoch is None:
            return None

        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return None

        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        if adx is None:
            return None

        ma_val = self.get_indicator("ema_21")
        if ma_val is None:
            return None

        k_curr = stoch["k"]
        d_curr = stoch["d"]
        k_prev = self._prev_stoch_k
        d_prev = self._prev_stoch_d
        self._prev_stoch_k = k_curr
        self._prev_stoch_d = d_curr

        cross_up_now = (k_curr > d_curr) and (k_prev <= d_prev)
        cross_down_now = (k_curr < d_curr) and (k_prev >= d_prev)

        # ADX <= 25 不交易
        if adx <= self.adx_threshold:
            return None

        # ── H4 趋势（DataFactory 缓存） ──
        h4_trend = self._get_h4_trend()
        h4_tag = f"H4:{h4_trend}" if h4_trend else "H4:NODATA"

        # ── M15 Stoch（DataFactory 缓存） ──
        m15 = get_cache("M15")
        m15_stoch = m15.get("stoch_5_3_3") if m15 else None
        m15_k = m15_stoch["k"] if m15_stoch else None

        # ── 评分系统 ──
        long_score, short_score = 0, 0
        long_factors, short_factors = [], []

        # v8: 极端不独立给分，只在有交叉时额外 +1
        has_extreme_buy = k_curr < 20
        has_extreme_sell = k_curr > 80

        if cross_up_now:
            long_score += 2
            long_factors.append("StochCross")
            if has_extreme_buy:
                long_score += 1
                long_factors.append("StochExtreme")
        if cross_down_now:
            short_score += 2
            short_factors.append("StochCross")
            if has_extreme_sell:
                short_score += 1
                short_factors.append("StochExtreme")

        # EMA21 方向
        if close > ma_val:
            long_score += 1
            long_factors.append("EMA21Dir")
        if close < ma_val:
            short_score += 1
            short_factors.append("EMA21Dir")

        # DI 方向
        if pdi > ndi:
            long_score += 1
            long_factors.append("DIDir")
        if ndi > pdi:
            short_score += 1
            short_factors.append("DIDir")

        # H4 趋势
        if h4_trend == 'UP':
            long_score += 1
            long_factors.append("H4Trend")
        if h4_trend == 'DOWN':
            short_score += 1
            short_factors.append("H4Trend")

        # M15 Stoch 对齐
        if m15_k is not None and m15_k < 30:
            long_score += 1
            long_factors.append("M15Align")
        if m15_k is not None and m15_k > 70:
            short_score += 1
            short_factors.append("M15Align")

        signal = None
        if long_score >= self.score_threshold:
            signal = OrderType.BUY
            self._pending_entry_info = {"regime": "trend", "adx": adx, "atr": atr_val, "extreme": has_extreme_buy, "pdi": pdi, "ndi": ndi}
        elif short_score >= self.score_threshold:
            signal = OrderType.SELL
            self._pending_entry_info = {"regime": "trend", "adx": adx, "atr": atr_val, "extreme": has_extreme_sell, "pdi": pdi, "ndi": ndi}

        iv = {
            "close": round(close, 2), "atr": round(atr_val, 2),
            "adx": round(adx, 1), "pdi": round(pdi, 1),
            "ndi": round(ndi, 1),
            "k": round(k_curr, 1), "d": round(d_curr, 1),
            "ema21": round(ma_val, 2),
            "h4_trend": h4_trend or "NODATA",
            "m15_k": round(m15_k, 1) if m15_k is not None else None,
            "long_score": long_score, "short_score": short_score,
        }

        logger.info(
            f"[{self.name}] K={k_curr:.1f} D={d_curr:.1f} ADX={adx:.1f} "
            f"H4={h4_trend or 'N/A'} M15K={f'{m15_k:.0f}' if m15_k is not None else 'N/A'} "
            f"得分:多={long_score} 空={short_score} "
            f"{'BUY' if signal == OrderType.BUY else 'SELL' if signal == OrderType.SELL else '无'}"
        )

        return (signal, long_score, short_score, long_factors, short_factors, iv)

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        sl_dist = atr_val * self.sl_atr
        tp_dist = atr_val * self.tp_atr  # 3.0 ATR = 1.5 ATR × 2
        if direction == OrderType.BUY:
            return round(entry_price - sl_dist, 2), round(entry_price + tp_dist, 2)
        else:
            return round(entry_price + sl_dist, 2), max(round(entry_price - tp_dist, 2), 0)

    # ─────────────── 出场 ───────────────

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._pos_data:
            self._pos_data[ticket] = {
                "entry_price": position.open_price,
                "peak": position.open_price,
                "entry_adx": self._pending_entry_info.get("adx", 0),
                "entry_pdi": self._pending_entry_info.get("pdi", 0),
                "entry_ndi": self._pending_entry_info.get("ndi", 0),
                "stoch_cross_done": False,
            }

        td = self._pos_data[ticket]
        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return False

        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")

        entry_price = td["entry_price"]
        pnl_pts = (bid - entry_price) if is_buy else (entry_price - ask)

        # ① 硬止损: 1.5 ATR
        if pnl_pts < -atr_val * self.sl_atr:
            logger.info(f"[{self.name}] HardStop 1.5ATR ticket={ticket}")
            self._last_exit_detail = {"exit_type": "hard_stop", "atr_mult": self.sl_atr}
            del self._pos_data[ticket]
            return True

        # ② 止盈: 3.0 ATR
        if pnl_pts > atr_val * self.tp_atr:
            logger.info(f"[{self.name}] TakeProfit 3.0ATR ticket={ticket}")
            self._last_exit_detail = {"exit_type": "take_profit", "atr_mult": self.tp_atr}
            del self._pos_data[ticket]
            return True

        # ③ DI反转（与入场时的DI方向比较，不是绝对大小）
        if adx is not None and pdi is not None and ndi is not None:
            entry_pdi = td.get("entry_pdi", 0)
            entry_ndi = td.get("entry_ndi", 0)
            if entry_pdi > entry_ndi and ndi > pdi:
                # 入场时PDI>NDI(多头)，现在NDI>PDI(空头)→真正翻转
                logger.info(f"[{self.name}] DI反转平{'BUY' if is_buy else 'SELL'} ticket={ticket} entry=({entry_pdi:.0f}/{entry_ndi:.0f}) now=({pdi:.0f}/{ndi:.0f})")
                self._last_exit_detail = {"exit_type": "di_flip"}
                del self._pos_data[ticket]
                return True
            elif entry_ndi > entry_pdi and pdi > ndi:
                logger.info(f"[{self.name}] DI反转平{'BUY' if is_buy else 'SELL'} ticket={ticket} entry=({entry_pdi:.0f}/{entry_ndi:.0f}) now=({pdi:.0f}/{ndi:.0f})")
                self._last_exit_detail = {"exit_type": "di_flip"}
                del self._pos_data[ticket]
                return True

        # ④ ADX < 20 趋势衰竭
        if adx is not None and adx < 20:
            logger.info(f"[{self.name}] ADX衰竭(<20) ticket={ticket}")
            self._last_exit_detail = {"exit_type": "adx_fade"}
            del self._pos_data[ticket]
            return True

        # ⑤ 趋势走完：Stoch 反向交叉确认（从 DataFactory 读取）
        stoch = self.get_indicator("stoch_5_3_3")
        if stoch:
            curr_k = stoch["k"]
            curr_d = stoch["d"]
            golden_cross = (curr_k > curr_d)
            death_cross = (curr_k < curr_d)

            if is_buy:
                # BUY金叉入场 → 等死叉 + K>65
                if death_cross or curr_k > 80:
                    logger.info(f"[{self.name}] BUY趋势走完(死叉K={curr_k:.1f}) ticket={ticket}")
                    self._last_exit_detail = {"exit_type": "stoch_reversal", "k": round(curr_k, 1)}
                    del self._pos_data[ticket]
                    return True
            else:
                # SELL死叉入场 → 等金叉 + K<35
                if golden_cross or curr_k < 20:
                    logger.info(f"[{self.name}] SELL趋势走完(金叉K={curr_k:.1f}) ticket={ticket}")
                    self._last_exit_detail = {"exit_type": "stoch_reversal", "k": round(curr_k, 1)}
                    del self._pos_data[ticket]
                    return True

        self._last_exit_detail = None
        return False

    # ─────────────── 验票 ───────────────

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        """v9 验票: 极端Stoch条件优先，DI仅过滤非极端情况"""
        direction = signal.get("direction", "BUY")
        adx = latest.get("adx", 20)
        pdi, ndi = latest.get("pdi", 15), latest.get("ndi", 15)
        stoch = latest.get("stoch_5_3_3") or {}
        stoch_k = stoch.get("k", 50)

        if adx < 25:
            return False

        if direction == "BUY":
            if stoch_k < 20:
                return True   # 极端金叉，直接入场
            if pdi <= ndi:
                return False
            if 20 <= stoch_k <= 40:
                return stoch_k <= 35
            return False
        else:
            if stoch_k > 80:
                return True   # 极端死叉，直接入场（不检查DI）
            if ndi <= pdi:
                return False
            if 60 <= stoch_k <= 80:
                return stoch_k >= 65
            return False
