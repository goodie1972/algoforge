"""
M30 BB DeepReturn — 超跌反弹策略
===================================
入场: BB 极值 + MFI 极值 → 超跌反弹
出场: 根据 BB 开口方向与 K 线是否同向分支决策
  - BB 反向（弱反弹）: 0.5 BB带宽 / MFI回超卖线 / 30%利润回撤
  - BB 同向（有动量）: ATR追踪 + BB对侧轨/MFI反向15%

作者: goodie1972
"""
import logging
import math
import time
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 661101
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 661101, "date": "2026-06-29", "desc": "初始上线：BB极值+MFI极值超跌反弹，分支出场"},
]


class BBDeepReturnStrategy(BaseStrategy):
    """M30 BB DeepReturn 超跌反弹策略"""

    name = "m30_bb_deepreturn"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None
        self._extreme_entry_data: dict[int, dict] = {}

        # Entry params
        self.mfi_period = 14
        self.mfi_oversold = 20
        self.mfi_overbought = 80
        self.bb_std = 2.0
        self.bb_period = 20
        self.score_threshold = 3

        # Exit params
        self.atr_period = 20
        self.p_trailing_atr_bull = 1.5   # BB同向时 ATR 追踪乘数（宽一点）
        self.p_trailing_atr_bear = 1.0   # BB反向时 ATR 追踪乘数
        self.p_hard_atr = 2.0
        self.profit_drawdown_pct = 0.30  # BB反向时 30% 利润回撤止盈

        # Exit: BB同向时 MFI 反向阈值
        self.mfi_reversal_pct = 15.0

        # Exit: BB反向时反弹目标
        self.bounce_bb_width = 0.5       # 0.5 个 BB 带宽

        # 盈利平仓冷却
        self._last_profit_exit_time: dict[str, float] = {"BUY": 0.0, "SELL": 0.0}
        self._exit_cooldown_seconds: int = 1800

        # ATR cache
        self._cached_atr_values: Optional[list[float]] = None
        self._cached_atr_key: int = 0

    # ─────────────── Indicator helpers ───────────────

    def get_adx_data(self) -> Optional[dict]:
        return self._calc_adx(14)

    def refresh_data(self, count: int = 350):
        self._cached_atr_key = 0
        self._cached_atr_values = None
        super().refresh_data(count)

    def _calc_sma(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period:
            return None
        return sum(closes[-period:]) / period

    def _calc_ema(self, closes: list[float], period: int) -> Optional[float]:
        if len(closes) < period:
            return None
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
        if len(candles) < period + 2:
            return None
        tr_values = []
        for i in range(1, len(candles)):
            h = candles[i].high
            l_ = candles[i].low
            pc = candles[i - 1].close
            tr = max(h - l_, abs(h - pc), abs(l_ - pc))
            tr_values.append(tr)
        if len(tr_values) < period:
            return None
        atr_list = [sum(tr_values[:period]) / period]
        for i in range(period, len(tr_values)):
            atr_list.append((atr_list[-1] * (period - 1) + tr_values[i]) / period)
        self._cached_atr_values = atr_list
        self._cached_atr_key = cache_key
        return atr_list

    def _calc_atr(self, period: int = 20) -> Optional[float]:
        vals = self._calc_atr_values(period)
        if vals is None or len(vals) == 0:
            return None
        return vals[-1]

    def _calc_bb_levels(self) -> Optional[dict]:
        closes = self.get_close_prices()
        if len(closes) < self.bb_period:
            return None
        recent = closes[-self.bb_period:]
        sma = sum(recent) / self.bb_period
        variance = sum((c - sma) ** 2 for c in recent) / self.bb_period
        std = math.sqrt(variance)
        return {"sma": sma, "upper": sma + self.bb_std * std, "lower": sma - self.bb_std * std}

    def _calc_mfi(self) -> Optional[float]:
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

    def _get_m30_trend(self) -> str:
        closes = self.get_close_prices()
        if len(closes) < 20:
            return 'NEUTRAL'
        ma20 = sum(closes[-20:]) / 20
        return 'UP' if closes[-1] > ma20 else 'DOWN'

    def _calc_adx(self, period: int = 14) -> Optional[dict]:
        candles = self.candles
        if len(candles) < period + 2:
            return None
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = self.get_close_prices()
        n = len(highs)
        tr_list, plus_dm, minus_dm = [], [], []
        for i in range(1, n):
            h, l_, pc = highs[i], lows[i], closes[i - 1]
            ph, pl = highs[i - 1], lows[i - 1]
            tr = max(h - l_, abs(h - pc), abs(l_ - pc))
            up = h - ph
            down = pl - l_
            plus_dm.append(up if (up > down and up > 0) else 0)
            minus_dm.append(down if (down > up and down > 0) else 0)
            tr_list.append(tr)
        if len(tr_list) < period:
            return None
        atr_v = sum(tr_list[:period]) / period
        pdi_v = sum(plus_dm[:period]) / period
        ndi_v = sum(minus_dm[:period]) / period
        if atr_v <= 0:
            return None
        pdi_v = pdi_v / atr_v * 100
        ndi_v = ndi_v / atr_v * 100
        atr_s, pdi_s, ndi_s = [atr_v], [pdi_v], [ndi_v]
        for i in range(period, len(tr_list)):
            atr_s.append((atr_s[-1] * (period - 1) + tr_list[i]) / period)
            if atr_s[-1] > 0:
                pdi_s.append((pdi_s[-1] * (period - 1) + plus_dm[i] / atr_s[-1] * 100) / period)
                ndi_s.append((ndi_s[-1] * (period - 1) + minus_dm[i] / atr_s[-1] * 100) / period)
            else:
                pdi_s.append(pdi_s[-1])
                ndi_s.append(ndi_s[-1])
        dx = [abs(pdi_s[i] - ndi_s[i]) / max(pdi_s[i] + ndi_s[i], 0.001) * 100 for i in range(len(atr_s))]
        adx = [sum(dx[:period]) / period]
        for i in range(period, len(dx)):
            adx.append((adx[-1] * (period - 1) + dx[i]) / period)
        return {"adx": adx[-1], "pdi": pdi_s[-1], "ndi": ndi_s[-1]}

    # ─────────────── BB 方向检测 ───────────────

    def _check_bb_aligned(self, is_buy: bool) -> bool:
        """检测 BB 开口方向是否与 K 线同向（用于出场分支）"""
        closes = self.get_close_prices()
        bb_now = self._calc_bb_levels()
        mfi_now = self._calc_mfi()
        if not bb_now or mfi_now is None or len(closes) < 10:
            return False

        # 比较当前位置 vs 5 根前的 BB 内位置
        bb_range = bb_now["upper"] - bb_now["lower"]
        if bb_range <= 0:
            return False
        curr_pos = (closes[-1] - bb_now["lower"]) / bb_range
        prev_closes = closes[:-5]
        if len(prev_closes) < self.bb_period + 1:
            return False
        prev_bb_lower = sum(sorted(prev_closes[-self.bb_period:])[:self.bb_period//2]) / (self.bb_period//2) if self.bb_period//2 > 0 else bb_now["lower"]
        # 简化: 用5根前的价格位置
        prev_pos = (closes[-5] - bb_now["lower"]) / bb_range

        price_dir = curr_pos > prev_pos  # 价格在 BB 内向上移动
        mfi_prev = self._calc_mfi_from(prev_closes)
        if mfi_prev is None:
            return False
        mfi_dir = mfi_now > mfi_prev

        if is_buy:
            return price_dir and mfi_dir
        else:
            return (not price_dir) and (not mfi_dir)

    # ─────────────── Entry scoring ───────────────

    def generate_signal(self) -> Optional[OrderType]:
        candles = self.candles
        if len(candles) < 100:
            return None

        closes = self.get_close_prices()
        close = closes[-1]

        bb = self._calc_bb_levels()
        if bb is None:
            return None

        mfi_val = self._calc_mfi()
        if mfi_val is None:
            return None

        atr_val = self._calc_atr()
        if atr_val is None:
            return None

        m30_trend = self._get_m30_trend()

        # ── 评分 ──
        long_score = 0
        short_score = 0
        long_detail = []
        short_detail = []

        # ① BB 触轨
        at_lower = close <= bb['lower']
        at_upper = close >= bb['upper']
        if at_lower:
            long_score += 1
            long_detail.append("BB-BOT")
        if at_upper:
            short_score += 1
            short_detail.append("BB-TOP")

        # ② MFI 极端
        mfi_os = mfi_val <= self.mfi_oversold
        mfi_ob = mfi_val >= self.mfi_overbought
        if mfi_os:
            long_score += 1
            long_detail.append(f"MFI-{mfi_val:.0f}")
        elif mfi_ob:
            short_score += 1
            short_detail.append(f"MFI-{mfi_val:.0f}")

        # ③ BB + MFI 共振（同时出现才算超跌反弹核心信号）
        if at_lower and mfi_os:
            long_score += 1
            long_detail.append("BBMFI-L")
        if at_upper and mfi_ob:
            short_score += 1
            short_detail.append("BBMFI-H")

        # ④ MA20 趋势确认
        if m30_trend == 'UP':
            long_score += 1
            long_detail.append("MA20-UP")
        elif m30_trend == 'DOWN':
            short_score += 1
            short_detail.append("MA20-DN")

        # ⑤ MFI 方向（确认拐头）
        if len(closes) >= self.mfi_period + 5:
            mfi_prev = self._calc_mfi_from(closes[:-2])
            if mfi_prev is not None:
                if at_lower and mfi_val > mfi_prev:
                    long_score += 1
                    long_detail.append("MFI-UP")
                elif at_upper and mfi_val < mfi_prev:
                    short_score += 1
                    short_detail.append("MFI-DN")

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
        if long_detail:
            detail_parts.append("LONG: " + " ".join(long_detail))
        if short_detail:
            detail_parts.append("SHORT: " + " ".join(short_detail))
        logger.info(
            f"[{self.name}] 评分: {long_score}/{short_score}  {signal_str}  "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )
        adx_data = self._calc_adx(14)
        adx_log = f" ADX={adx_data['adx']:.1f} DI={adx_data['pdi']:.0f}/{adx_data['ndi']:.0f}" if adx_data else ""
        logger.info(
            f"[{self.name}] Price={close:.2f} BB={bb['lower']:.2f}/{bb['upper']:.2f} "
            f"MFI={mfi_val:.1f} ATR={atr_val:.2f}{adx_log}"
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
            "mfi_os": self.mfi_oversold, "mfi_ob": self.mfi_overbought,
        }
        if adx_data:
            indicator_values.update({
                "adx": round(adx_data["adx"], 1),
                "pdi": round(adx_data["pdi"], 1),
                "ndi": round(adx_data["ndi"], 1),
            })
        return (signal, long_score, short_score, long_detail, short_detail, indicator_values)

    # ─────────────── Entry tracking (引擎调用) ───────────────

    def mark_extreme_entry(self, ticket: int | str):
        """引擎开仓后调用，记录极值入场时的指标快照"""
        sig = getattr(self, '_last_signal', None) or {}
        iv = sig.get('indicator_values', {})
        if not iv:
            return
        mfi = iv.get('mfi', 50)
        close = iv.get('close', 0)
        bb_lower = iv.get('bb_lower', 0)
        bb_upper = iv.get('bb_upper', 0)

        is_extreme = (close <= bb_lower * 1.005 and mfi <= self.mfi_oversold) or \
                     (close >= bb_upper * 0.995 and mfi >= self.mfi_overbought)
        if not is_extreme:
            return

        self._extreme_entry_data[ticket] = {
            "entry_mfi": mfi,
            "bb_range": bb_upper - bb_lower,
        }
        logger.info(f"[{self.name}] 标记极值进场 ticket={ticket} MFI={mfi:.1f}")

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        dist = atr_val * self.p_hard_atr
        if direction == OrderType.BUY:
            sl = round(entry_price - dist, 2)
            tp = round(entry_price + dist * 50, 2)
        else:
            sl = round(entry_price + dist, 2)
            tp = round(entry_price - dist * 50, 2)
            if tp <= 0:
                tp = 0
        return sl, tp

    # ─────────────── Exit logic ───────────────

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """
        分支出场逻辑:
        - BB同向: ATR 追踪 + BB对侧轨 / MFI反向15%
        - BB反向: 0.5 BB带宽反弹 / MFI跨超卖线 / 30%利润回撤
        """
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        # ── 初始化 trail data ──
        if ticket not in self._trail_data:
            td = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
                "peak_profit": 0.0,
            }
            if ticket in self._extreme_entry_data:
                ed = self._extreme_entry_data.pop(ticket)
                td.update(ed)
                td["is_extreme"] = True
                td["peak_mfi"] = ed.get("entry_mfi", 50)
                td["valley_mfi"] = ed.get("entry_mfi", 50)
            self._trail_data[ticket] = td

        td = self._trail_data[ticket]
        atr_val = self._calc_atr()
        if atr_val is None or atr_val <= 0:
            return False

        # ── 更新追踪数据 ──
        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - td["entry"]
            loss = td["entry"] - bid
            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)
            # 追踪 MFI 峰值（用于反向检测）
            mfi_now = self._calc_mfi()
            if mfi_now is not None:
                td["peak_mfi"] = max(td.get("peak_mfi", mfi_now), mfi_now)
        else:
            td["lowest"] = min(td["lowest"], ask)
            current_profit = td["entry"] - ask
            loss = ask - td["entry"]
            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)
            mfi_now = self._calc_mfi()
            if mfi_now is not None:
                td["valley_mfi"] = min(td.get("valley_mfi", mfi_now), mfi_now)

        # ── 极值进场 → 分支出场 ──
        if td.get("is_extreme"):
            bb_now = self._calc_bb_levels()
            mfi_now = self._calc_mfi()
            if bb_now and mfi_now is not None:
                bb_range = bb_now["upper"] - bb_now["lower"]
                bb_aligned = self._check_bb_aligned(is_buy)

                if not bb_aligned:
                    # ═══ 场景 A: BB反向（弱反弹）═══
                    # ① 反弹 0.5 BB 带宽
                    bounce_target = td["entry"] + bb_range * self.bounce_bb_width if is_buy \
                                    else td["entry"] - bb_range * self.bounce_bb_width
                    if (is_buy and bid >= bounce_target) or (not is_buy and ask <= bounce_target):
                        logger.info(f"[{self.name}] BB反向反弹止盈 ticket={ticket} "
                                     f"{'BUY' if is_buy else 'SELL'} target={bounce_target:.2f}")
                        self._last_exit_detail = {"exit_type": "bounce_tp", "target": round(bounce_target, 2)}
                        self._on_exit(ticket, is_buy)
                        return True

                    # ② MFI 跨过超卖线
                    if (is_buy and mfi_now > self.mfi_oversold) or \
                       (not is_buy and mfi_now < self.mfi_overbought):
                        logger.info(f"[{self.name}] BB反向 MFI回线止盈 ticket={ticket} "
                                     f"MFI={mfi_now:.1f} 阈值={'<20' if not is_buy else '>80'}")
                        self._last_exit_detail = {"exit_type": "mfi_cross", "mfi": round(mfi_now, 1)}
                        self._on_exit(ticket, is_buy)
                        return True

                    # ③ 30% 利润回撤止盈
                    if current_profit > 0 and td.get("peak_profit", 0) > atr_val * 0.5:
                        profit_ratio = current_profit / td["peak_profit"]
                        if profit_ratio < (1 - self.profit_drawdown_pct):
                            logger.info(f"[{self.name}] BB反向利润回撤止盈 ticket={ticket} "
                                         f"profit=${current_profit:.2f} peak=${td['peak_profit']:.2f}")
                            self._last_exit_detail = {"exit_type": "profit_drawdown_30",
                                                       "peak": round(td["peak_profit"], 2),
                                                       "current": round(current_profit, 2)}
                            self._on_exit(ticket, is_buy)
                            return True
                else:
                    # ═══ 场景 B: BB同向（有动量）═══
                    # 通道1: BB 对侧轨止盈
                    if is_buy and bid >= bb_now["upper"]:
                        logger.info(f"[{self.name}] BB同向上轨止盈 ticket={ticket} bid={bid:.2f} BB_U={bb_now['upper']:.2f}")
                        self._last_exit_detail = {"exit_type": "bb_band_tp", "band": "upper"}
                        self._on_exit(ticket, is_buy)
                        return True
                    if not is_buy and ask <= bb_now["lower"]:
                        logger.info(f"[{self.name}] BB同向下轨止盈 ticket={ticket} ask={ask:.2f} BB_L={bb_now['lower']:.2f}")
                        self._last_exit_detail = {"exit_type": "bb_band_tp", "band": "lower"}
                        self._on_exit(ticket, is_buy)
                        return True

                    # 通道2: MFI 反向 15% 止盈
                    if is_buy and td.get("peak_mfi", mfi_now) > mfi_now:
                        mfi_drop = (td["peak_mfi"] - mfi_now) / max(td["peak_mfi"], 1) * 100
                        if mfi_drop >= self.mfi_reversal_pct:
                            logger.info(f"[{self.name}] BB同向 MFI反向止盈 ticket={ticket} "
                                         f"peak_mfi={td['peak_mfi']:.1f} now={mfi_now:.1f} drop={mfi_drop:.0f}%")
                            self._last_exit_detail = {"exit_type": "mfi_reversal", "drop_pct": round(mfi_drop, 1)}
                            self._on_exit(ticket, is_buy)
                            return True
                    if not is_buy and td.get("valley_mfi", mfi_now) < mfi_now:
                        mfi_rise = (mfi_now - td["valley_mfi"]) / max(mfi_now, 1) * 100
                        if mfi_rise >= self.mfi_reversal_pct:
                            logger.info(f"[{self.name}] BB同向 MFI反向止盈 ticket={ticket} "
                                         f"valley_mfi={td['valley_mfi']:.1f} now={mfi_now:.1f} rise={mfi_rise:.0f}%")
                            self._last_exit_detail = {"exit_type": "mfi_reversal", "rise_pct": round(mfi_rise, 1)}
                            self._on_exit(ticket, is_buy)
                            return True

                    # 通道3: ATR 追踪止盈（兜底）
                    if is_buy:
                        drawdown = td["highest"] - bid
                        if drawdown > atr_val * self.p_trailing_atr_bull:
                            logger.info(f"[{self.name}] BB同向 ATR追踪止盈 ticket={ticket} "
                                         f"drawdown={drawdown:.2f} trail={self.p_trailing_atr_bull}")
                            self._last_exit_detail = {"exit_type": "atr_trail", "drawdown": round(drawdown, 2)}
                            self._on_exit(ticket, is_buy)
                            return True
                    else:
                        rally = ask - td["lowest"]
                        if rally > atr_val * self.p_trailing_atr_bull:
                            logger.info(f"[{self.name}] BB同向 ATR追踪止盈 ticket={ticket} "
                                         f"rally={rally:.2f} trail={self.p_trailing_atr_bull}")
                            self._last_exit_detail = {"exit_type": "atr_trail", "rally": round(rally, 2)}
                            self._on_exit(ticket, is_buy)
                            return True

        # ── 非极值 / 兜底: 硬止损 ──
        if is_buy:
            if loss > atr_val * self.p_hard_atr:
                logger.info(f"[{self.name}] HardStop BUY ticket={ticket} loss={loss:.2f}")
                self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss, 2)}
                self._on_exit(ticket, is_buy)
                return True
        else:
            if loss > atr_val * self.p_hard_atr:
                logger.info(f"[{self.name}] HardStop SELL ticket={ticket} loss={loss:.2f}")
                self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss, 2)}
                self._on_exit(ticket, is_buy)
                return True

        self._last_exit_detail = None
        return False

    def _on_exit(self, ticket: int, is_buy: bool):
        """出场清理"""
        direction = "BUY" if is_buy else "SELL"
        self._last_profit_exit_time[direction] = time.time()
        self._trail_data.pop(ticket, None)
