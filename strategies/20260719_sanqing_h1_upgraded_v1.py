"""
SanQing EA v9_upgraded — H1 实盘strategy升级版
===========================================
- EMA9/21 趋-trend + ATR14 Score系统（保留原Score逻辑）
- Scorethreshold: ADX>20=4, ADX≤20=3
- 运动员等回抽 EMA9 Entry
- DI 方向保护 profitdrawdown + 硬止损/take profit + DI反转出场
data源: all指标从 DataFactory TA-Lib read
"""
import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v9_upgraded"
STRATEGY_MAGIC = 880108
STRATEGY_LEGACY_MAGICS: list[int] = [880102, 880103, 880104, 880105, 880106]
STRATEGY_CHANGELOG = [
    {"version": "v11_dynamic_dd", "magic": 880108, "date": "2026-08-11",
     "desc": "趋势保护下强制止盈改为动态阈值：盈利>10时回撤30%止盈（原50%），保护大盈利；≤10保持50%；不满足趋势保护时保持原逻辑不变"},
    {"version": "v10_optimized", "magic": 880108, "date": "2026-08-08",
     "desc": "optimize版: Scorethreshold3→5, ADXthreshold20→25, 硬止损1.5→1.2ATR"},
    {"version": "v9_upgraded", "magic": 880108, "date": "2026-07-21",
     "desc": "ADX自适应出场: 强趋-trend放宽trailing/take profit让profit跑, 震荡收紧, 新增trailing止损"},
]


