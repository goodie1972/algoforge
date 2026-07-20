"""
M30 RSI + 布林带均值回归 — 7因子评分系统
=========================
- 入场: 7因子评分系统 ≥4直接开, =3需diff≥2
- 7因子: M30趋势, BB位置(90%), RSI分层(25/35/65/75), RSI方向(3根), DI强度, 成交量, K线形态
- ADX>28趋势门禁已移除（2026-06-30）
- 出场: 保本出场 + 利润回撤止盈 + ATR追踪 + DI跳过(盈利时) + 硬止损
- 双向交易 (Long / Short)
数据源: 全部指标从 DataFactory TA-Lib 读取
"""

import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v13"
STRATEGY_MAGIC = 660707
STRATEGY_LEGACY_MAGICS = [660705, 660706,
]  # 旧版 magic，引擎启动时自动接管
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 660701, "date": "2026-06-08", "desc": "初始上线：5因子评分≥3，ATR跟踪止损 trail=4.0 hard=3.0"},
    {"version": "v2", "magic": 660702, "date": "2026-06-08", "desc": "修复出场逻辑：区分盈利/亏损阶段，新增 peak_profit 跟踪"},
    {"version": "v3", "magic": 660703, "date": "2026-06-09", "desc": "双重止盈：trail=1.0 hard=2.0，新增 profit_drawdown_pct=0.25，新增 indicator_values 返回"},
    {"version": "v4", "magic": 660704, "date": "2026-06-11", "desc": "RSI分层过滤：RSI<20禁空，RSI20-30空头扣1分；新增 tight_exit_mode 新闻风控"},
    {"version": "v5", "magic": 660705, "date": "2026-06-12", "desc": "位置门禁：60根K线区间底部10%禁空、顶部10%禁多"},
    {"version": "v6", "magic": 660706, "date": "2026-06-15", "desc": "趋势判断改为M30自身SMA200（替代H1 SMA200），盈利平仓后同方向30分钟冷却"},
    {"version": "v7", "magic": 660707, "date": "2026-06-19", "desc": "趋势判断MA14替代SMA200，去掉低波动率因子⑤，4因子评分"},
    {"version": "v8", "magic": 660707, "date": "2026-06-22", "desc": "移除tight_exit_mode和RSI短侧过滤"},
    {"version": "v9", "magic": 660707, "date": "2026-06-22", "desc": "新增ADX>28趋势门禁(EMA9/21), RSI方向改3根连续确认"},
    {"version": "v10", "magic": 660707, "date": "2026-06-22", "desc": "新增DI止盈判定: 移动止盈触发时+DI- -DI>10(BUY)/-DI-+DI>10(SELL)则忽略止盈"},
    {"version": "v11", "magic": 660707, "date": "2026-06-22", "desc": "新增DI强度因子⑤: |DI差|>10 给±1分, 5因子评分阈值保持3"},
    {"version": "v12", "magic": 660707, "date": "2026-07-01", "desc": "H1 MA20趋势门禁替代ADX门禁"},
    {"version": "v13", "magic": 660707, "date": "2026-07-01", "desc": "H1门禁放过极值区：BB上轨10%外或RSI深超买时允许SELL，下轨10%外或深超卖时允许BUY"},
]


