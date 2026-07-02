"""
Momentum Pulse PRO — 7维度多因子评分 + 三层TP出场
====================================================
来源: TradingView Momentum Pulse PRO (自适应动量复合 + 多维度共识)
- AMC: RSI+MACD+ROC 合成动量分
- 7维度评分: AMC强度, 信号对齐, RSI区域, 多周期对齐, 成交量确认, 市场状态, 无衰竭
- 三层TP: TP1=1.5ATR(50%) → TP2=3.0ATR(30%) → 剩余移动追踪
"""

import logging
import math
import time
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 661301
STRATEGY_LEGACY_MAGICS: list[int] = []


class MomentumPulseProStrategy(BaseStrategy):
    """Momentum Pulse PRO — 7维度多因子评分 + 三层TP出场"""

    name = "momentum_pulse_pro"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None
        self._tp_hit: dict[int, int] = {}  # ticket -> TP level hit (1, 2)

        # === Entry params ===
        self.score_threshold = 6  # 7维度中至少6
        self.rsi_period = 14
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        self.roc_period = 10
        self.atr_period = 14

        # === Exit params — 三层TP ===
        self.tp1_atr = 1.5   # TP1: 1.5 ATR → 出50%
        self.tp2_atr = 3.0   # TP2: 3.0 ATR → 出30%
        self.tp3_atr = 5.0   # TP3: 5.0 ATR → 出20%
        self.sl_atr = 1.5    # 初始止损
        self.trail_atr = 1.5 # 移动追踪

        # 时间止损(根K线)
        self.max_bars = 40  # 日内交易默认40根

        # 冷却
        self._entry_bar: dict[int, int] = {}
        self._cooloff_until: float = 0

    def get_adx_data(self) -> Optional[dict]:
        _adx = self.get_indicator("adx")
        _pdi = self.get_indicator("pdi")
        _ndi = self.get_indicator("ndi")
        if _adx is not None:
            return {"adx": _adx, "pdi": _pdi, "ndi": _ndi}
        return None

    # ─────────────── Indicator helpers ───────────────

    def _calc_roc(self, closes: list[float], period: int = 10) -> Optional[float]:
        if len(closes) < period + 1: return None
        return (closes[-1] - closes[-period - 1]) / closes[-period - 1] * 100

    def _calc_amc(self, closes: list[float]) -> Optional[float]:
        """自适应动量复合(AMC): RSI + MACD + ROC Z-score归一化"""
        rsi = self.get_indicator("rsi")
        macd_d = self.get_indicator("macd")
        roc = self._calc_roc(closes)
        if rsi is None or macd_d is None or roc is None:
            return None
        rsi_norm = (rsi - 50) / 50         # -1~1
        macd_norm = macd_d["macd"] / max(closes[-1] * 0.001, 0.001)
        roc_norm = max(min(roc / 10, 1), -1)   # -1~1
        return (rsi_norm + macd_norm + roc_norm) / 3

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 60:
            return None

        closes = self.get_close_prices()
        close = closes[-1]
        atr_val = self.get_indicator("atr")
        if atr_val is None: return None

        # ── 计算7维度 ──
        long_score = 0; long_detail = []
        short_score = 0; short_detail = []

        # ① AMC强度
        amc = self._calc_amc(closes)
        if amc is not None:
            if amc > 0.3:
                long_score += 1; long_detail.append(f"AMC+{amc:.2f}")
            elif amc < -0.3:
                short_score += 1; short_detail.append(f"AMC{amc:.2f}")

        # ② 信号对齐: MACD方向
        macd_d = self.get_indicator("macd")
        if macd_d is not None:
            if macd_d["macd"] > 0:
                long_score += 1; long_detail.append("MACD+")
            else:
                short_score += 1; short_detail.append("MACD-")

        # ③ RSI区域
        rsi_val = self.get_indicator("rsi")
        if rsi_val is not None:
            if rsi_val > 50:
                long_score += 1; long_detail.append(f"RSI>{rsi_val:.0f}")
            else:
                short_score += 1; short_detail.append(f"RSI<{rsi_val:.0f}")

        # ④ 多周期对齐: H1方向
        try:
            h1_raw = self.bridge.get_candles(self.symbol, "H1", 50)
            h1_candles = list(reversed(h1_raw))
            h1_closes = [c.close for c in h1_candles]
            h1_ma = sum(h1_closes[-20:]) / 20 if len(h1_closes) >= 20 else None
            if h1_ma is not None:
                if h1_closes[-1] > h1_ma:
                    long_score += 1; long_detail.append("H1-UP")
                else:
                    short_score += 1; short_detail.append("H1-DN")
        except Exception:
            pass

        # ⑤ 成交量确认
        if len(candles) >= 21:
            avg_vol = sum(c.volume for c in candles[-21:-1]) / 20
            cur_vol = candles[-1].volume
            if cur_vol > avg_vol * 1.2:
                score_side = long_score if long_score > short_score else short_score
                if long_score >= short_score:
                    long_score += 1; long_detail.append("VOL+")
                else:
                    short_score += 1; short_detail.append("VOL+")

        # ⑥ 市场状态: ADX趋势
        _adx = self.get_indicator("adx")
        _pdi = self.get_indicator("pdi")
        _ndi = self.get_indicator("ndi")
        adx_data = {"adx": _adx, "pdi": _pdi, "ndi": _ndi} if _adx is not None else None
        if adx_data and adx_data["adx"] > 22:
            if adx_data["pdi"] > adx_data["ndi"]:
                long_score += 1; long_detail.append(f"TREND+{adx_data['adx']:.0f}")
            else:
                short_score += 1; short_detail.append(f"TREND-{adx_data['adx']:.0f}")

        # ⑦ 无衰竭: BB位置
        bb = self.get_indicator("bb")
        if bb:
            bb_range = bb["upper"] - bb["lower"]
            price_pos = (close - bb["lower"]) / bb_range if bb_range > 0 else 0.5
            if 0.2 < price_pos < 0.8:
                # 非极端位置 → 无衰竭(加分)
                if long_score >= short_score:
                    long_score += 1; long_detail.append(f"SAFE{price_pos:.0%}")
                else:
                    short_score += 1; short_detail.append(f"SAFE{price_pos:.0%}")

        # ── 决策 ──
        signal = None
        signal_str = "无信号"
        if long_score >= self.score_threshold and long_score > short_score:
            signal = OrderType.BUY
            signal_str = "LONG"
        elif short_score >= self.score_threshold and short_score > long_score:
            signal = OrderType.SELL
            signal_str = "SELL"

        detail_parts = []
        if long_detail: detail_parts.append("LONG: " + " ".join(long_detail))
        if short_detail: detail_parts.append("SHORT: " + " ".join(short_detail))
        logger.info(
            f"[{self.name}] 评分: {long_score}/{short_score}  {signal_str}  "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )

        indicator_values = {
            "close": round(close, 2), "atr": round(atr_val, 2),
            "amc": round(amc, 3) if amc is not None else 0,
            "rsi": round(rsi_val, 1) if rsi_val is not None else 0,
            "adx": round(adx_data["adx"], 1) if adx_data else 0,
            "long_score": long_score, "short_score": short_score,
        }
        return (signal, long_score, short_score, long_detail, short_detail, indicator_values)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """初始SL/TP: SL=1.5ATR, TP=TP1(1.5ATR) — 第一层目标"""
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return None  # fallback to settings pips
        sl_dist = atr_val * self.sl_atr
        tp_dist = atr_val * self.tp1_atr  # TP1
        if direction == OrderType.BUY:
            return round(entry_price - sl_dist, 2), round(entry_price + tp_dist, 2)
        else:
            return round(entry_price + sl_dist, 2), round(entry_price - tp_dist, 2)

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """三层TP出场: TP1→50%/ TP2→30%/ 剩余移动追踪"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
                "peak_profit": 0.0,
                "partial_closed": False,
            }
            self._tp_hit[ticket] = 0

        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return False

        entry = td["entry"]
        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - entry
            peak = td["highest"] - entry
            td["peak_profit"] = max(td["peak_profit"], current_profit)

            # TP命中检查
            tp_hit = self._tp_hit.get(ticket, 0)
            if tp_hit < 1 and current_profit > atr_val * self.tp1_atr:
                self._tp_hit[ticket] = 1
                logger.info(f"[{self.name}] BUY TP1命中 ticket={ticket} profit=${current_profit:.2f}")
                # TP1: 出50% — 引擎层会管理分批
                td["partial_closed"] = True
            if tp_hit < 2 and current_profit > atr_val * self.tp2_atr:
                self._tp_hit[ticket] = 2
                logger.info(f"[{self.name}] BUY TP2命中 ticket={ticket} profit=${current_profit:.2f}")
            if current_profit > atr_val * self.tp3_atr:
                self._last_exit_detail = {"exit_type": "tp3_hit", "profit": round(current_profit, 2)}
                del self._trail_data[ticket]
                return True

            # 移动追踪(TP1命中后启动或兜底)
            drawdown = td["highest"] - bid
            if drawdown > atr_val * self.trail_atr:
                logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} drawdown={drawdown:.2f}")
                self._last_exit_detail = {"exit_type": "trail_stop", "profit": round(current_profit, 2)}
                del self._trail_data[ticket]
                return True

            # 硬止损
            loss = entry - bid
            if loss > atr_val * self.sl_atr:
                logger.info(f"[{self.name}] BUY HardStop ticket={ticket} loss={loss:.2f}")
                self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss, 2)}
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            current_profit = entry - ask
            peak = entry - td["lowest"]
            td["peak_profit"] = max(td["peak_profit"], current_profit)

            tp_hit = self._tp_hit.get(ticket, 0)
            if tp_hit < 1 and current_profit > atr_val * self.tp1_atr:
                self._tp_hit[ticket] = 1
                logger.info(f"[{self.name}] SELL TP1命中 ticket={ticket} profit=${current_profit:.2f}")
                td["partial_closed"] = True
            if tp_hit < 2 and current_profit > atr_val * self.tp2_atr:
                self._tp_hit[ticket] = 2
                logger.info(f"[{self.name}] SELL TP2命中 ticket={ticket} profit=${current_profit:.2f}")
            if current_profit > atr_val * self.tp3_atr:
                self._last_exit_detail = {"exit_type": "tp3_hit", "profit": round(current_profit, 2)}
                del self._trail_data[ticket]
                return True

            rally = ask - td["lowest"]
            if rally > atr_val * self.trail_atr:
                logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} rally={rally:.2f}")
                self._last_exit_detail = {"exit_type": "trail_stop", "profit": round(current_profit, 2)}
                del self._trail_data[ticket]
                return True

            loss = ask - entry
            if loss > atr_val * self.sl_atr:
                logger.info(f"[{self.name}] SELL HardStop ticket={ticket} loss={loss:.2f}")
                self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss, 2)}
                del self._trail_data[ticket]
                return True

        self._last_exit_detail = None
        return False

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        """默认验证：tick 价不跑出 BB 边界"""
        direction = signal.get("direction", "BUY")
        bb = latest.get("bb") or signal.get("indicator_values", {}).get("bb") or {}
        if direction == "BUY":
            if bb.get("lower") and tick_price > bb["lower"] * 1.005:
                return False
        else:
            if bb.get("upper") and tick_price < bb["upper"] * 0.995:
                return False
        return True
