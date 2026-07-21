"""
SanQing EA v8_upgraded — H1 实盘策略升级版
===========================================
- EMA9/21 趋势 + ATR14 评分系统（保留原评分逻辑）
- 评分阈值: ADX>20=4, ADX≤20=3
- 运动员等回抽 EMA9 入场
- DI 方向保护的利润回撤 + 硬止损/止盈 + DI反转出场
数据源: 全部指标从 DataFactory TA-Lib 读取
"""
import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v8_upgraded"
STRATEGY_MAGIC = 880108
STRATEGY_LEGACY_MAGICS: list[int] = [880102, 880103, 880104, 880105, 880106]
STRATEGY_CHANGELOG = [
    {"version": "v8_upgraded", "magic": 880108, "date": "2026-07-19",
     "desc": "升级版: 运动员等回抽EMA9入场; 1.5ATR止损3.0ATR止盈; DI保护利润回撤; DI反转出场"},
]


class SanQingH1Upgraded(BaseStrategy):
    """SanQing v8_upgraded — 升级版"""

    name = "sanqing_h1_upgraded"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None

        # 评分阈值
        self.score_threshold = 3
        self.adx_threshold = 20          # ADX>20 趋势中阈值升到 4

        # Exit params
        self.sl_atr = 1.5                # 硬止损 1.5 ATR
        self.tp_atr = 3.0                # 止盈 3.0 ATR (2×止损)
        # profit_drawdown_pct 继承自 BaseStrategy（默认 0.25）
        # DI 方向保护：profit_drawdown 方向一致时不执行
        self._drawdown_min_hold = 1800  # 利润回撤最小持仓：30 分钟（H1 策略，给趋势发展时间）

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

    def refresh_data(self, count: int = 300):
        super().refresh_data(count)

    # ─────────────── 指标 ───────────────

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

        # 实体中位数
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
        logger.info(
            f"[{self.name}] 评分: BUY={buy_score} SELL={sell_score} "
            f"Price={close:.2f} EMA9={ema9:.2f} EMA21={ema21:.2f} ATR={atr_val:.2f}"
            f"{adx_str} 阈值={effective_threshold}"
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

        # 位置门禁（与 v7 一致）
        lookback = min(60, len(candles))
        recent_high = max(c.high for c in candles[-lookback:])
        recent_low = min(c.low for c in candles[-lookback:])
        price_position = (close - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5

        if price_position < 0.10 and sell_score >= effective_threshold:
            short_factors.append("BOTTOM-GATE")
            logger.info(f"[{self.name}] 位置门禁: 底部 {price_position:.1%}，禁止SELL")
            sell_score = 0
        elif price_position > 0.90 and buy_score >= effective_threshold:
            long_factors.append("TOP-GATE")
            logger.info(f"[{self.name}] 位置门禁: 顶部 {price_position:.1%}，禁止BUY")
            buy_score = 0

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

    def _get_exit_multipliers(self, is_buy: bool) -> tuple[float, float]:
        """趋势感知，用于 get_dynamic_sl_tp。缩小幅度。"""
        ema9 = self.get_indicator("ema_9")
        ema21 = self.get_indicator("ema_21")
        trend_up = ema9 is not None and ema21 is not None and ema9 > ema21

        if (is_buy and trend_up) or (not is_buy and not trend_up):
            return (1.5, 3.0)  # 顺趋势
        return (1.0, 2.0)     # 逆趋势

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        is_buy = direction == OrderType.BUY
        sl_mult, tp_mult = self._get_exit_multipliers(is_buy)
        sl_dist = atr_val * sl_mult
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
        """
        v8 出场：
        ① 硬止损: 1.5 ATR（顺）/ 1.0 ATR（逆）
        ② 止盈: 3.0 ATR（顺）/ 2.0 ATR（逆）
        ③ 利润回撤止盈 + DI 方向保护
        ④ DI反转出场
        """
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._trail_data:
            ema9 = self.get_indicator("ema_9")
            ema21 = self.get_indicator("ema_21")
            trend_up = ema9 is not None and ema21 is not None and ema9 > ema21
            sl_mult, tp_mult = self._get_exit_multipliers(is_buy)
            self._trail_data[ticket] = {
                "entry": position.open_price,
                "peak_profit": 0.0,
                "sl_mult": sl_mult,
                "tp_mult": tp_mult,
                "trend_up_entry": trend_up,  # 锁定入场时的趋势方向
                "entry_ts": time.time(),  # 入场时间戳，用于DI反转出场门槛
            }

        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return False

        sl_mult = td["sl_mult"]
        tp_mult = td["tp_mult"]
        pnl_pts = (bid - td["entry"]) if is_buy else (td["entry"] - ask)
        loss_pts = (td["entry"] - bid) if is_buy else (ask - td["entry"])

        # 当前 ADX/DI
        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")

        # 方向是否与 DI 对齐（DI 方向保护用）
        di_aligned = (is_buy and pdi is not None and ndi is not None and pdi > ndi) or \
                     (not is_buy and pdi is not None and ndi is not None and ndi > pdi)

        # ── 更新 peak_profit ──
        if pnl_pts > 0:
            td["peak_profit"] = max(td["peak_profit"], pnl_pts)

        # ── ① 硬止损 ──
        if loss_pts > atr_val * sl_mult:
            logger.info(f"[{self.name}] {'BUY' if is_buy else 'SELL'} HardStop ticket={ticket} loss={loss_pts:.2f}")
            self._last_exit_detail = {"exit_type": "hard_stop", "loss": round(loss_pts, 2)}
            del self._trail_data[ticket]
            return True

        # ── ② 止盈 ──
        if pnl_pts > atr_val * tp_mult:
            logger.info(f"[{self.name}] {'BUY' if is_buy else 'SELL'} TakeProfit ticket={ticket} profit=${pnl_pts:.2f}")
            self._last_exit_detail = {"exit_type": "take_profit", "profit": round(pnl_pts, 2)}
            del self._trail_data[ticket]
            return True

        # ── ③ 利润回撤止盈（DI 保护 + 最小持仓保护） ──
        if pnl_pts > 0 and self.profit_drawdown_enabled and \
           td["peak_profit"] > atr_val * self.profit_drawdown_min_peak_atr:
            profit_ratio = pnl_pts / td["peak_profit"]
            if profit_ratio < (1 - self.profit_drawdown_pct):
                # 最小持仓保护：开仓不足 N 秒不执行利润回撤，给趋势发展时间
                if time.time() - td.get("entry_ts", 0) < self._drawdown_min_hold:
                    logger.info(f"[{self.name}] {'BUY' if is_buy else 'SELL'} "
                                f"利润回撤触发但持仓不足{self._drawdown_min_hold//60}min，跳过")
                # DI 方向保护：如果 DI 仍然对齐，说明趋势完好，不执行利润回撤
                elif di_aligned and adx is not None and adx > 20:
                    logger.info(f"[{self.name}] {'BUY' if is_buy else 'SELL'} "
                                f"利润回撤触发但DI对齐(ADX={adx:.1f})，跳过")
                else:
                    logger.info(f"[{self.name}] {'BUY' if is_buy else 'SELL'} "
                                f"ProfitStop ticket={ticket} profit=${pnl_pts:.2f} "
                                f"peak=${td['peak_profit']:.2f} di_aligned={di_aligned}")
                    self._last_exit_detail = {"exit_type": "profit_drawdown",
                                              "peak": round(td["peak_profit"], 2),
                                              "profit": round(pnl_pts, 2)}
                    del self._trail_data[ticket]
                    return True

        # ── ④ DI反转出场（开仓5分钟后才检查，避免开仓即平） ──
        if pdi is not None and ndi is not None and time.time() - td["entry_ts"] > 300:
            if is_buy and ndi > pdi:
                logger.info(f"[{self.name}] BUY DI反转出场 ticket={ticket}")
                self._last_exit_detail = {"exit_type": "di_flip"}
                del self._trail_data[ticket]
                return True
            elif not is_buy and pdi > ndi:
                logger.info(f"[{self.name}] SELL DI反转出场 ticket={ticket}")
                self._last_exit_detail = {"exit_type": "di_flip"}
                del self._trail_data[ticket]
                return True

        self._last_exit_detail = None
        return False

    # ─────────────── 运动员验票（回抽 EMA9） ───────────────

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict, item: dict = None) -> bool:
        """
        v8 验票：等回抽 EMA9 再入场。
        SELL: 价格远低于 EMA9 → 等反弹到 ≥ EMA9×0.998
        BUY:  价格远高于 EMA9 → 等回抽到 ≤ EMA9×1.002
        """
        direction = signal.get("direction", "BUY")
        ema9 = latest.get("ema_9") or signal.get("indicator_values", {}).get("ema9", 0)
        if ema9 <= 0:
            return True  # 无 EMA9 数据就直接放行（保底）

        # 更新极端值跟踪（跨 tick）
        vs = item.setdefault("verify_state", {}) if item else {}
        if "tick_extreme" not in vs:
            vs["tick_extreme"] = tick_price
        if direction == "SELL":
            vs["tick_extreme"] = max(vs["tick_extreme"], tick_price)
            # 如果价格已经远低于 EMA9，等反弹
            if tick_price < ema9 * 0.998:
                # 还没反弹到 EMA9，继续等
                return False
        else:  # BUY
            vs["tick_extreme"] = min(vs["tick_extreme"], tick_price)
            # 如果价格已经远高于 EMA9，等回抽
            if tick_price > ema9 * 1.002:
                return False

        logger.debug(f"[verify_v8] {direction} ENTER: price={tick_price:.2f} ema9={ema9:.2f}")
        return True