class M30RSIStrategy(BaseStrategy):
    """M30 RSI + 布林带均值回归 + ATR动态出场"""

    name = "M30_rsi_bb"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None

        # Entry params (from optimization)
        self.rsi_deep_oversold = 25
        self.rsi_oversold = 35
        self.rsi_deep_overbought = 75
        self.rsi_overbought = 65
        self.bb_std = 2.0
        self.score_threshold = 3

        # Exit params — 双重止盈：利润回撤25% + ATR移动止盈 + 硬止损
        self.p_trailing_atr = 1.0   # 回调超过 1 ATR 即止盈（原为 4.0）
        self.p_hard_atr = 2.0       # 硬止损 ATR×2（原为 3.0）
        # profit_drawdown_pct 继承自 BaseStrategy（默认 0.25，由 settings.py 控制）

        # (ADX>28 趋势门禁已移除 — 2026-06-30)

        # Indicator params
        self.bb_period = 20
        self.rsi_period = 14
        self.atr_period = 20
        self.ma14_period = 14

        # 盈利平仓冷却：盈利出场后同方向30分钟内不再开仓
        self._last_profit_exit_time: dict[str, float] = {"BUY": 0.0, "SELL": 0.0}
        self._exit_cooldown_seconds: int = 1800  # 30分钟

    def get_adx_data(self) -> Optional[dict]:
        """返回 ADX 数据（含 +DI/-DI），供引擎门禁使用"""
        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        if adx is None:
            return None
        return {"adx": adx, "pdi": pdi, "ndi": ndi}

    def refresh_data(self, count: int = 350):
        super().refresh_data(count)

    def _calc_rsi(self, closes: list[float], period: int = 14) -> Optional[float]:
        """RSI 计算（保留用于 _get_m30_rsi_direction 的序列切片计算）"""
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

    def _get_m30_rsi_direction(self) -> str:
        """M30 RSI方向: 连续3根RSI同向确认"""
        closes = self.get_close_prices()
        if len(closes) < self.rsi_period + 5: return 'flat'
        rsi_3 = self._calc_rsi(closes[:-2], self.rsi_period)
        rsi_2 = self._calc_rsi(closes[:-1], self.rsi_period)
        rsi_1 = self._calc_rsi(closes, self.rsi_period)
        if any(x is None for x in [rsi_3, rsi_2, rsi_1]): return 'flat'
        if rsi_3 < rsi_2 < rsi_1: return 'up'
        if rsi_3 > rsi_2 > rsi_1: return 'down'
        return 'flat'

    # ─────────────── Signal generation ───────────────

    def _detect_candle_pattern(self) -> tuple:
        """TA-Lib 强反转形态检测（仅高置信度信号）。"""
        c = self.candles
        if len(c) < 10:
            return ('none', None)
        try:
            import numpy as np
            import talib
            o = np.array([x.open for x in c], dtype=float)
            h = np.array([x.high for x in c], dtype=float)
            l = np.array([x.low for x in c], dtype=float)
            cl = np.array([x.close for x in c], dtype=float)

            # 早晨之星/黄昏之星（三根K线确认，最强反转）
            if talib.CDLMORNINGSTAR(o, h, l, cl, penetration=0.3)[-1] == 100:
                return ('long', 'MORNING')
            if talib.CDLEVENINGSTAR(o, h, l, cl, penetration=0.3)[-1] == -100:
                return ('short', 'EVENING')

            # 强见底反转
            for func, name in [
                    (talib.CDLHAMMER, "HAMMER"),
                    (talib.CDLPIERCING, "PIERCE"),
            ]:
                if func(o, h, l, cl)[-1] == 100:
                    return ('long', name)

            # 强见顶反转
            for func, name in [
                    (talib.CDLSHOOTINGSTAR, "SHOOT"),
                    (talib.CDLDARKCLOUDCOVER, "CLOUD"),
                    (talib.CDLBEARISHENGULFING, "ENGULF"),
                    (talib.CDLHANGINGMAN, "HANG"),
            ]:
                if func(o, h, l, cl)[-1] == -100:
                    return ('short', name)
        except Exception:
            pass
        return ('none', None)


    def generate_signal(self) -> Optional[OrderType]:
        candles = self.candles
        if len(candles) < 100:
            logger.debug(f"[{self.name}] 数据不足: {len(candles)} < 100")
            return (None, 0, 0, [], [], {})

        closes = self.get_close_prices()
        close = closes[-1]
        low = candles[-1].low
        high = candles[-1].high

        # Indicators
        bb = self.get_indicator("bb")
        if bb is None: return (None, 0, 0, [], [], {})

        rsi_val = self.get_indicator("rsi")
        if rsi_val is None: return (None, 0, 0, [], [], {})

        atr_val = self.get_indicator("atr_20")
        if atr_val is None: return (None, 0, 0, [], [], {})

        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        # ADX 缺失时 adx_data 置 None，避免后续 None - None TypeError
        adx_data = {"adx": adx, "pdi": pdi, "ndi": ndi} if adx is not None else None
        m30_trend = self.get_indicator("trend")
        m30_rsi_dir = self._get_m30_rsi_direction()

        # ── Scoring ──
        long_score = 0; long_detail = []
        short_score = 0; short_detail = []

        # ① M30 trend（原H1 SMA200改为M30自身周期）
        if m30_trend == 'UP':
            long_score += 1; long_detail.append("M30-UP")
        elif m30_trend == 'DOWN':
            short_score += 1; short_detail.append("M30-DN")

        # ② BB 位置：价格进入上下轨 10% 区间即触发（原需精确触轨）
        bb_range = bb['upper'] - bb['lower']
        bb_bot_zone = bb['lower'] + bb_range * 0.1   # 底部 10% 边界
        bb_top_zone = bb['lower'] + bb_range * 0.9   # 顶部 10% 边界
        if close <= bb_bot_zone:
            long_score += 1; long_detail.append(f"BB-BOT({(close-bb['lower'])/bb_range*100:.0f}%)")
        if close >= bb_top_zone:
            short_score += 1; short_detail.append(f"BB-TOP({(close-bb['lower'])/bb_range*100:.0f}%)")

        # ③ RSI extreme（分层：浅/深两档）
        if rsi_val < self.rsi_deep_oversold:
            long_score += 2; long_detail.append(f"RSI-{rsi_val:.0f}(deep)")
        elif rsi_val < self.rsi_oversold:
            long_score += 1; long_detail.append(f"RSI-{rsi_val:.0f}")
        if rsi_val > self.rsi_deep_overbought:
            short_score += 2; short_detail.append(f"RSI-{rsi_val:.0f}(deep)")
        elif rsi_val > self.rsi_overbought:
            short_score += 1; short_detail.append(f"RSI-{rsi_val:.0f}")

        # ④ M30 RSI direction
        if m30_rsi_dir == 'up':
            long_score += 1; long_detail.append("RSI-UP")
        elif m30_rsi_dir == 'down':
            short_score += 1; short_detail.append("RSI-DN")

        # ⑤ DI强度: |DI差|>10 确认单边势
        if adx_data:
            di_diff = adx_data["pdi"] - adx_data["ndi"]
            if di_diff > 10:
                long_score += 1; long_detail.append(f"DI+{di_diff:.0f}")
            elif di_diff < -10:
                short_score += 1; short_detail.append(f"DI{di_diff:.0f}")

        # ⑥ H1 趋势门禁（只拦信号不扣分）
        # 例外：价格在BB极值 + RSI极端同时满足时，确认真均值回归，放过
        #   SHORT: H1=UP 但 price>=BB上轨 AND RSI>70 → 放过SELL
        #   LONG:  H1=DOWN 但 price<=BB下轨 AND RSI<30 → 放过BUY
        self._load_h1_data()
        h1_trend = self._get_h1_trend(20)
        h1_block_long = h1_trend == 'DOWN' and not (close <= bb_bot_zone and rsi_val < 30)
        h1_block_short = h1_trend == 'UP' and not (close >= bb_top_zone and rsi_val > 70)

        # --- Volume confirmation: vol > SMA20*1.3 ---
        vol_sma = self.get_indicator("volume_sma_20")
        if vol_sma and vol_sma > 0:
            cur_vol = candles[-1].volume
            if cur_vol > vol_sma * 1.3:
                if candles[-1].close > candles[-1].open:
                    long_score += 1; long_detail.append(f"VOL{cur_vol/vol_sma:.1f}x")
                else:
                    short_score += 1; short_detail.append(f"VOL{cur_vol/vol_sma:.1f}x")

        # --- Candlestick pattern ---
        pat_dir, pat_name = self._detect_candle_pattern()
        if pat_dir == 'long':
            long_score += 1; long_detail.append(pat_name)
        elif pat_dir == 'short':
            short_score += 1; short_detail.append(pat_name)

        now = time.time()

        # ── 盈利平仓冷却：同方向30分钟内不开仓 ──
        if long_score >= self.score_threshold:
            remaining = self._exit_cooldown_seconds - (now - self._last_profit_exit_time.get("BUY", 0))
            if remaining > 0:
                long_detail.append(f"COOLDOWN({int(remaining)}s)")
                logger.info(f"[{self.name}] BUY冷却中: 盈利平仓后还剩{int(remaining)}秒")
                long_score = 0
        if short_score >= self.score_threshold:
            remaining = self._exit_cooldown_seconds - (now - self._last_profit_exit_time.get("SELL", 0))
            if remaining > 0:
                short_detail.append(f"COOLDOWN({int(remaining)}s)")
                logger.info(f"[{self.name}] SELL冷却中: 盈利平仓后还剩{int(remaining)}秒")
                short_score = 0

        # ── Decision（双层判决：≥4直接开，=3需diff≥2）+ H1门禁拦截 ──
        diff = long_score - short_score
        signal = None
        signal_str = "无信号"
        if long_score >= self.score_threshold + 1 and not h1_block_long:
            signal = OrderType.BUY
            signal_str = "LONG"
        elif short_score >= self.score_threshold + 1 and not h1_block_short:
            signal = OrderType.SELL
            signal_str = "SELL"
        elif long_score >= self.score_threshold and diff >= 2 and not h1_block_long:
            signal = OrderType.BUY
            signal_str = f"LONG(diff={diff})"
        elif short_score >= self.score_threshold and -diff >= 2 and not h1_block_short:
            signal = OrderType.SELL
            signal_str = f"SELL(diff={-diff})"

        # ── Logging ──
        gate_log = ""
        if h1_block_long: gate_log = " [H1禁BUY]"
        elif h1_block_short: gate_log = " [H1禁SELL]"
        detail_parts = []
        if long_detail: detail_parts.append("LONG: " + " ".join(long_detail))
        if short_detail: detail_parts.append("SHORT: " + " ".join(short_detail))
        logger.info(
            f"[{self.name}] 评分: {long_score}/{short_score}{gate_log}  {signal_str}  "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )
        adx_log = f" ADX={adx_data['adx']:.1f}" if adx_data else ""
        logger.info(
            f"[{self.name}] Price={close:.2f} BB={bb['lower']:.2f}/{bb['upper']:.2f} "
            f"RSI={rsi_val:.1f} ATR={atr_val:.2f} M30={m30_trend} H1={h1_trend}{adx_log}"
        )

        # Price position within BB bands
        bb_range = bb["upper"] - bb["lower"]
        price_position = (close - bb["lower"]) / bb_range if bb_range > 0 else 0.5
        # Recent price extremes (20-bar lookback)
        lookback = min(20, len(closes))
        recent_high = max(closes[-lookback:])
        recent_low = min(closes[-lookback:])

        indicator_values = {
            "close": round(close, 2), "rsi": round(rsi_val, 2),
            "atr": round(atr_val, 2), "bb_upper": round(bb["upper"], 2),
            "price_position": round(price_position, 3),
            "recent_high": round(recent_high, 2), "recent_low": round(recent_low, 2),
            "bb_lower": round(bb["lower"], 2), "bb_mid": round(bb["mid"], 2),
            "m30_trend": m30_trend, "m30_rsi_dir": m30_rsi_dir,
            "h1_trend": h1_trend,
            "adx": round(adx_data["adx"], 1) if adx_data else 0,
            "ema9": 0, "ema21": 0,
        }
        return (signal, long_score, short_score, long_detail, short_detail, indicator_values)

    # ─────────────── Trend-aware exit multipliers ───────────────

    def _get_exit_multipliers(self, is_buy: bool) -> tuple[float, float]:
        trend = self.get_indicator("trend")
        if trend == 'UP':
            return (1.5, 3.0) if is_buy else (1.0, 2.0)
        elif trend == 'DOWN':
            return (1.0, 2.0) if is_buy else (1.5, 3.0)
        else:
            return (1.2, 2.5)

    # ─────────────── SL/TP and Exit ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """双层止盈止损：
        ① 固定 SL/TP：根据 顺势/逆向/震荡 设置不同的 ATR 倍率（MT4 订单级硬边界）
        ② 趋势止盈：由 check_ema20_exit 运行时动态管理（trailing/drawdown）
        """
        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)

        m30_trend = self.get_indicator("trend")
        is_buy = direction == OrderType.BUY

        # 三档固定倍率：逆势 / 震荡 / 顺势
        if m30_trend == 'NEUTRAL':
            sl_mult, tp_mult = 1.5, 3.0       # 震荡: SL=1.5ATR  TP=3.0ATR
        elif (m30_trend == 'UP' and is_buy) or (m30_trend == 'DOWN' and not is_buy):
            sl_mult, tp_mult = 2.5, 4.0       # 顺势: SL=2.5ATR  TP=4.0ATR (和MA同向)
        else:
            sl_mult, tp_mult = 1.0, 2.0       # 逆向: SL=1.0ATR  TP=2.0ATR (和MA反向)

        sl_dist = atr_val * sl_mult
        tp_dist = atr_val * tp_mult
        if is_buy:
            sl = round(entry_price - sl_dist, 2)
            tp = round(entry_price + tp_dist, 2)
        else:
            sl = round(entry_price + sl_dist, 2)
            tp = round(entry_price - tp_dist, 2)
            if tp <= 0:
                tp = 0
        return sl, tp

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """双重止盈：利润回撤止盈 + ATR移动止盈 + 硬止损"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        if ticket not in self._trail_data:
            # 锁定开仓时的趋势方向，后续不受 MA14 翻转影响
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
        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return False

        trail_mult = td["trail_mult"]
        hard_mult = td["hard_mult"]
        pdd = self.profit_drawdown_pct
        # ADX>25 趋势强 → 放宽回撤
        _ax_adx = self.get_indicator("adx")
        if _ax_adx and _ax_adx > 25:
            pdd = max(pdd, 0.5)

        adx_data = {"adx": self.get_indicator("adx"), "pdi": self.get_indicator("pdi"), "ndi": self.get_indicator("ndi")}

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - td["entry"]
            loss = td["entry"] - bid
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
                    profit_ratio = current_profit / td["peak_profit"]
                    if profit_ratio < (1 - pdd):
                        logger.info(f"[{self.name}] BUY ProfitStop ticket={ticket} profit=${current_profit:.2f} peak=${td['peak_profit']:.2f}")
                        self._last_exit_detail = {"exit_type": "profit_drawdown", "peak_profit": round(td["peak_profit"], 2), "current_profit": round(current_profit, 2), "atr": round(atr_val, 2)}
                        self._last_profit_exit_time["BUY"] = time.time()
                        del self._trail_data[ticket]
                        return True

            # 移动止盈：从最高点回落
            drawdown = td["highest"] - bid
            if drawdown > atr_val * trail_mult:
                # DI止盈判定: +DI - -DI > 10 趋势仍强, 忽略止盈
                if adx_data and current_profit > 0 and (adx_data["pdi"] - adx_data["ndi"]) > 10:
                    logger.info(f"[{self.name}] BUY DI跳过止盈 ticket={ticket} DIs={adx_data['pdi']-adx_data['ndi']:.1f}")
                else:
                    logger.info(f"[{self.name}] BUY TrailStop ticket={ticket} drawdown={drawdown:.2f} trail={trail_mult}")
                    self._last_exit_detail = {"exit_type": "trail_stop", "direction": "BUY", "drawdown": round(drawdown, 2), "atr": round(atr_val, 2), "trail_mult": trail_mult}
                    self._last_profit_exit_time["BUY"] = time.time()
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
                    profit_ratio = current_profit / td["peak_profit"]
                    if profit_ratio < (1 - pdd):
                        logger.info(f"[{self.name}] SELL ProfitStop ticket={ticket} profit=${current_profit:.2f} peak=${td['peak_profit']:.2f}")
                        self._last_exit_detail = {"exit_type": "profit_drawdown", "peak_profit": round(td["peak_profit"], 2), "current_profit": round(current_profit, 2), "atr": round(atr_val, 2)}
                        self._last_profit_exit_time["SELL"] = time.time()
                        del self._trail_data[ticket]
                        return True

            # 移动止盈：从最低点反弹
            rally = ask - td["lowest"]
            if rally > atr_val * trail_mult:
                # DI止盈判定: -DI - +DI > 10 趋势仍强, 忽略止盈
                if adx_data and current_profit > 0 and (adx_data["ndi"] - adx_data["pdi"]) > 10:
                    logger.info(f"[{self.name}] SELL DI跳过止盈 ticket={ticket} DIs={adx_data['ndi']-adx_data['pdi']:.1f}")
                else:
                    logger.info(f"[{self.name}] SELL TrailStop ticket={ticket} rally={rally:.2f} trail={trail_mult}")
                    self._last_exit_detail = {"exit_type": "trail_stop", "direction": "SELL", "rally": round(rally, 2), "atr": round(atr_val, 2), "trail_mult": trail_mult}
                    self._last_profit_exit_time["SELL"] = time.time()
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
        '''用最新 tick 价 + 工厂缓存重算入场条件'''
        direction = signal.get("direction", "BUY")
        bb = latest.get("bb") or {}
        rsi = latest.get("rsi", 50)
        pdi = latest.get("pdi", 15)
        ndi = latest.get("ndi", 15)
        trend = latest.get("trend", "NEUTRAL")
        factors = signal.get("factors_long", []) if direction == "BUY" else signal.get("factors_short", [])

        if direction == "BUY":
            if bb.get("lower") and tick_price > bb["lower"] * 1.005:
                return False
            if any(f.startswith("RSI-") for f in factors) and rsi > 45:
                return False
            if any(f.startswith("DI+") for f in factors) and pdi <= ndi:
                return False
            if any(f in ("M30-UP","MA20-UP") for f in factors) and trend != "UP":
                return False
        else:
            if bb.get("upper") and tick_price < bb["upper"] * 0.995:
                return False
            if any(f.startswith("RSI-") for f in factors) and rsi < 55:
                return False
            if any(f.startswith("DI-") or f.startswith("DI") for f in factors) and ndi <= pdi:
                return False
            if any(f in ("M30-DN","MA20-DN") for f in factors) and trend != "DOWN":
                return False
        return True
