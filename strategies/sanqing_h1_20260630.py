"""
SanQing EA — H1 实盘策略
======================
- EMA9/21 趋势 + ATR14 评分系统
- 评分阈值: ADX>20 趋势中=4, ADX≤20=3, 触发 BUY/SELL
- ATR动态追踪止损出场
数据源: 全部指标从 DataFactory TA-Lib 读取
"""

import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v7"
STRATEGY_MAGIC = 880107
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 880101, "date": "2026-06-08", "desc": "初始上线：6因子评分≥5，ATR跟踪止损 trail=4.0 hard=2.5"},
    {"version": "v2", "magic": 880102, "date": "2026-06-08", "desc": "修复出场逻辑：区分盈利/亏损阶段，新增 peak_profit 跟踪"},
    {"version": "v3", "magic": 880103, "date": "2026-06-09", "desc": "双重止盈：trail=1.0 hard=2.0，新增 profit_drawdown_pct=0.25，新增 indicator_values 返回"},
    {"version": "v4", "magic": 880104, "date": "2026-06-11", "desc": "新增 tight_exit_mode 新闻风控"},
    {"version": "v5", "magic": 880105, "date": "2026-06-11", "desc": "位置门禁：60根K线区间底部10%禁空、顶部10%禁多"},
    {"version": "v6", "magic": 880106, "date": "2026-06-12", "desc": "自适应回撤止盈：微利单profit_drawdown按peak_profit占比ATR动态放松至50%/40%"},
    {"version": "v6r", "magic": 880106, "date": "2026-06-21", "desc": "回退v6纯顺趋势逻辑，去掉逆势因子；顺趋势出场加宽至trail=2.5 hard=4.0"},
    {"version": "v7", "magic": 880107, "date": "2026-06-22", "desc": "ADX>25 趋势中阈值从5降到4；ADX≤25保持阈值5"},
]