class SanQingH1Upgraded(BaseStrategy):
    """SanQing v9_upgraded — ADX自适应出场"""

    name = "sanqing_h1_upgraded"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None

        # Scorethreshold
        self.score_threshold = 5
        self.adx_threshold = 25          # ADX>25 趋-trend threshold升到 4

        # Exit params
        # profit_drawdown_pct 继承自 BaseStrategy（default 0.25）
        # DI 方向保护：profit_drawdown 方向一致时不exec
        self._drawdown_min_hold = 1800  # profitdrawdownminPositions：30 min（H1 strategy，给趋-trend发展时间）
        # ADX 自适应出场param
        self.p_trail_chop = 1.5         # 震荡: 窄trailing
        self.p_trail_normal = 2.5       #  等: 正常trailing
        self.p_trail_trend = 3.5        # 强趋-trend: 宽trailing让profit跑
        self.p_profit_chop = 2.5        # 震荡: 小目标落袋
        self.p_profit_normal = 4.0      #  等: 正常take profit
        self.p_profit_trend = 6.0       # 强趋-trend: 大目标让profit跑
        self.p_hard_atr = 1.2           # 硬止损: 固定 1.2 ATR（最后防线）

        # EMA 交叉检测：record上一次 值（来自 DataFactory）
        self._prev_ema9: float = 0.0
        self._prev_ema21: float = 0.0

    def get_adx_data(self) -> Optional[dict]:
        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        if adx is None:
            return None
        return {"adx": adx, "pdi": pdi, "ndi": ndi}

    def refresh_data(self, count: int = 300):
        super().refresh_data(count)

    # ─────────────── 指标 ───────────────

    # ─────────────── K线data提取 ───────────────

    def _get_opens(self) -> list[float]:
        return [c.open for c in self.candles]

    def _get_highs(self) -> list[float]:
        return [c.high for c in self.candles]

    def _get_lows(self) -> list[float]:
        return [c.low for c in self.candles]

    def _get_volumes(self) -> list[float]:
        return [c.volume for c in self.candles]

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
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

        # EMA9/21（all从 DataFactory read）
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

        # ATR/ADX
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return None
        adx = self.get_indicator("adx")
        effective_threshold = 4 if (adx is not None and adx > self.adx_threshold) else self.score_threshold

        # K线实体
        body = abs(close - opens_[-1])
        candle_range = high - low
        body_atr_ratio = body / atr_val if atr_val > 0 else 0

        # 实体 位数
        n = len(closes)
        recent_bodies = [abs(closes[j] - opens_[j]) for j in range(max(0, n - 21), n)]
        body_median = sorted(recent_bodies)[len(recent_bodies) // 2] if recent_bodies else 1
        body_median_ratio = body / body_median if body_median > 0 else 0
        prev_bodies = [abs(closes[j] - opens_[j]) for j in range(max(0, n - 6), n - 1)]
        prev_body_max = max(prev_bodies) if prev_bodies else 1

        # 均量
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

        adx_str = f" ADX={adx:.1f}" if adx else ""

        # ── SteepMA 趋-trendfilter ──
        steep_dir = self._steep_ma_direction(period=14, lookback=5)
        if steep_dir == "UP":
            buy_score += 1
        elif steep_dir == "DOWN":
            sell_score += 1
        if steep_dir != "NEUTRAL":
            logger.info(f"[{self.name}] SteepMA: {steep_dir}")

        logger.info(
            f"[{self.name}] Score: BUY={buy_score} SELL={sell_score} "
            f"Price={close:.2f} EMA9={ema9:.2f} EMA21={ema21:.2f} ATR={atr_val:.2f}"
            f"{adx_str} threshold={effective_threshold}"
        )

        # 因子明细
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
        if steep_dir == "UP": long_factors.append("STEEP-UP")
        elif steep_dir == "DOWN": short_factors.append("STEEP-DN")

        # positionGate（高位/低位拦截，含 EMA21 偏离确认）
        lookback = min(60, len(candles))
        recent_high = max(c.high for c in candles[-lookback:])
        recent_low = min(c.low for c in candles[-lookback:])
        price_position = (close - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5
        _dev = (close - ema21) / atr_val if atr_val > 0 else 0  # 偏离 EMA21 倍数

        # 高位拦截：price_position > 0.88 且 偏离 EMA21 > 4×ATR → 禁 BUY 追高，但允许 SELL
        if price_position > 0.82 and _dev > 2.5:
            long_factors.append("TOP-GATE")
            logger.info(f"[{self.name}] positionGate: top {price_position:.1%} dev={_dev:.1f}×ATR，blockBUY")
            buy_score = 0
        # 低位拦截：price_position < 0.12 且 偏离 < -4×ATR → 禁 SELL 抄底，但允许 BUY
        elif price_position < 0.18 and _dev < -2.5:
            short_factors.append("BOTTOM-GATE")
            logger.info(f"[{self.name}] positionGate: bottom {price_position:.1%} dev={_dev:.1f}×ATR，blockSELL")
            sell_score = 0

        iv = {
            "close": round(close, 2), "ema9": round(ema9, 2), "ema21": round(ema21, 2),
            "atr": round(atr_val, 2), "body_atr_ratio": round(body_atr_ratio, 2),
            "volume_ratio": round(volume / avg_vol, 2) if avg_vol > 0 else 0,
            "body_median_ratio": round(body_median_ratio, 2),
            "price_position": round(price_position, 3),
            "adx": round(adx, 1) if adx else 0,
            "pdi": self.get_indicator("pdi") or 0,
            "ndi": self.get_indicator("ndi") or 0,
        }

        signal = None
        if buy_score >= effective_threshold:
            signal = OrderType.BUY
        elif sell_score >= effective_threshold:
            signal = OrderType.SELL
        return (signal, buy_score, sell_score, long_factors, short_factors, iv)

    # ─────────────── SL/TP ───────────────

    def _get_adx_multipliers(self) -> tuple[float, float]:
        """ADX 自适应：return (trail_atr, profit_atr)"""
        adx = self.get_indicator("adx")
        if adx is None or adx <= 25:
            return self.p_trail_chop, self.p_profit_chop
        if adx > 35:
            return self.p_trail_trend, self.p_profit_trend
        return self.p_trail_normal, self.p_profit_normal

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        is_buy = direction == OrderType.BUY
        sl_mult = self.p_hard_atr
        sl_dist = atr_val * sl_mult
        _, tp_mult = self._get_adx_multipliers()
        tp_dist = atr_val * tp_mult
        if is_buy:
            return round(entry_price - sl_dist, 2), round(entry_price + tp_dist, 2)
        else:
            tp = round(entry_price - tp_dist, 2)
            if tp <= 0:
                tp = 0
            return round(entry_price + sl_dist, 2), tp

    # ─────────────── 出场 ───────────────

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """v9 ADX自适应出场"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        # 确保指标缓存update（_run_exits 在 _run_strategy 之前调用）
        self.refresh_data()

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "entry": position.open_price,
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "peak_profit": 0.0,
                "entry_ts": time.time(),
            }

        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return False

        trail_mult, tp_mult = self._get_adx_multipliers()
        pnl_pts = (bid - td["entry"]) if is_buy else (td["entry"] - ask)
        loss_pts = (td["entry"] - bid) if is_buy else (ask - td["entry"])

        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        di_aligned = (is_buy and pdi is not None and ndi is not None and pdi > ndi) or (not is_buy and pdi is not None and ndi is not None and ndi > pdi)

        if is_buy:
            td["highest"] = max(td["highest"], bid)
        else:
            td["lowest"] = min(td["lowest"], ask)
        if pnl_pts > 0:
            td["peak_profit"] = max(td["peak_profit"], pnl_pts)

        side = "BUY" if is_buy else "SELL"

        # (1) Trail stop
        if is_buy:
            d = td["highest"] - bid
            if d > atr_val * trail_mult:
                logger.info(f"[{self.name}] {side} TrailStop ticket={ticket} dd={d:.2f} m={trail_mult:.1f}")
                del self._trail_data[ticket]
                return True
        else:
            r = ask - td["lowest"]
            if r > atr_val * trail_mult:
                logger.info(f"[{self.name}] {side} TrailStop ticket={ticket} rally={r:.2f} m={trail_mult:.1f}")
                del self._trail_data[ticket]
                return True

        # (2) Take profit
        if pnl_pts > atr_val * tp_mult:
            logger.info(f"[{self.name}] {side} TP ticket={ticket} p=${pnl_pts:.2f} m={tp_mult:.1f}")
            del self._trail_data[ticket]
            return True

        # (3) Hard stop
        if loss_pts > atr_val * self.p_hard_atr:
            logger.info(f"[{self.name}] {side} HardStop ticket={ticket} loss={loss_pts:.2f}")
            del self._trail_data[ticket]
            return True

        # (4) Drawdown protection
        if pnl_pts > 0 and self.profit_drawdown_enabled and td["peak_profit"] > atr_val * self.profit_drawdown_min_peak_atr:
            ratio = pnl_pts / td["peak_profit"]
            peak = td["peak_profit"]
            # 动态强制止盈阈值（仅趋势保护 di_aligned 时使用）：
            # 盈利≤10 → 回撤50%强制；盈利>10 → 回撤30%强制（保护大盈利）
            forced_ratio = 0.50 if peak <= 10 else 0.35
            if ratio < (1 - self.profit_drawdown_pct):
                if time.time() - td.get("entry_ts", 0) < self._drawdown_min_hold:
                    logger.info(f"[{self.name}] {side} dd skip: hold < {self._drawdown_min_hold//60}min")
                elif di_aligned and adx is not None and adx > 20:
                    # 趋势保护满足：让利润跑，仅回撤超过动态阈值时才强制止盈
                    if ratio < forced_ratio:
                        logger.info(f"[{self.name}] {side} forced ProfitStop(dd>{1-forced_ratio:.0%}) t={ticket} p=${pnl_pts:.2f} peak=${td["peak_profit"]:.2f}")
                        del self._trail_data[ticket]
                        return True
                    logger.info(f"[{self.name}] {side} dd skip: DI aligned ADX={adx:.1f}")
                else:
                    logger.info(f"[{self.name}] {side} ProfitStop t={ticket} p=${pnl_pts:.2f} peak=${td["peak_profit"]:.2f}")
                    del self._trail_data[ticket]
                    return True

        # (5) DI flip — 加1 candlesK线confirm缓冲，防止频繁翻转
        if pdi is not None and ndi is not None and time.time() - td["entry_ts"] > 300:
            di_flip_detected = (is_buy and ndi > pdi) or (not is_buy and pdi > ndi)
            if di_flip_detected:
                # check是否在上一tick检测到DI flip（使用currentcandle计数）
                current_candle = len(self.candles)
                last_flip_candle = td.get("_di_flip_candle", 0)
                if last_flip_candle == 0:
                    #  一次检测到DI flip，recordcandle编号，waitconfirm
                    td["_di_flip_candle"] = current_candle
                    logger.info(f"[{self.name}] {side} DI flip pending confirm ticket={ticket} candle={current_candle}")
                elif current_candle > last_flip_candle:
                    # 下一 candlesK线confirm，真正出场
                    logger.info(f"[{self.name}] {side} DI flip confirm exit ticket={ticket}")
                    del self._trail_data[ticket]
                    return True
                # 同一 candlesK线内，继续wait

        return False

    # ─────────────── 运动员验票（回抽 EMA9） ───────────────

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict, item: dict = None) -> bool:
        """
        v8 验票：等回抽 EMA9 再Entry。
        SELL: 价格远低于 EMA9 → 等rebound到 ≥ EMA9×0.998
        BUY:  价格远高于 EMA9 → 等回抽到 ≤ EMA9×1.002
        """
        direction = signal.get("direction", "BUY")
        ema9 = latest.get("ema_9") or signal.get("indicator_values", {}).get("ema9", 0)
        if ema9 <= 0:
            return True  # 无 EMA9 data就直接放行（保底）

        # update极端值跟踪（跨 tick）
        vs = item.setdefault("verify_state", {}) if item else {}
        if "tick_extreme" not in vs:
            vs["tick_extreme"] = tick_price
        if direction == "SELL":
            vs["tick_extreme"] = max(vs["tick_extreme"], tick_price)
            # 如果价格经远低于 EMA9，等rebound
            if tick_price < ema9 * 0.998:
                # 还没rebound到 EMA9，继续等
                return False
        else:  # BUY
            vs["tick_extreme"] = min(vs["tick_extreme"], tick_price)
            # 如果价格经远高于 EMA9，等回抽
            if tick_price > ema9 * 1.002:
                return False

        logger.debug(f"[verify_v8] {direction} ENTER: price={tick_price:.2f} ema9={ema9:.2f}")
        return True
