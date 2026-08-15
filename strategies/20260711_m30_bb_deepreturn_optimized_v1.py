"""
M30 BB DeepReturn Optimized — 超跌reboundstrategyoptimize版
===================================================
Entry: BB extreme + MFI extreme → 超跌rebound
出场:  candles据 BB 开口方向 and  K 线是否same-dir分支决策
  - BB reverse（弱rebound）: 0.5 BB带宽 / MFI回超卖线 / 30%profitdrawdown
  - BB same-dir（有动量）: ATRtrailing + BB对侧轨/MFIreverse15%

optimize (v3):
  - 动态 ADX threshold: 趋-trend (ADX>25)用3分, 震荡 (ADX<=25)用2分
  - ATR volatility加分: ATR/close > 0.25% 额外 +1 分
  - 盈利cooldown缩短至 900s

作者: goodie1972
data源: all指标从 DataFactory TA-Lib read
"""
import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v3_optimized"
STRATEGY_MAGIC = 661102
STRATEGY_LEGACY_MAGICS: list[int] = [661101]
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 661101, "date": "2026-06-29", "desc": "初始上线：BBextreme+MFIextreme超跌rebound，分支出场"},
    {"version": "v2", "magic": 661101, "date": "2026-07-01", "desc": "MFI超买 80→70 不对称化，适应黄金慢涨急跌"},
    {"version": "v3_optimized", "magic": 661102, "date": "2026-07-11", "desc": "动态ADXthreshold+ATRvolatility加分+缩短cooldown至900s"},
]


