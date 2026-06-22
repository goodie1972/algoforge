"""
Gold-AutoResearch — H1 实盘策略
===============================
- 4因子共识投票: 趋势 + 动量 + 波动 + 安全
  - EMA10/20 → 趋势方向
  - MACD(12,26,9) + Stoch(14,3,3) → 动量
  - ADX + ATR → 波动活性
  - RSI(10) + BB(20,2) → 安全过滤
- 全部4条件一致才触发信号
- ATR动态追踪止损出场
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v6"
STRATEGY_MAGIC = 880306
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 880301, "date": "2026-06-08", "desc": "初始上线：4因子共识投票，ATR跟踪止损 trail=3.5 hard=2.0"},
    {"version": "v2", "magic": 880302, "date": "2026-06-08", "desc": "修复出场逻辑：区分盈利/亏损阶段，新增 peak_profit 跟踪"},
    {"version": "v3", "magic": 880303, "date": "2026-06-09", "desc": "双重止盈：trail=1.0 hard=2.0，新增 profit_drawdown_pct=0.25，新增 indicator_values 返回"},
    {"version": "v4", "magic": 880304, "date": "2026-06-11", "desc": "新增 tight_exit_mode 新闻风控"},
    {"version": "v5", "magic": 880305, "date": "2026-06-11", "desc": "SAFE-DN改为RSI≤35独立封空，防止接近超卖区开空"},
    {"version": "v6", "magic": 880306, "date": "2026-06-11", "desc": "位置门禁：60根K线区间底部10%禁空、顶部10%禁多"},
]


class GoldAutoResearchStrategy(BaseStrategy):
    """Gold-AutoResearch — H1 共识投票策略"""

    name = "gold_auto_research"

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None
        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0
        self._cached_adx: Optional[dict] = None
        self._cached_adx_key: int = 0

        # Exit params — 双重止盈：利润回撤25% + ATR移动止盈 + 硬止损
        self.p_trailing_atr = 1.0   # 回调超过 1 ATR 即止盈（原为 3.5）
        self.p_hard_atr = 2.0
        # profit_drawdown_pct 继承自 BaseStrategy（默认 0.25，由 settings.py 控制）

    def refresh_data(self, count: int = 300):
        self._cached_atr_key = 0
        self._cached_atr_values = None
        self._cached_adx_key = 0
        self._cached_adx = None
        super().refresh_data(count)

    # ─────────────── Indicator helpers ───────────────

    def _calc_ema(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period:
            return None
        k = 2.0 / (period + 1)
        ema = closes[0]
        for p in closes[1:]:
            ema = (p - ema) * k + ema
        return ema

    def _calc_sma(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period:
            return None
        return sum(closes[-period:]) / period

    def _calc_stddev(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period:
            return None
        sub = closes[-period:]
        s = sum(sub) / period
        return math.sqrt(sum((c - s) ** 2 for c in sub) / period)

    def _calc_rsi(self, closes: list[float], period: int = 14) -> Optional[float]:
        if len(closes) < period + 1:
            return None
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
        if avg_loss == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

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

    def _calc_adx(self, period: int = 14):
        """Compute ADX from candle data. Returns dict with adx_list, pdi_list, ndi_list."""
        cache_key = len(self.candles)
        if self._cached_adx_key == cache_key and self._cached_adx is not None:
            return self._cached_adx

        candles = self.candles
        n = len(candles)
        if n < period + 2:
            return None

        tr, plus_dm, minus_dm = [], [], []
        for i in range(1, n):
            h, l, pc = candles[i].high, candles[i].low, candles[i - 1].close
            ph = candles[i - 1].high
            pl_ = candles[i - 1].low
            tr.append(max(h - l, abs(h - pc), abs(l - pc)))
            up = h - ph
            down = pl_ - l
            plus_dm.append(up if up > down and up > 0 else 0)
            minus_dm.append(down if down > up and down > 0 else 0)

        if len(tr) < period:
            return None

        atr_val = sum(tr[:period]) / period
        pdi_val = sum(plus_dm[:period]) / period / atr_val * 100 if atr_val > 0 else 0
        ndi_val = sum(minus_dm[:period]) / period / atr_val * 100 if atr_val > 0 else 0

        atr_smooth = [atr_val]
        pdi_smooth = [pdi_val]
        ndi_smooth = [ndi_val]

        for i in range(period, len(tr)):
            atr_smooth.append((atr_smooth[-1] * (period - 1) + tr[i]) / period)
            pd_ = (pdi_smooth[-1] * (period - 1) + plus_dm[i] / atr_smooth[-1] * 100) / period if atr_smooth[-1] > 0 else 0
            nd_ = (ndi_smooth[-1] * (period - 1) + minus_dm[i] / atr_smooth[-1] * 100) / period if atr_smooth[-1] > 0 else 0
            pdi_smooth.append(pd_)
            ndi_smooth.append(nd_)

        dx = [abs(pdi_smooth[i] - ndi_smooth[i]) / max(pdi_smooth[i] + ndi_smooth[i], 0.001) * 100
              for i in range(len(atr_smooth))]
        adx_list = [sum(dx[:period]) / period]
        for i in range(period, len(dx)):
            adx_list.append((adx_list[-1] * (period - 1) + dx[i]) / period)

        result = {
            'adx_list': adx_list,
            'pdi_list': pdi_smooth,
            'ndi_list': ndi_smooth,
            'warmup': period + 1,
        }
        self._cached_adx = result
        self._cached_adx_key = cache_key
        return result

    def _get_adx_at(self, idx: int):
        """Get (adx, pdi, ndi) at candle index."""
        adx_result = self._calc_adx(14)
        if adx_result is None:
            return None, None, None
        warmup = adx_result['warmup']
        if idx < warmup:
            return None, None, None
        ai = idx - warmup
        if ai >= len(adx_result['adx_list']):
            return None, None, None
        return adx_result['adx_list'][ai], adx_result['pdi_list'][ai], adx_result['ndi_list'][ai]

    def _get_macd(self, closes: list[float]):
        """Compute MACD(12,26,9) up to current close. Returns (macd, signal, histogram)."""
        if len(closes) < 27:
            return None, None, None
        k12 = 2.0 / 13
        k26 = 2.0 / 27
        e12 = closes[0]
        e26 = closes[0]
        macd_line = []
        for p in closes:
            e12 = (p - e12) * k12 + e12
            e26 = (p - e26) * k26 + e26
            macd_line.append(e12 - e26)

        sig_line = [macd_line[0]]
        k9 = 2.0 / 10
        for v in macd_line[1:]:
            sig_line.append((v - sig_line[-1]) * k9 + sig_line[-1])

        macd_val = macd_line[-1]
        sig_val = sig_line[-1]
        return macd_val, sig_val, macd_val - sig_val

    def _get_stoch(self, idx: int):
        """Compute Stoch(14,3,3) at candle idx. Returns (k, d) or (None, None)."""
        if idx < 20:
            return None, None
        lookback = 14
        # %K
        w = self.candles[idx - lookback: idx + 1]
        hi_w = max(c.high for c in w)
        lo_w = min(c.low for c in w)
        k = 50.0 if hi_w == lo_w else (self.candles[idx].close - lo_w) / (hi_w - lo_w) * 100

        # %D (3-bar SMA of %K)
        k_values = []
        for j in range(idx - lookback, idx + 1):
            w2 = self.candles[j - lookback + 1: j + 1]
            h2 = max(c.high for c in w2)
            l2 = min(c.low for c in w2)
            k_values.append(50.0 if h2 == l2 else (self.candles[j].close - l2) / (h2 - l2) * 100)
        d = sum(k_values[-3:]) / 3 if len(k_values) >= 3 else k
        return k, d

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[OrderType]:
        candles = self.candles
        if len(candles) < 100:
            return None

        closes = self.get_close_prices()
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        close = closes[-1]
        high = highs[-1]
        low = lows[-1]
        n = len(closes)

        # ── ① Trend: EMA10 vs EMA20 ──
        ema10 = self._calc_ema(closes, 10)
        ema20 = self._calc_ema(closes, 20)
        if ema10 is None or ema20 is None:
            return None
        trend_up = ema10 > ema20
        trend_dn = ema10 < ema20

        # ── ② Momentum: MACD + Stoch ──
        macd_val, macd_sig, _ = self._get_macd(closes)
        stoch_k, stoch_d = self._get_stoch(n - 1)

        mom_up = False
        mom_dn = False
        if macd_val is not None:
            if macd_val > macd_sig:
                mom_up = True
            elif macd_val < macd_sig:
                mom_dn = True
        if stoch_k is not None:
            if stoch_k > stoch_d:
                mom_up = True
            elif stoch_k < stoch_d:
                mom_dn = True

        # ── ③ Volatility: ADX > 20 or ATR rising ──
        adx_val, pdi, ndi = self._get_adx_at(n - 1)
        atr_val = self._calc_atr(14)

        # ATR SMA(20) for comparison
        atr_all = self._calc_atr_values(14)
        atr_sma20 = None
        if atr_all and len(atr_all) >= 20:
            atr_sma20 = sum(atr_all[-20:]) / 20

        vol_active = False
        if adx_val is not None and adx_val > 20:
            vol_active = True
        elif atr_val and atr_sma20 and atr_val > atr_sma20:
            vol_active = True

        # ── ④ Safety: RSI(10) + BB(20,2) ──
        rsi_val = self._calc_rsi(closes, 10)
        bb_mid = self._calc_sma(closes, 20)
        bb_std = self._calc_stddev(closes, 20)

        safe_up = True
        safe_dn = True
        if bb_mid is not None and bb_std is not None:
            bb_up = bb_mid + 2 * bb_std
            bb_dn = bb_mid - 2 * bb_std
            if rsi_val is not None:
                if close >= bb_up and rsi_val >= 70:
                    safe_up = False
                # RSI <= 35 独立封空，防止接近超卖区开空
                if rsi_val <= 35:
                    safe_dn = False

        # ── Consensus ──
        logger.info(
            f"[{self.name}] Trend={'UP' if trend_up else 'DOWN'} "
            f"Mom={'UP' if mom_up else 'DOWN'} "
            f"Vol={'ACTIVE' if vol_active else 'QUIET'} "
            f"RSI={rsi_val:.1f} ADX={adx_val} "
            f"Price={close:.2f} "
            f"EMA10={ema10:.2f} EMA20={ema20:.2f}"
        )

        indicator_values = {
            "close": round(close, 2), "ema10": round(ema10, 2), "ema20": round(ema20, 2),
            "macd_val": round(macd_val, 4) if macd_val else 0,
            "macd_sig": round(macd_sig, 4) if macd_sig else 0,
            "stoch_k": round(stoch_k, 2) if stoch_k else 0,
            "stoch_d": round(stoch_d, 2) if stoch_d else 0,
            "adx": round(adx_val, 2) if adx_val else 0,
            "atr": round(atr_val, 2) if atr_val else 0,
            "rsi": round(rsi_val, 2) if rsi_val else 0,
            "bb_mid": round(bb_mid, 2) if bb_mid else 0,
            "bb_std": round(bb_std, 2) if bb_std else 0,
        }

        long_factors = []
        if trend_up: long_factors.append("TREND-UP")
        if mom_up: long_factors.append("MOM-UP")
        if vol_active: long_factors.append("VOL-ACTIVE")
        if safe_up: long_factors.append("SAFE-UP")

        short_factors = []
        if trend_dn: short_factors.append("TREND-DN")
        if mom_dn: short_factors.append("MOM-DN")
        if vol_active: short_factors.append("VOL-ACTIVE")
        if safe_dn: short_factors.append("SAFE-DN")

        signal = None
        if trend_up and mom_up and vol_active and safe_up:
            signal = OrderType.BUY
        elif trend_dn and mom_dn and vol_active and safe_dn:
            signal = OrderType.SELL

        return (signal, len(long_factors), len(short_factors), long_factors, short_factors, indicator_values)

    # ─────────────── Trend-aware exit multipliers ───────────────

    def _get_trend(self) -> str:
        """EMA10/20 trend: 'UP' / 'DOWN' / 'NEUTRAL'"""
        closes = self.get_close_prices()
        ema10 = self._calc_ema(closes, 10)
        ema20 = self._calc_ema(closes, 20)
        if ema10 is None or ema20 is None:
            return 'NEUTRAL'
        return 'UP' if ema10 > ema20 else 'DOWN'

    def _get_exit_multipliers(self, is_buy: bool) -> tuple[float, float]:
        trend = self._get_trend()
        if trend == 'UP':
            return (1.5, 3.0) if is_buy else (1.0, 2.0)
        elif trend == 'DOWN':
            return (1.0, 2.0) if is_buy else (1.5, 3.0)
        else:
            return (1.2, 2.5)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self._calc_atr(14)
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        _, hard_mult = self._get_exit_multipliers(direction == OrderType.BUY)
        dist = atr_val * hard_mult
        if direction == OrderType.BUY:
            tp = round(entry_price + dist * 50, 2)
            return round(entry_price - dist, 2), tp
        else:
            tp = round(entry_price - dist * 50, 2)
            # TP 为负时设为 0（不给 TP，让移动止盈逻辑出场），
            # 避免 MT4 OrderSend error 4107
            if tp <= 0:
                tp = 0
            return round(entry_price + dist, 2), tp

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """双重止盈：利润回撤止盈 + ATR移动止盈 + 硬止损"""
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

        trail_mult, hard_mult = self._get_exit_multipliers(is_buy)
        pdd = self.profit_drawdown_pct

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - td["entry"]
            loss = td["entry"] - bid
            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)

            if current_profit > 0:
                # 盈利 → 利润回撤止盈
                if self.profit_drawdown_enabled and td["peak_profit"] > 0:
                    profit_ratio = current_profit / td["peak_profit"]
                    if profit_ratio < (1 - pdd):
                        logger.info(f"[{self.name}] BUY ProfitStop ticket={ticket} profit=${current_profit:.2f} peak=${td['peak_profit']:.2f}")
                        self._last_exit_detail = {"exit_type": "profit_drawdown", "peak_profit": round(td["peak_profit"], 2), "current_profit": round(current_profit, 2), "atr": round(atr_val, 2)}
                        del self._trail_data[ticket]
                        return True

            # 移动止盈：从最高点回落（不论盈亏）
            drawdown = td["highest"] - bid
            if drawdown > atr_val * trail_mult:
                logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} drawdown={drawdown:.2f} trail={trail_mult}")
                self._last_exit_detail = {"exit_type": "trail_stop", "direction": "BUY", "drawdown": round(drawdown, 2), "atr": round(atr_val, 2), "trail_mult": trail_mult}
                del self._trail_data[ticket]
                return True

            # 硬止损（仅亏损时兜底）
            if current_profit <= 0 and loss > atr_val * hard_mult:
                logger.info(f"[{self.name}] BUY HardStop ticket={ticket} loss={loss:.2f} hard={hard_mult}")
                self._last_exit_detail = {"exit_type": "hard_stop", "direction": "BUY", "loss": round(loss, 2), "atr": round(atr_val, 2), "hard_mult": hard_mult}
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            current_profit = td["entry"] - ask
            loss = ask - td["entry"]
            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)

            if current_profit > 0:
                # 盈利 → 利润回撤止盈
                if self.profit_drawdown_enabled and td["peak_profit"] > 0:
                    profit_ratio = current_profit / td["peak_profit"]
                    if profit_ratio < (1 - pdd):
                        logger.info(f"[{self.name}] SELL ProfitStop ticket={ticket} profit=${current_profit:.2f} peak=${td['peak_profit']:.2f}")
                        self._last_exit_detail = {"exit_type": "profit_drawdown", "peak_profit": round(td["peak_profit"], 2), "current_profit": round(current_profit, 2), "atr": round(atr_val, 2)}
                        del self._trail_data[ticket]
                        return True

            # 移动止盈：从最低点反弹（不论盈亏）
            rally = ask - td["lowest"]
            if rally > atr_val * trail_mult:
                logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} rally={rally:.2f} trail={trail_mult}")
                self._last_exit_detail = {"exit_type": "trail_stop", "direction": "SELL", "rally": round(rally, 2), "atr": round(atr_val, 2), "trail_mult": trail_mult}
                del self._trail_data[ticket]
                return True

            # 硬止损（仅亏损时兜底）
            if current_profit <= 0 and loss > atr_val * hard_mult:
                logger.info(f"[{self.name}] SELL HardStop ticket={ticket} loss={loss:.2f} hard={hard_mult}")
                self._last_exit_detail = {"exit_type": "hard_stop", "direction": "SELL", "loss": round(loss, 2), "atr": round(atr_val, 2), "hard_mult": hard_mult}
                del self._trail_data[ticket]
                return True

        self._last_exit_detail = None
        return False
