"""
M30 MFI + 布林带双模策略 — ADX=25 趋势/震荡分界
=============================================
- ADX≥25 趋势模式: 顺着 +DI/-DI 方向交易，MFI 回调至 40-60 中值区域进场
- ADX<25 震荡模式: MFI 极端值(>80/<20) + BB 触轨均值回归
- 入场: 5因子评分系统 ≥3 分触发
- 出场: ATR 动态追踪止损 + 硬止损 + 利润回撤止盈
- 双向交易
"""

import logging
import math
import time
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 661001
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 661001, "date": "2026-06-26", "desc": "初始上线：MFI+BB 双模策略，ADX=25 分界"},
]


class M30MFIBBStrategy(BaseStrategy):
    """M30 MFI + 布林带双模策略"""

    name = "mfi_bb_m30"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None

        # Entry params
        self.mfi_period = 14
        self.mfi_oversold = 20
        self.mfi_overbought = 80
        self.mfi_mid_low = 40
        self.mfi_mid_high = 60
        self.bb_std = 2.0
        self.score_threshold = 3

        # ADX 双模分界
        self.adx_trend_threshold = 25

        # Exit params
        self.p_trailing_atr = 1.0
        self.p_hard_atr = 2.0

        # Indicator params
        self.bb_period = 20
        self.atr_period = 20
        self.ma20_period = 20

        # 盈利平仓冷却
        self._last_profit_exit_time: dict[str, float] = {"BUY": 0.0, "SELL": 0.0}
        self._exit_cooldown_seconds: int = 1800

        # ATR cache
        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

    def get_adx_data(self) -> Optional[dict]:
        return self._calc_adx(14)

    def refresh_data(self, count: int = 350):
        self._cached_atr_key = 0
        self._cached_atr_values = None
        super().refresh_data(count)

    # ─────────────── Indicator helpers ───────────────

    def _calc_sma(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period: return None
        return sum(closes[-period:]) / period

    def _calc_ema(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period: return None
        k = 2.0 / (period + 1)
        ema = closes[0]
        for p in closes[1:]:
            ema = (p - ema) * k + ema
        return ema

    def _calc_atr_values(self, period: int = 20) -> Optional[list[float]]:
        cache_key = len(self.candles)
        if self._cached_atr_key == cache_key and self._cached_atr_values is not None:
            return self._cached_atr_values

        candles = self.candles
        if len(candles) < period + 2: return None
        tr_values = []
        for i in range(1, len(candles)):
            h = candles[i].high
            l_ = candles[i].low
            pc = candles[i - 1].close
            tr = max(h - l_, abs(h - pc), abs(l_ - pc))
            tr_values.append(tr)
        if len(tr_values) < period: return None
        atr_list = [sum(tr_values[:period]) / period]
        for i in range(period, len(tr_values)):
            atr_list.append((atr_list[-1] * (period - 1) + tr_values[i]) / period)
        self._cached_atr_values = atr_list
        self._cached_atr_key = cache_key
        return atr_list

    def _calc_atr(self, period: int = 20) -> Optional[float]:
        vals = self._calc_atr_values(period)
        if vals is None or len(vals) == 0: return None
        return vals[-1]

    def _calc_bb_levels(self) -> Optional[dict]:
        closes = self.get_close_prices()
        if len(closes) < self.bb_period: return None
        recent = closes[-self.bb_period:]
        sma = sum(recent) / self.bb_period
        variance = sum((c - sma) ** 2 for c in recent) / self.bb_period
        std = math.sqrt(variance)
        return {"sma": sma, "upper": sma + self.bb_std * std, "lower": sma - self.bb_std * std}

    def _calc_mfi(self) -> Optional[float]:
        """计算 MFI(14) — 需 volume 数据"""
        candles = self.candles
        if len(candles) < self.mfi_period + 1:
            return None

        typical = [(c.high + c.low + c.close) / 3.0 for c in candles]
        money_flow = [tp * c.volume for tp, c in zip(typical, candles)]

        pos_flow, neg_flow = 0.0, 0.0
        for i in range(-self.mfi_period, 0):
            if typical[i] > typical[i - 1]:
                pos_flow += money_flow[i]
            else:
                neg_flow += money_flow[i]

        if neg_flow == 0:
            return 100.0
        mfr = pos_flow / neg_flow
        return 100.0 - 100.0 / (1.0 + mfr)

    def _get_m30_trend(self) -> str:
        """M30 MA20 趋势判断"""
        closes = self.get_close_prices()
        if len(closes) < self.ma20_period:
            return 'NEUTRAL'
        ma20 = sum(closes[-self.ma20_period:]) / self.ma20_period
        return 'UP' if closes[-1] > ma20 else 'DOWN'

    def _calc_adx(self, period: int = 14) -> Optional[dict]:
        """标准 Wilder ADX/+DI/-DI（0-100 量纲），委托基类统一实现"""
        return self.calc_adx_wilder(self.candles, period)

    # ─────────────── Score helpers ───────────────

    def _score_trend_mode(self, adx_data: dict) -> tuple:
        """趋势模式评分 (ADX≥25): 顺 DI 方向交易，MFI 中值回调进场"""
        closes = self.get_close_prices()
        close = closes[-1]
        bb = self._calc_bb_levels()
        mfi_val = self._calc_mfi()
        m30_trend = self._get_m30_trend()

        long_score = 0; long_detail = []
        short_score = 0; short_detail = []

        pdi = adx_data["pdi"]
        ndi = adx_data["ndi"]
        adx = adx_data["adx"]

        # ① DI 方向: +DI > -DI 偏多, 反之偏空
        di_bull = pdi > ndi
        if di_bull:
            long_score += 1; long_detail.append(f"DI+{pdi - ndi:.0f}")
        else:
            short_score += 1; short_detail.append(f"DI-{ndi - pdi:.0f}")

        # ② MFI 回调中值区 (40-60): 趋势中的回调进场信号
        if mfi_val is not None:
            if di_bull and self.mfi_mid_low <= mfi_val <= self.mfi_mid_high:
                long_score += 1; long_detail.append(f"MFI-{mfi_val:.0f}")
            elif not di_bull and self.mfi_mid_low <= mfi_val <= self.mfi_mid_high:
                short_score += 1; short_detail.append(f"MFI-{mfi_val:.0f}")

        # ③ MA20 趋势确认
        if m30_trend == 'UP':
            long_score += 1; long_detail.append("MA20-UP")
        elif m30_trend == 'DOWN':
            short_score += 1; short_detail.append("MA20-DN")

        # ④ BB 中轨附近: 趋势中价格回到中轨是顺趋势进场点
        if bb:
            mid = bb["sma"]
            dist_pct = abs(close - mid) / (bb["upper"] - bb["lower"]) if (bb["upper"] - bb["lower"]) > 0 else 1
            if dist_pct < 0.3:
                if di_bull:
                    long_score += 1; long_detail.append("BB-MID")
                else:
                    short_score += 1; short_detail.append("BB-MID")

        # ⑤ ADX 强度: ADX≥30 额外 +1 确认趋势强度
        if adx >= 30:
            if di_bull:
                long_score += 1; long_detail.append(f"ADX{adx:.0f}")
            else:
                short_score += 1; short_detail.append(f"ADX{adx:.0f}")

        return long_score, short_score, long_detail, short_detail

    def _score_oscillate_mode(self) -> tuple:
        """震荡模式评分 (ADX<25): MFI 极端 + BB 触轨均值回归"""
        closes = self.get_close_prices()
        close = closes[-1]
        bb = self._calc_bb_levels()
        mfi_val = self._calc_mfi()
        m30_trend = self._get_m30_trend()

        long_score = 0; long_detail = []
        short_score = 0; short_detail = []

        # ① BB 触轨
        if bb:
            if close <= bb['lower']:
                long_score += 1; long_detail.append("BB-BOT")
            if close >= bb['upper']:
                short_score += 1; short_detail.append("BB-TOP")

        # ② MFI 极端
        if mfi_val is not None:
            if mfi_val <= self.mfi_oversold:
                long_score += 1; long_detail.append(f"MFI-{mfi_val:.0f}")
            elif mfi_val >= self.mfi_overbought:
                short_score += 1; short_detail.append(f"MFI-{mfi_val:.0f}")

        # ③ MFI 方向: MFI 回升/回落确认
        if mfi_val is not None and len(closes) >= self.mfi_period + 5:
            mfi_prev = self._calc_mfi_from(closes[:-2])
            if mfi_prev is not None and mfi_val > mfi_prev:
                long_score += 1; long_detail.append("MFI-UP")
            elif mfi_prev is not None and mfi_val < mfi_prev:
                short_score += 1; short_detail.append("MFI-DN")

        # ④ MA20 趋势
        if m30_trend == 'UP':
            long_score += 1; long_detail.append("MA20-UP")
        elif m30_trend == 'DOWN':
            short_score += 1; short_detail.append("MA20-DN")

        # ⑤ BB+MFI 共振: 触轨 + 极端同时出现确认强回归信号
        if bb and mfi_val is not None:
            if close <= bb['lower'] and mfi_val <= self.mfi_oversold:
                long_score += 1; long_detail.append("BBMFI-L")
            if close >= bb['upper'] and mfi_val >= self.mfi_overbought:
                short_score += 1; short_detail.append("BBMFI-H")

        return long_score, short_score, long_detail, short_detail

    def _calc_mfi_from(self, closes: list) -> Optional[float]:
        """用给定收盘价之前的 K 线算 MFI（用于趋势比较）"""
        idx = len(closes) - 1
        if idx < self.mfi_period + 1:
            return None
        candles = self.candles[:idx + 1]
        if len(candles) < self.mfi_period + 1:
            return None
        typical = [(c.high + c.low + c.close) / 3.0 for c in candles]
        money_flow = [tp * c.volume for tp, c in zip(typical, candles)]
        pos_flow, neg_flow = 0.0, 0.0
        for i in range(-self.mfi_period, 0):
            if typical[i] > typical[i - 1]:
                pos_flow += money_flow[i]
            else:
                neg_flow += money_flow[i]
        if neg_flow == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + pos_flow / neg_flow)

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[OrderType]:
        candles = self.candles
        if len(candles) < 100:
            logger.debug(f"[{self.name}] 数据不足: {len(candles)} < 100")
            return None

        closes = self.get_close_prices()
        close = closes[-1]

        bb = self._calc_bb_levels()
        if bb is None: return None

        mfi_val = self._calc_mfi()
        if mfi_val is None: return None

        atr_val = self._calc_atr()
        if atr_val is None: return None

        adx_data = self._calc_adx()
        if adx_data is None: return None

        is_trend = adx_data["adx"] >= self.adx_trend_threshold

        # ── Dual-mode scoring ──
        if is_trend:
            long_score, short_score, long_detail, short_detail = self._score_trend_mode(adx_data)
            mode_label = "TREND"
        else:
            long_score, short_score, long_detail, short_detail = self._score_oscillate_mode()
            mode_label = "OSC"

        # ── DI 趋势方向强过滤（趋势模式下反向不做） ──
        pdi, ndi = adx_data["pdi"], adx_data["ndi"]
        if is_trend:
            if pdi > ndi:
                short_score = 0  # 顺势偏多，不做空
            else:
                long_score = 0   # 顺势偏空，不做多

        now = time.time()

        # ── 盈利平仓冷却 ──
        if long_score >= self.score_threshold:
            remaining = self._exit_cooldown_seconds - (now - self._last_profit_exit_time.get("BUY", 0))
            if remaining > 0:
                long_detail.append(f"COOLDOWN({int(remaining)}s)")
                long_score = 0
        if short_score >= self.score_threshold:
            remaining = self._exit_cooldown_seconds - (now - self._last_profit_exit_time.get("SELL", 0))
            if remaining > 0:
                short_detail.append(f"COOLDOWN({int(remaining)}s)")
                short_score = 0

        # ── Decision ──
        signal = None
        signal_str = "无信号"
        if long_score >= self.score_threshold:
            signal = OrderType.BUY
            signal_str = "LONG"
        elif short_score >= self.score_threshold:
            signal = OrderType.SELL
            signal_str = "SELL"

        # ── Logging ──
        detail_parts = []
        if long_detail: detail_parts.append("LONG: " + " ".join(long_detail))
        if short_detail: detail_parts.append("SHORT: " + " ".join(short_detail))
        logger.info(
            f"[{self.name}] [{mode_label}] 评分: {long_score}/{short_score}  {signal_str}  "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )
        adx_log = f" ADX={adx_data['adx']:.1f} DI={pdi:.0f}/{ndi:.0f}"
        logger.info(
            f"[{self.name}] Price={close:.2f} BB={bb['lower']:.2f}/{bb['upper']:.2f} "
            f"MFI={mfi_val:.1f} ATR={atr_val:.2f}{adx_log} 模式={mode_label}"
        )

        bb_range = bb["upper"] - bb["lower"]
        price_position = (close - bb["lower"]) / bb_range if bb_range > 0 else 0.5
        lookback = min(20, len(closes))
        recent_high = max(closes[-lookback:])
        recent_low = min(closes[-lookback:])

        indicator_values = {
            "close": round(close, 2), "mfi": round(mfi_val, 2),
            "atr": round(atr_val, 2), "bb_upper": round(bb["upper"], 2),
            "price_position": round(price_position, 3),
            "recent_high": round(recent_high, 2), "recent_low": round(recent_low, 2),
            "bb_lower": round(bb["lower"], 2), "bb_mid": round(bb["sma"], 2),
            "adx": round(adx_data["adx"], 1),
            "pdi": round(pdi, 1), "ndi": round(ndi, 1),
            "mode": mode_label, "mfi_os": self.mfi_oversold, "mfi_ob": self.mfi_overbought,
        }
        return (signal, long_score, short_score, long_detail, short_detail, indicator_values)

    # ─────────────── Trend-aware exit multipliers ───────────────

    def _get_exit_multipliers(self, is_buy: bool) -> tuple[float, float]:
        trend = self._get_m30_trend()
        if trend == 'UP':
            return (1.5, 3.0) if is_buy else (1.0, 2.0)
        elif trend == 'DOWN':
            return (1.0, 2.0) if is_buy else (1.5, 3.0)
        else:
            return (1.2, 2.5)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        _, hard_mult = self._get_exit_multipliers(direction == OrderType.BUY)
        dist = atr_val * hard_mult
        if direction == OrderType.BUY:
            sl = round(entry_price - dist, 2)
            tp = round(entry_price + dist * 50, 2)
        else:
            sl = round(entry_price + dist, 2)
            tp = round(entry_price - dist * 50, 2)
            if tp <= 0:
                tp = 0
        return sl, tp

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """双重止盈：利润回撤止盈 + ATR移动止盈 + 硬止损"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._trail_data:
            trail_mult, hard_mult = self._get_exit_multipliers(is_buy)
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
                "peak_profit": 0.0,
                "trail_mult": trail_mult,
                "hard_mult": hard_mult,
            }

        td = self._trail_data[ticket]
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return False

        trail_mult = td["trail_mult"]
        hard_mult = td["hard_mult"]
        pdd = self.profit_drawdown_pct
        _ax = self._calc_adx(14)
        if _ax and _ax.get("adx", 0) > 25:
            pdd = max(pdd, 0.5)

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - td["entry"]
            loss = td["entry"] - bid
            td["peak_profit"] = max(td["peak_profit"], current_profit)

            if current_profit > 0:
                if self.profit_drawdown_enabled and td["peak_profit"] > atr_val * self.profit_drawdown_min_peak_atr:
                    profit_ratio = current_profit / td["peak_profit"]
                    if profit_ratio < (1 - pdd):
                        logger.info(f"[{self.name}] BUY ProfitStop ticket={ticket} profit=${current_profit:.2f} peak=${td['peak_profit']:.2f}")
                        self._last_exit_detail = {"exit_type": "profit_drawdown", "peak_profit": round(td["peak_profit"], 2), "current_profit": round(current_profit, 2), "atr": round(atr_val, 2)}
                        self._last_profit_exit_time["BUY"] = time.time()
                        del self._trail_data[ticket]
                        return True

            drawdown = td["highest"] - bid
            if drawdown > atr_val * trail_mult:
                adx_data = self._calc_adx()
                if adx_data and current_profit > 0 and (adx_data["pdi"] - adx_data["ndi"]) > 10:
                    logger.info(f"[{self.name}] BUY DI跳过止盈 ticket={ticket} DIs={adx_data['pdi']-adx_data['ndi']:.1f}")
                else:
                    logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} drawdown={drawdown:.2f} trail={trail_mult}")
                    self._last_exit_detail = {"exit_type": "trail_stop", "direction": "BUY", "drawdown": round(drawdown, 2), "atr": round(atr_val, 2), "trail_mult": trail_mult}
                    self._last_profit_exit_time["BUY"] = time.time()
                    del self._trail_data[ticket]
                    return True

            if current_profit <= 0 and loss > atr_val * hard_mult:
                logger.info(f"[{self.name}] BUY HardStop ticket={ticket} loss={loss:.2f} hard={hard_mult}")
                self._last_exit_detail = {"exit_type": "hard_stop", "direction": "BUY", "loss": round(loss, 2), "atr": round(atr_val, 2), "hard_mult": hard_mult}
                del self._trail_data[ticket]
                return True
        else:
            td["lowest"] = min(td["lowest"], ask)
            current_profit = td["entry"] - ask
            loss = ask - td["entry"]
            td["peak_profit"] = max(td["peak_profit"], current_profit)

            if current_profit > 0:
                if self.profit_drawdown_enabled and td["peak_profit"] > atr_val * self.profit_drawdown_min_peak_atr:
                    profit_ratio = current_profit / td["peak_profit"]
                    if profit_ratio < (1 - pdd):
                        logger.info(f"[{self.name}] SELL ProfitStop ticket={ticket} profit=${current_profit:.2f} peak=${td['peak_profit']:.2f}")
                        self._last_exit_detail = {"exit_type": "profit_drawdown", "peak_profit": round(td["peak_profit"], 2), "current_profit": round(current_profit, 2), "atr": round(atr_val, 2)}
                        self._last_profit_exit_time["SELL"] = time.time()
                        del self._trail_data[ticket]
                        return True

            rally = ask - td["lowest"]
            if rally > atr_val * trail_mult:
                adx_data = self._calc_adx()
                if adx_data and current_profit > 0 and (adx_data["ndi"] - adx_data["pdi"]) > 10:
                    logger.info(f"[{self.name}] SELL DI跳过止盈 ticket={ticket} DIs={adx_data['ndi']-adx_data['pdi']:.1f}")
                else:
                    logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} rally={rally:.2f} trail={trail_mult}")
                    self._last_exit_detail = {"exit_type": "trail_stop", "direction": "SELL", "rally": round(rally, 2), "atr": round(atr_val, 2), "trail_mult": trail_mult}
                    self._last_profit_exit_time["SELL"] = time.time()
                    del self._trail_data[ticket]
                    return True

            if current_profit <= 0 and loss > atr_val * hard_mult:
                logger.info(f"[{self.name}] SELL HardStop ticket={ticket} loss={loss:.2f} hard={hard_mult}")
                self._last_exit_detail = {"exit_type": "hard_stop", "direction": "SELL", "loss": round(loss, 2), "atr": round(atr_val, 2), "hard_mult": hard_mult}
                del self._trail_data[ticket]
                return True

        self._last_exit_detail = None
        return False