class M30BBDeepReturnOptimized(BaseStrategy):
    """M30 BB DeepReturn 超跌reboundstrategyoptimize版"""

    name = "m30_bb_deepreturn_optimized"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None
        self._extreme_entry_data: dict[int, dict] = {}

        # Entry params
        self.mfi_period = 14
        self.mfi_oversold = 30
        self.mfi_overbought = 70
        self.bb_std = 2.0
        self.bb_period = 20
        self.score_threshold = 2          # 基础threshold降低到 2，ADX>25 时动态升至 3
        self.adx_trend_threshold = 25     # ADX 趋-trend/震荡分界
        self.score_threshold_trending = 3 # 趋-trend 分数要求

        # ATR volatility加分
        self.atr_volatility_threshold = 0.0025  # 0.25%

        # Exit params
        self.atr_period = 20
        self.p_trailing_atr_bull = 1.5   # BB same-dir时 ATR trailing乘数（宽一 points）
        self.p_trailing_atr_bear = 1.0   # BB reverse时 ATR trailing乘数
        self.p_hard_atr = 2.0
        self.profit_drawdown_pct = 0.50  # BB reverse时 50% profitdrawdowntake profit

        # Exit: BB same-dir时 MFI reversethreshold
        self.mfi_reversal_pct = 15.0

        # Exit: BB reverse时rebound目标
        self.bounce_bb_width = 0.5       # 0.5  BB 带宽

        # 盈利closecooldown（缩短至 900s）
        self._last_profit_exit_time: dict[str, float] = {"BUY": 0.0, "SELL": 0.0}
        self._exit_cooldown_seconds: int = 900
        # 保本延迟：M30 两w期内不激活保本，让硬止损兜底
        self.breakeven_delay_seconds = 3600

    # ─────────────── Indicator helpers ───────────────

    def get_adx_data(self) -> Optional[dict]:
        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        if adx is None:
            return None
        return {"adx": adx, "pdi": pdi, "ndi": ndi}

    def refresh_data(self, count: int = 350):
        super().refresh_data(count)

    # ─────────────── BB 方向检测 ───────────────

    def _check_bb_aligned(self, is_buy: bool) -> bool:
        """检测 BB 开口方向是否 and  K 线same-dir（用于出场分支）。
        使用 DataFactory   mfi_direction 判断 MFI 方向。"""
        closes = self.get_close_prices()
        bb_now = self.get_indicator("bb")
        mfi_dir = self.get_indicator("mfi_direction")
        if not bb_now or mfi_dir is None or len(closes) < 10:
            return False

        # 比较currentposition vs 5  candles前  BB 内position
        bb_range = bb_now["upper"] - bb_now["lower"]
        if bb_range <= 0:
            return False
        curr_pos = (closes[-1] - bb_now["lower"]) / bb_range
        prev_pos = (closes[-5] - bb_now["lower"]) / bb_range

        price_dir = curr_pos > prev_pos  # 价格在 BB 内向上移动

        if is_buy:
            return price_dir and mfi_dir == "up"
        else:
            return (not price_dir) and mfi_dir == "down"

    # ─────────────── Entry scoring ───────────────

    def _get_dynamic_threshold(self) -> tuple[int, int]:
        """return (with趋-trendthreshold, 逆趋-trendthreshold)
        ADX>25 趋-trend ：with2分Entry，逆4分（防逆-trend乱做）
        ADX≤25 震荡 ：都3分
        """
        adx = self.get_indicator("adx")
        if adx is not None and adx > self.adx_trend_threshold:
            return (2, 4)  # 趋-trend ：with2分，逆4分
        return (3, 3)  # 震荡 ：all3分

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 100:
            return None

        closes = self.get_close_prices()
        close = closes[-1]

        bb = self.get_indicator("bb")
        if bb is None:
            return None

        mfi_val = self.get_indicator("mfi")
        if mfi_val is None:
            return None

        atr_val = self.get_indicator("atr_20")
        if atr_val is None:
            return None

        m30_trend = self.get_indicator("trend")

        # ── 动态threshold：趋-trend方向决定with/逆 ──
        with_t, counter_t = self._get_dynamic_threshold()
        pdi_v = self.get_indicator("pdi")
        ndi_v = self.get_indicator("ndi")
        long_th = with_t if (pdi_v is not None and ndi_v is not None and pdi_v > ndi_v) else counter_t
        short_th = with_t if (pdi_v is not None and ndi_v is not None and ndi_v > pdi_v) else counter_t

        # ── Score ──
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

        # ③ BB + MFI 共振（同时出现才算超跌rebound核心Signal）
        if at_lower and mfi_os:
            long_score += 1
            long_detail.append("BBMFI-L")
        if at_upper and mfi_ob:
            short_score += 1
            short_detail.append("BBMFI-H")

        # ④ MA20 趋-trendconfirm
        if m30_trend == 'UP':
            long_score += 1
            long_detail.append("MA20-UP")
        elif m30_trend == 'DOWN':
            short_score += 1
            short_detail.append("MA20-DN")

        # ⑤ MFI 方向（confirm拐头，从 DataFactory read）
        mfi_dir = self.get_indicator("mfi_direction")
        if mfi_dir:
            if at_lower and mfi_dir == "up":
                long_score += 1
                long_detail.append("MFI-UP")
            elif at_upper and mfi_dir == "down":
                short_score += 1
                short_detail.append("MFI-DN")

        # ⑥ ATR volatility加分：高波动增强均值回归Signal
        if atr_val > 0 and close > 0:
            atr_ratio = atr_val / close
            if atr_ratio > self.atr_volatility_threshold:
                if at_lower:
                    long_score += 1
                    long_detail.append(f"ATR-HI({atr_ratio*100:.2f}%)")
                if at_upper:
                    short_score += 1
                    short_detail.append(f"ATR-HI({atr_ratio*100:.2f}%)")

        now = time.time()

        # ── 盈利closecooldown ──
        if long_score >= min(with_t, counter_t):
            remaining = self._exit_cooldown_seconds - (now - self._last_profit_exit_time.get("BUY", 0))
            if remaining > 0:
                long_detail.append(f"COOLDOWN({int(remaining)}s)")
                long_score = 0
        if short_score >= min(with_t, counter_t):
            remaining = self._exit_cooldown_seconds - (now - self._last_profit_exit_time.get("SELL", 0))
            if remaining > 0:
                short_detail.append(f"COOLDOWN({int(remaining)}s)")
                short_score = 0

        # ── BB expand  + MFI方向一致拦截 ──
        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        if _bwr and _bwr > 1.05 and _bwd == "up" and _mfi is not None and _mfi_dir:
            if close > bb["mid"] and _mfi_dir in ("up", "flat"):
                short_score = 0
                short_detail.append("BBW-MFI-UP↑")
                logger.info(f"[{self.name}] BB expand + price > mid + MFI rising({_mfi:.0f})，block short")
            if close < bb["mid"] and _mfi_dir in ("down", "flat"):
                long_score = 0
                long_detail.append("BBW-MFI-DN↓")
                logger.info(f"[{self.name}] BB expand + price < mid + MFI falling({_mfi:.0f})，block long")

        # ── Decision ──
        signal = None
        signal_str = "No signal"
        if long_score >= long_th:
            signal = OrderType.BUY
            signal_str = "LONG"
        elif short_score >= short_th:
            signal = OrderType.SELL
            signal_str = "SELL"

        # ── Logging ──
        detail_parts = []
        if long_detail:
            detail_parts.append("LONG: " + " ".join(long_detail))
        if short_detail:
            detail_parts.append("SHORT: " + " ".join(short_detail))
        adx_v = self.get_indicator("adx")
        logger.info(
            f"[{self.name}] Score: {long_score}/{short_score} threshold=多{long_th}/空{short_th} {signal_str}  "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )
        pdi_v = self.get_indicator("pdi")
        ndi_v = self.get_indicator("ndi")
        adx_log = f" ADX={adx_v:.1f} DI={pdi_v:.0f}/{ndi_v:.0f}" if adx_v is not None else ""
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
            "bb_lower": round(bb["lower"], 2), "bb_mid": round(bb["mid"], 2),
            "mfi_os": self.mfi_oversold, "mfi_ob": self.mfi_overbought,
            "long_th": long_th, "short_th": short_th,
        }
        if adx_v is not None:
            indicator_values.update({
                "adx": round(adx_v, 1),
                "pdi": round(pdi_v, 1),
                "ndi": round(ndi_v, 1),
            })
        return (signal, long_score, short_score, long_detail, short_detail, indicator_values)

    # ─────────────── Entry tracking (engine调用) ───────────────

    def mark_extreme_entry(self, ticket: int | str):
        """engineOpen后调用，recordextremeEntry时 指标快照"""
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
        logger.info(f"[{self.name}] mark extreme entry ticket={ticket} MFI={mfi:.1f}")

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        atr_val = self.get_indicator("atr_20")
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
        - BB same-dir: ATR trailing + BB对侧轨 / MFIreverse15%
        - BB reverse: 0.5 BB带宽rebound / MFI跨超卖线 / 30%profitdrawdown
        """
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        # ── 初始化 trail data ──
        if ticket not in self._trail_data:
            td = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
                "entry_time": time.time(),
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
        atr_val = self.get_indicator("atr_20")
        if atr_val is None or atr_val <= 0:
            return False

        # ── updatetrailingdata ──
        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - td["entry"]
            loss = td["entry"] - bid
            td["peak_profit"] = max(td["peak_profit"], current_profit)

            # 保本出场：走过≥0.3ATR盈利后回到成本附近
            if self._check_breakeven_exit(td, current_profit, atr_val, td["entry"], is_buy):
                logger.info(f"[{self.name}] BUY Breakeven ticket={ticket} profit=${current_profit:.2f}")
                self._last_exit_detail = {"exit_type": "breakeven", "profit": round(current_profit, 2)}
                del self._trail_data[ticket]
                return True

            # trailing MFI 峰值（用于reverse检测）
            mfi_now = self.get_indicator("mfi")
            if mfi_now is not None:
                td["peak_mfi"] = max(td.get("peak_mfi", mfi_now), mfi_now)
        else:
            td["lowest"] = min(td["lowest"], ask)
            current_profit = td["entry"] - ask
            loss = ask - td["entry"]
            td["peak_profit"] = max(td["peak_profit"], current_profit)

            # 保本出场：走过≥0.3ATR盈利后回到成本附近
            if self._check_breakeven_exit(td, current_profit, atr_val, td["entry"], is_buy):
                logger.info(f"[{self.name}] SELL Breakeven ticket={ticket} profit=${current_profit:.2f}")
                self._last_exit_detail = {"exit_type": "breakeven", "profit": round(current_profit, 2)}
                del self._trail_data[ticket]
                return True

            mfi_now = self.get_indicator("mfi")
            if mfi_now is not None:
                td["valley_mfi"] = min(td.get("valley_mfi", mfi_now), mfi_now)

        # ── extremeentry → 分支出场 ──
        if td.get("is_extreme"):
            bb_now = self.get_indicator("bb")
            mfi_now = self.get_indicator("mfi")
            if bb_now and mfi_now is not None:
                bb_range = bb_now["upper"] - bb_now["lower"]
                bb_aligned = self._check_bb_aligned(is_buy)

                if not bb_aligned:
                    # ═══ 场景 A: BB reverse（弱rebound）═══
                    # ① rebound 0.5 BB 带宽
                    bounce_target = td["entry"] + bb_range * self.bounce_bb_width if is_buy \
                                    else td["entry"] - bb_range * self.bounce_bb_width
                    if (is_buy and bid >= bounce_target) or (not is_buy and ask <= bounce_target):
                        logger.info(f"[{self.name}] BB reverse rebound TP ticket={ticket} "
                                     f"{'BUY' if is_buy else 'SELL'} target={bounce_target:.2f}")
                        self._last_exit_detail = {"exit_type": "bounce_tp", "target": round(bounce_target, 2)}
                        self._on_exit(ticket, is_buy)
                        return True

                    # ② MFI 跨过超卖线
                    if (is_buy and mfi_now > self.mfi_oversold) or \
                       (not is_buy and mfi_now < self.mfi_overbought):
                        logger.info(f"[{self.name}] BB reverse MFI return TP ticket={ticket} "
                                     f"MFI={mfi_now:.1f} threshold={'<20' if not is_buy else '>80'}")
                        self._last_exit_detail = {"exit_type": "mfi_cross", "mfi": round(mfi_now, 1)}
                        self._on_exit(ticket, is_buy)
                        return True

                    # ③ 30% profitdrawdowntake profit
                    if current_profit > 0 and td.get("peak_profit", 0) > atr_val * 0.5:
                        profit_ratio = current_profit / td["peak_profit"]
                        # 动态止盈：盈利>10时收紧到35%，否则保持50%
                        _dd_pct = 0.35 if td.get("peak_profit", 0) > 10 else self.profit_drawdown_pct
                        if profit_ratio < (1 - _dd_pct):
                            logger.info(f"[{self.name}] BB reverse profit drawdown TP ticket={ticket} "
                                         f"profit=${current_profit:.2f} peak=${td['peak_profit']:.2f}")
                            self._last_exit_detail = {"exit_type": "profit_drawdown_30",
                                                       "peak": round(td["peak_profit"], 2),
                                                       "current": round(current_profit, 2)}
                            self._on_exit(ticket, is_buy)
                            return True
                else:
                    # ═══ 场景 B: BB same-dir（有动量）═══
                    # 通道1: BB 对侧轨take profit
                    if is_buy and bid >= bb_now["upper"]:
                        logger.info(f"[{self.name}] BB same-dir upper band TP ticket={ticket} bid={bid:.2f} BB_U={bb_now['upper']:.2f}")
                        self._last_exit_detail = {"exit_type": "bb_band_tp", "band": "upper"}
                        self._on_exit(ticket, is_buy)
                        return True
                    if not is_buy and ask <= bb_now["lower"]:
                        logger.info(f"[{self.name}] BB same-dir lower band TP ticket={ticket} ask={ask:.2f} BB_L={bb_now['lower']:.2f}")
                        self._last_exit_detail = {"exit_type": "bb_band_tp", "band": "lower"}
                        self._on_exit(ticket, is_buy)
                        return True

                    # 通道2: MFI reverse 15% take profit
                    if is_buy and td.get("peak_mfi", mfi_now) > mfi_now:
                        mfi_drop = (td["peak_mfi"] - mfi_now) / max(td["peak_mfi"], 1) * 100
                        if mfi_drop >= self.mfi_reversal_pct:
                            logger.info(f"[{self.name}] BB same-dir MFI reverse TP ticket={ticket} "
                                         f"peak_mfi={td['peak_mfi']:.1f} now={mfi_now:.1f} drop={mfi_drop:.0f}%")
                            self._last_exit_detail = {"exit_type": "mfi_reversal", "drop_pct": round(mfi_drop, 1)}
                            self._on_exit(ticket, is_buy)
                            return True
                    if not is_buy and td.get("valley_mfi", mfi_now) < mfi_now:
                        mfi_rise = (mfi_now - td["valley_mfi"]) / max(mfi_now, 1) * 100
                        if mfi_rise >= self.mfi_reversal_pct:
                            logger.info(f"[{self.name}] BB same-dir MFI reverse TP ticket={ticket} "
                                         f"valley_mfi={td['valley_mfi']:.1f} now={mfi_now:.1f} rise={mfi_rise:.0f}%")
                            self._last_exit_detail = {"exit_type": "mfi_reversal", "rise_pct": round(mfi_rise, 1)}
                            self._on_exit(ticket, is_buy)
                            return True

                    # 通道3: ATR trailingtake profit（兜底）
                    if is_buy:
                        drawdown = td["highest"] - bid
                        if drawdown > atr_val * self.p_trailing_atr_bull:
                            logger.info(f"[{self.name}] BB same-dir ATR trailing TP ticket={ticket} "
                                         f"drawdown={drawdown:.2f} trail={self.p_trailing_atr_bull}")
                            self._last_exit_detail = {"exit_type": "atr_trail", "drawdown": round(drawdown, 2)}
                            self._on_exit(ticket, is_buy)
                            return True
                    else:
                        rally = ask - td["lowest"]
                        if rally > atr_val * self.p_trailing_atr_bull:
                            logger.info(f"[{self.name}] BB same-dir ATR trailing TP ticket={ticket} "
                                         f"rally={rally:.2f} trail={self.p_trailing_atr_bull}")
                            self._last_exit_detail = {"exit_type": "atr_trail", "rally": round(rally, 2)}
                            self._on_exit(ticket, is_buy)
                            return True

        # ── 硬止损（无件兜底，对所有Positions生效，含extremeentry）──
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
        """出场cleanup"""
        direction = "BUY" if is_buy else "SELL"
        self._last_profit_exit_time[direction] = time.time()
        self._trail_data.pop(ticket, None)

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        direction = signal.get("direction", "BUY")
        bb = latest.get("bb") or {}
        mfi = latest.get("mfi", 50)
        trend = latest.get("trend", "NEUTRAL")
        factors = signal.get("factors_long", []) if direction == "BUY" else signal.get("factors_short", [])

        _log = logging.getLogger(__name__)

        if direction == "BUY":
            if bb.get("lower") and tick_price > bb["lower"] * 1.005:
                _log.info(f"[verify] BUY REJECT: price={tick_price:.2f} > lower*1.005={bb['lower']*1.005:.2f}")
                return False
            if any(f.startswith("MFI-") for f in factors) and mfi > 45:
                _log.info(f"[verify] BUY REJECT: factors={factors} mfi={mfi:.1f} > 45")
                return False
            if any(f == "MA20-UP" for f in factors) and trend != "UP":
                _log.info(f"[verify] BUY REJECT: MA20-UP but trend={trend}")
                return False
        else:
            if bb.get("upper") and tick_price < bb["upper"] * 0.995:
                _log.info(f"[verify] SELL REJECT: price={tick_price:.2f} < upper*0.995={bb['upper']*0.995:.2f}")
                return False
            if any(f.startswith("MFI-") for f in factors) and mfi < 55:
                _log.info(f"[verify] SELL REJECT: factors={factors} mfi_cache={mfi:.1f} < 55")
                return False
            if any(f == "MA20-DN" for f in factors) and trend != "DOWN":
                _log.info(f"[verify] SELL REJECT: MA20-DN but trend={trend}")
                return False
        _log.info(f"[verify] SELL PASS: price={tick_price:.2f} upper={bb.get('upper',0):.2f} mfi={mfi:.1f} trend={trend}")
        return True