class SanQingH1Strategy(BaseStrategy):
    """SanQing EA — H1 EMA9/21 + ATR14 评分系统"""

    name = "sanqing_h1"

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None

        # Entry params
        self.score_threshold = 3

        # ADX>20 趋势中阈值=4；ADX≤20 保持阈值=3
        self.adx_threshold = 20

        # Exit params — 双重止盈：利润回撤25% + ATR移动止盈 + 硬止损
        self.p_trailing_atr = 1.0   # 回调超过 1 ATR 即止盈（原为 4.0）
        self.p_hard_atr = 2.0    # 硬止损 ATR×2（原为 2.5）
        # profit_drawdown_pct 继承自 BaseStrategy（默认 0.25，由 settings.py 控制）

        # EMA 交叉检测：记录上一次的值（来自 DataFactory）
        self._prev_ema9: float = 0.0
        self._prev_ema21: float = 0.0

    def get_adx_data(self) -> Optional[dict]:
        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        if adx is None:
            return None
        return {"adx": adx, "pdi": pdi, "ndi": ndi}

    def refresh_data(self, count: int = 200):
        super().refresh_data(count)

    # ─────────────── K线数据提取 ───────────────

    def _get_opens(self) -> list[float]:
        return [c.open for c in self.candles]

    def _get_highs(self) -> list[float]:
        return [c.high for c in self.candles]

    def _get_lows(self) -> list[float]:
        return [c.low for c in self.candles]

    def _get_volumes(self) -> list[float]:
        return [c.volume for c in self.candles]

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[OrderType]:
        candles = self.candles
        if len(candles) < 60:
            return None

        closes = self.get_close_prices()
        highs = self._get_highs()
        lows = self._get_lows()
        opens_ = self._get_opens()
        volumes = self._get_volumes()

        close = closes[-1]
        high = highs[-1]
        low = lows[-1]
        volume = volumes[-1] if len(volumes) > 0 else 0

        # EMA9/21（全部从 DataFactory 读取）
        ema9 = self.get_indicator("ema_9")
        ema21 = self.get_indicator("ema_21")
        if ema9 is None or ema21 is None:
            return None
        ema9_p = self._prev_ema9
        ema21_p = self._prev_ema21
        self._prev_ema9 = ema9
        self._prev_ema21 = ema21

        uptrend = ema9 > ema21
        downtrend = ema9 < ema21
        cross_up = ema9_p > 0 and ema21_p > 0 and ema9_p <= ema21_p and ema9 > ema21
        cross_dn = ema9_p > 0 and ema21_p > 0 and ema9_p >= ema21_p and ema9 < ema21

        # ATR
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return None

        # ADX — 趋势中阈值动态放宽
        adx = self.get_indicator("adx")
        adx_data = {"adx": adx, "pdi": self.get_indicator("pdi"), "ndi": self.get_indicator("ndi")}
        effective_threshold = 4 if (adx is not None and adx > self.adx_threshold) else self.score_threshold

        # Body analysis
        body = abs(close - opens_[-1])
        candle_range = high - low
        body_atr_ratio = body / atr_val if atr_val > 0 else 0

        # Body median ratio
        n = len(closes)
        recent_bodies = [abs(closes[j] - opens_[j]) for j in range(max(0, n - 21), n)]
        body_median = sorted(recent_bodies)[len(recent_bodies) // 2] if recent_bodies else 1
        body_median_ratio = body / body_median if body_median > 0 else 0
        prev_bodies = [abs(closes[j] - opens_[j]) for j in range(max(0, n - 6), n - 1)]
        prev_body_max = max(prev_bodies) if prev_bodies else 1

        # Volume average
        avg_vol = sum(volumes[max(0, n - 21):n]) / min(20, n) if n >= 5 else 0

        # ── BUY scoring ──
        buy_score = 0
        if uptrend:
            buy_score += 2
        elif cross_up:
            buy_score += 1
        if low <= ema9 * 1.002 and close > ema9:
            buy_score += 2
        if body_atr_ratio > 1.0:
            buy_score += 1
        if avg_vol > 0 and volume > avg_vol * 1.3:
            buy_score += 1
        if (body_median_ratio >= 1.5 and body / prev_body_max >= 1.5
                and candle_range > 0 and body / candle_range >= 0.5):
            buy_score += 2

        # ── SELL scoring ──
        sell_score = 0
        if downtrend:
            sell_score += 2
        elif cross_dn:
            sell_score += 1
        if high >= ema9 * 0.998 and close < ema9:
            sell_score += 2
        if body_atr_ratio > 1.0:
            sell_score += 1
        if avg_vol > 0 and volume > avg_vol * 1.3:
            sell_score += 1
        if (body_median_ratio >= 1.5 and body / prev_body_max >= 1.5
                and candle_range > 0 and body / candle_range >= 0.5):
            sell_score += 2

        adx_str = f" ADX={adx_data['adx']:.1f}" if adx_data else ""
        logger.info(
            f"[{self.name}] 评分: BUY={buy_score} SELL={sell_score} "
            f"Price={close:.2f} EMA9={ema9:.2f} EMA21={ema21:.2f} ATR={atr_val:.2f}{adx_str}"
            f" 阈值={effective_threshold}"
        )

        # 构建因子明细
        long_factors = []
        if uptrend: long_factors.append("EMA-UP")
        elif cross_up: long_factors.append("EMA-CROSS-UP")
        if low <= ema9 * 1.002 and close > ema9: long_factors.append("TOUCH-EMA9")
        if body_atr_ratio > 1.0: long_factors.append("BODY-ATR")
        if avg_vol > 0 and volume > avg_vol * 1.3: long_factors.append("HIGH-VOL")
        if body_median_ratio >= 1.5 and body / prev_body_max >= 1.5 and candle_range > 0 and body / candle_range >= 0.5:
            long_factors.append("ENGULF")

        short_factors = []
        if downtrend: short_factors.append("EMA-DN")
        elif cross_dn: short_factors.append("EMA-CROSS-DN")
        if high >= ema9 * 0.998 and close < ema9: short_factors.append("TOUCH-EMA9")
        if body_atr_ratio > 1.0: short_factors.append("BODY-ATR")
        if avg_vol > 0 and volume > avg_vol * 1.3: short_factors.append("HIGH-VOL")
        if body_median_ratio >= 1.5 and body / prev_body_max >= 1.5 and candle_range > 0 and body / candle_range >= 0.5:
            short_factors.append("ENGULF")

        # ── Position gate: 极端位置不做逆势交易 ──
        n_candles = len(candles)
        lookback = min(60, n_candles)
        recent_high = max(c.high for c in candles[-lookback:])
        recent_low = min(c.low for c in candles[-lookback:])
        price_position = (close - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5

        if price_position < 0.10 and sell_score >= effective_threshold:
            short_factors.append("BOTTOM-GATE")
            logger.info(f"[{self.name}] 位置门禁: 价格在区间底部 {price_position:.1%}，禁止SELL (原分={sell_score})")
            sell_score = 0
        elif price_position > 0.90 and buy_score >= effective_threshold:
            long_factors.append("TOP-GATE")
            logger.info(f"[{self.name}] 位置门禁: 价格在区间顶部 {price_position:.1%}，禁止BUY (原分={buy_score})")
            buy_score = 0

        indicator_values = {
            "close": round(close, 2), "ema9": round(ema9, 2), "ema21": round(ema21, 2),
            "atr": round(atr_val, 2), "body_atr_ratio": round(body_atr_ratio, 2),
            "volume_ratio": round(volume / avg_vol, 2) if avg_vol > 0 else 0,
            "body_median_ratio": round(body_median_ratio, 2),
            "price_position": round(price_position, 3),
            "recent_high": round(recent_high, 2), "recent_low": round(recent_low, 2),
            "adx": round(adx_data["adx"], 1) if adx_data else None,
            "pdi": round(adx_data["pdi"], 1) if adx_data else None,
            "ndi": round(adx_data["ndi"], 1) if adx_data else None,
        }

        signal = None
        if buy_score >= effective_threshold:
            signal = OrderType.BUY
        elif sell_score >= effective_threshold:
            signal = OrderType.SELL
        return (signal, buy_score, sell_score, long_factors, short_factors, indicator_values)

    # ─────────────── Trend-aware exit multipliers ───────────────

    def _get_trend(self) -> str:
        """EMA9/21 trend: 'UP' / 'DOWN' / 'NEUTRAL'"""
        ema9 = self.get_indicator("ema_9")
        ema21 = self.get_indicator("ema_21")
        if ema9 is None or ema21 is None:
            return 'NEUTRAL'
        return 'UP' if ema9 > ema21 else 'DOWN'

    def _get_exit_multipliers(self, is_buy: bool) -> tuple[float, float]:
        trend = self._get_trend()
        if trend == 'UP':
            return (2.5, 4.0) if is_buy else (1.0, 2.0)
        elif trend == 'DOWN':
            return (1.0, 2.0) if is_buy else (2.5, 4.0)
        else:
            return (1.5, 3.0)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        _, hard_mult = self._get_exit_multipliers(direction == OrderType.BUY)
        dist = atr_val * hard_mult
        if direction == OrderType.BUY:
            return round(entry_price - dist, 2), round(entry_price + dist * 50, 2)
        else:
            tp = round(entry_price - dist * 50, 2)
            if tp <= 0:
                tp = 0
            return round(entry_price + dist, 2), tp

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """双重止盈：利润回撤止盈 + ATR移动止盈 + 硬止损"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._trail_data:
            # 锁定开仓时的趋势方向，后续不受 EMA9/21 翻转影响
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
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return False

        trail_mult = td["trail_mult"]
        hard_mult = td["hard_mult"]
        pdd = self.profit_drawdown_pct

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - td["entry"]
            loss = td["entry"] - bid
            if abs(current_profit) < atr_val * 10:
                td["peak_profit"] = max(td["peak_profit"], current_profit)

            # 保本出场：走过≥0.3ATR盈利后回到成本附近
            if self._check_breakeven_exit(td, current_profit, atr_val, td["entry"], is_buy):
                logger.info(f"[{self.name}] BUY Breakeven ticket={ticket} profit=${current_profit:.2f}")
                self._last_exit_detail = {"exit_type": "breakeven", "profit": round(current_profit, 2)}
                self._last_profit_exit_time["BUY"] = time.time()
                del self._trail_data[ticket]
                return True

            if current_profit > 0:
                # 盈利 → 止盈逻辑
                if self.profit_drawdown_enabled and td["peak_profit"] > atr_val * self.profit_drawdown_min_peak_atr:
                    # 自适应回撤: 微利单给更多浮动空间
                    if td["peak_profit"] < atr_val * 1.0:
                        pdd_used = 0.5
                    elif td["peak_profit"] < atr_val * 2.0:
                        pdd_used = 0.4
                    else:
                        pdd_used = pdd
                        # ADX>25 趋势强 → 放宽回撤
                        if pdd_used < 0.5:
                            _ax_adx = self.get_indicator("adx")
                            if _ax_adx and _ax_adx > 25:
                                pdd_used = 0.5
                    profit_ratio = current_profit / td["peak_profit"]
                    if profit_ratio < (1 - pdd_used):
                        logger.info(
                            f"[{self.name}] BUY ProfitStop ticket={ticket} "
                            f"profit ${current_profit:.2f} peak ${td['peak_profit']:.2f} pdd={pdd_used:.0%}"
                        )
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

            # 保本出场：走过≥0.3ATR盈利后回到成本附近
            if self._check_breakeven_exit(td, current_profit, atr_val, td["entry"], is_buy):
                logger.info(f"[{self.name}] SELL Breakeven ticket={ticket} profit=${current_profit:.2f}")
                self._last_exit_detail = {"exit_type": "breakeven", "profit": round(current_profit, 2)}
                self._last_profit_exit_time["SELL"] = time.time()
                del self._trail_data[ticket]
                return True

            if current_profit > 0:
                # 盈利 → 止盈逻辑
                if self.profit_drawdown_enabled and td["peak_profit"] > atr_val * self.profit_drawdown_min_peak_atr:
                    # 自适应回撤: 微利单给更多浮动空间
                    if td["peak_profit"] < atr_val * 1.0:
                        pdd_used = 0.5
                    elif td["peak_profit"] < atr_val * 2.0:
                        pdd_used = 0.4
                    else:
                        pdd_used = pdd
                        # ADX>25 趋势强 → 放宽回撤
                        if pdd_used < 0.5:
                            _ax_adx = self.get_indicator("adx")
                            if _ax_adx and _ax_adx > 25:
                                pdd_used = 0.5
                    profit_ratio = current_profit / td["peak_profit"]
                    if profit_ratio < (1 - pdd_used):
                        logger.info(
                            f"[{self.name}] SELL ProfitStop ticket={ticket} "
                            f"profit ${current_profit:.2f} peak ${td['peak_profit']:.2f} pdd={pdd_used:.0%}"
                        )
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
