"""
Viprasol Sniper — 7因子共识 + 多级RR出场
=============================================
来源: TradingView Viprasol Sniper Confluence Entry/Exit
- 7因子评分: VWAP替代→EMA位置, RSI, MACD, EMA排列, ADX+DI, 成交量, 次级RSI
- 多级RR出场: 1R/2R/3R/4R/5R, TP1命中后移到保本
- K线收盘确认
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 661401
STRATEGY_LEGACY_MAGICS: list[int] = []


class ViprasolSniperStrategy(BaseStrategy):
    """Viprasol Sniper — 7因子共识 + 多级RR出场"""

    name = "viprasol_sniper"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}

        # === Entry params ===
        self.score_threshold = 4  # 7因子中至少4
        self.rsi_period = 14
        self.ema_fast = 9
        self.ema_slow = 21
        self.atr_period = 14

        # === Exit params — 多级RR ===
        self.sl_atr = 1.5    # 初始止损 = 1R
        self.rr_levels = [1, 2, 3, 4, 5]  # 5级TP
        self.trail_atr = 1.0  # 移动追踪

    def get_adx_data(self) -> Optional[dict]:
        return self._calc_adx(14)

    # ─────────────── Indicator helpers ───────────────

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

    def _calc_macd(self, closes: list[float]) -> Optional[dict]:
        if len(closes) < 35: return None
        ema12 = self._calc_ema(closes, 12)
        ema26 = self._calc_ema(closes, 26)
        if ema12 is None or ema26 is None: return None
        macd_line = ema12 - ema26
        return {"macd": macd_line}

    def _calc_atr(self, period: int = 14) -> Optional[float]:
        candles = self.candles
        if len(candles) < period + 2: return None
        tr_sum = 0
        for i in range(1, period + 2):
            h, l_, pc = candles[-i].high, candles[-i].low, candles[-i-1].close
            tr_sum += max(h - l_, abs(h - pc), abs(l_ - pc))
        return tr_sum / (period + 1)

    def _calc_adx(self, period: int = 14) -> Optional[dict]:
        candles = self.candles
        if len(candles) < period + 2: return None
        n = len(candles)
        tr_list, plus_dm, minus_dm = [], [], []
        for i in range(1, n):
            h, l_, pc = candles[i].high, candles[i].low, candles[i-1].close
            ph, pl = candles[i-1].high, candles[i-1].low
            tr = max(h - l_, abs(h - pc), abs(l_ - pc))
            up = h - ph; down = pl - l_
            plus_dm.append(up if (up > down and up > 0) else 0)
            minus_dm.append(down if (down > up and down > 0) else 0)
            tr_list.append(tr)
        if len(tr_list) < period: return None
        atr_v = sum(tr_list[:period]) / period
        pdi_v = sum(plus_dm[:period]) / period
        ndi_v = sum(minus_dm[:period]) / period
        if atr_v <= 0: return None
        pdi_v, ndi_v = pdi_v / atr_v * 100, ndi_v / atr_v * 100
        atr_s, pdi_s, ndi_s = [atr_v], [pdi_v], [ndi_v]
        for i in range(period, len(tr_list)):
            atr_s.append((atr_s[-1] * (period - 1) + tr_list[i]) / period)
            if atr_s[-1] > 0:
                pdi_s.append((pdi_s[-1] * (period - 1) + plus_dm[i]/atr_s[-1]*100) / period)
                ndi_s.append((ndi_s[-1] * (period - 1) + minus_dm[i]/atr_s[-1]*100) / period)
        dx = [abs(pdi_s[i]-ndi_s[i])/max(pdi_s[i]+ndi_s[i], 0.001)*100 for i in range(len(atr_s))]
        adx = [sum(dx[:period]) / period]
        for i in range(period, len(dx)):
            adx.append((adx[-1] * (period - 1) + dx[i]) / period)
        return {"adx": adx[-1], "pdi": pdi_s[-1], "ndi": ndi_s[-1]}

    def _calc_bb_levels(self) -> Optional[dict]:
        closes = self.get_close_prices()
        if len(closes) < 20: return None
        recent = closes[-20:]
        sma = sum(recent) / 20
        variance = sum((c - sma) ** 2 for c in recent) / 20
        std = math.sqrt(variance)
        return {"sma": sma, "upper": sma + 2 * std, "lower": sma - 2 * std}

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 60: return None

        closes = self.get_close_prices()
        close = closes[-1]
        atr_val = self._calc_atr()
        if atr_val is None: return None

        ema9 = self._calc_ema(closes, 9)
        ema21 = self._calc_ema(closes, 21)
        if ema9 is None or ema21 is None: return None

        long_score = 0; long_detail = []
        short_score = 0; short_detail = []

        # ① 价格vs EMA位置 (VWAP替代)
        if close > ema21:
            long_score += 1; long_detail.append(f"EMA>{ema21:.1f}")
        else:
            short_score += 1; short_detail.append(f"EMA<{ema21:.1f}")

        # ② RSI方向
        rsi_val = self._calc_rsi(closes)
        if rsi_val is not None:
            if rsi_val > 50:
                long_score += 1; long_detail.append(f"RSI>{rsi_val:.0f}")
            elif rsi_val < 50:
                short_score += 1; short_detail.append(f"RSI<{rsi_val:.0f}")

        # ③ MACD方向
        macd_d = self._calc_macd(closes)
        if macd_d is not None:
            if macd_d["macd"] > 0:
                long_score += 1; long_detail.append("MACD+")
            else:
                short_score += 1; short_detail.append("MACD-")

        # ④ EMA排列
        if ema9 > ema21:
            long_score += 1; long_detail.append("EMA9>21")
        else:
            short_score += 1; short_detail.append("EMA9<21")

        # ⑤ ADX>25 + DI方向
        adx_data = self._calc_adx()
        if adx_data and adx_data["adx"] > 25:
            if adx_data["pdi"] > adx_data["ndi"]:
                long_score += 1; long_detail.append(f"DI+{adx_data['pdi']-adx_data['ndi']:.0f}")
            else:
                short_score += 1; short_detail.append(f"DI-{adx_data['ndi']-adx_data['pdi']:.0f}")

        # ⑥ 成交量确认
        if len(candles) >= 21:
            avg_vol = sum(c.volume for c in candles[-21:-1]) / 20
            cur_vol = candles[-1].volume
            is_bull_candle = candles[-1].close > candles[-1].open
            if cur_vol > avg_vol * 1.2:
                if is_bull_candle:
                    long_score += 1; long_detail.append("VOL+")
                else:
                    short_score += 1; short_detail.append("VOL+")

        # ⑦ 次级RSI (M15)
        try:
            m15_raw = self.bridge.get_candles(self.symbol, "M15", 30)
            m15_candles = list(reversed(m15_raw))
            m15_closes = [c.close for c in m15_candles]
            rsi_m15 = self._calc_rsi(m15_closes)
            if rsi_m15 is not None:
                if rsi_m15 > 50:
                    long_score += 1; long_detail.append(f"M15-RSI>{rsi_m15:.0f}")
                else:
                    short_score += 1; short_detail.append(f"M15-RSI<{rsi_m15:.0f}")
        except Exception:
            pass

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
            "rsi": round(rsi_val, 1) if rsi_val is not None else 0,
            "ema9": round(ema9, 2), "ema21": round(ema21, 2),
            "adx": round(adx_data["adx"], 1) if adx_data else 0,
            "long_score": long_score, "short_score": short_score,
        }
        return (signal, long_score, short_score, long_detail, short_detail, indicator_values)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """初始SL/TP: SL=1.5ATR, TP=1R(1.5ATR)"""
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return None
        dist = atr_val * self.sl_atr
        if direction == OrderType.BUY:
            return round(entry_price - dist, 2), round(entry_price + dist, 2)
        else:
            return round(entry_price + dist, 2), round(entry_price - dist, 2)

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """多级RR出场 + 保本 + 移动追踪"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
                "peak_profit": 0.0,
                "breakeven": False,
            }

        td = self._trail_data[ticket]
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return False

        entry = td["entry"]
        risk_r = atr_val * self.sl_atr  # 1R

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - entry
            td["peak_profit"] = max(td["peak_profit"], current_profit)

            # TP1命中→移到保本
            if not td["breakeven"] and current_profit > risk_r * self.rr_levels[0]:
                td["breakeven"] = True
                self.bridge.modify_order(ticket, sl=entry, tp=0)
                logger.info(f"[{self.name}] BUY 保本触发 ticket={ticket}")

            # 逐级TP
            for level in reversed(self.rr_levels):
                tp_price = entry + risk_r * level
                if bid >= tp_price:
                    logger.info(f"[{self.name}] BUY TP{level}R  ticket={ticket} profit=${current_profit:.2f}")
                    self._last_exit_detail = {"exit_type": f"tp{level}r", "profit": round(current_profit, 2)}
                    del self._trail_data[ticket]
                    return True

            # 移动追踪
            drawdown = td["highest"] - bid
            if drawdown > atr_val * self.trail_atr and td["peak_profit"] > atr_val * 0.5:
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
            td["peak_profit"] = max(td["peak_profit"], current_profit)

            if not td["breakeven"] and current_profit > risk_r * self.rr_levels[0]:
                td["breakeven"] = True
                self.bridge.modify_order(ticket, sl=entry, tp=0)
                logger.info(f"[{self.name}] SELL 保本触发 ticket={ticket}")

            for level in reversed(self.rr_levels):
                tp_price = entry - risk_r * level
                if ask <= tp_price:
                    logger.info(f"[{self.name}] SELL TP{level}R  ticket={ticket} profit=${current_profit:.2f}")
                    self._last_exit_detail = {"exit_type": f"tp{level}r", "profit": round(current_profit, 2)}
                    del self._trail_data[ticket]
                    return True

            rally = ask - td["lowest"]
            if rally > atr_val * self.trail_atr and td["peak_profit"] > atr_val * 0.5:
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
