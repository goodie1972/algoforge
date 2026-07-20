"""
Viprasol Sniper — 7因子共识 + 多级RR出场
=============================================
来源: TradingView Viprasol Sniper Confluence Entry/Exit
- 7因子评分: VWAP替代→EMA位置, RSI, MACD, EMA排列, ADX+DI, 成交量, 次级RSI
- 多级RR出场: 1R/2R/3R/4R/5R, TP1命中后移到保本
- K线收盘确认
数据源: 全部指标从 DataFactory TA-Lib 读取
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
        self.rr_levels = [2, 3, 4, 5]  # 出场级别从 2R 开始（1R 只触发保本，不平仓）
        self.breakeven_r = 1.0  # 保本触发级别（1R）
        self.trail_atr = 1.0  # 移动追踪

    def get_adx_data(self) -> Optional[dict]:
        adx = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        if adx is None:
            return None
        return {"adx": adx, "pdi": pdi, "ndi": ndi}

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 60: return (None, 0, 0, [], [], {})

        closes = self.get_close_prices()
        close = closes[-1]
        atr_val = self.get_indicator("atr")
        if atr_val is None: return (None, 0, 0, [], [], {})

        ema9 = self.get_indicator("ema_9")
        ema21 = self.get_indicator("ema_21")
        if ema9 is None or ema21 is None: return (None, 0, 0, [], [], {})

        long_score = 0; long_detail = []
        short_score = 0; short_detail = []

        # ① 价格vs EMA位置 (VWAP替代)
        if close > ema21:
            long_score += 1; long_detail.append(f"EMA>{ema21:.1f}")
        else:
            short_score += 1; short_detail.append(f"EMA<{ema21:.1f}")

        # ② RSI方向
        rsi_val = self.get_indicator("rsi")
        if rsi_val is not None:
            if rsi_val > 50:
                long_score += 1; long_detail.append(f"RSI>{rsi_val:.0f}")
            elif rsi_val < 50:
                short_score += 1; short_detail.append(f"RSI<{rsi_val:.0f}")

        # ③ MACD方向（DataFactory）
        macd_d = self.get_indicator("macd")
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
        _adx = self.get_indicator("adx")
        _pdi = self.get_indicator("pdi")
        _ndi = self.get_indicator("ndi")
        adx_data = {"adx": _adx, "pdi": _pdi, "ndi": _ndi} if _adx is not None else None
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

        # ⑦ 次级RSI (M15) - DataFactory TA-Lib 值
        try:
            from services.data_factory import get_cache
            m15_cached = get_cache("M15")
            rsi_m15 = m15_cached.get("rsi") if m15_cached else None
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
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return (0, 0)  # ATR 缺失时返回 (0,0) 让引擎走 fallback
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
            _atr0 = self.get_indicator("atr")
            self._trail_data[ticket] = {
                "highest": position.open_price if is_buy else 0,
                "lowest": position.open_price if not is_buy else float("inf"),
                "entry": position.open_price,
                "peak_profit": 0.0,
                "breakeven": False,
                # 锁定入场时 1R 风险距离，RR 出场价位不随后续 ATR 漂移
                "risk_r": (_atr0 * self.sl_atr) if (_atr0 and _atr0 > 0) else None,
            }

        td = self._trail_data[ticket]
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return False

        entry = td["entry"]
        # RR 出场用入场时锁定的 1R；若入场时 ATR 缺失则用当前 ATR 补锁
        risk_r = td.get("risk_r")
        if not risk_r:
            risk_r = atr_val * self.sl_atr
            td["risk_r"] = risk_r

        if is_buy:
            td["highest"] = max(td["highest"], bid)
            current_profit = bid - entry
            td["peak_profit"] = max(td["peak_profit"], current_profit)

            # TP1命中→移到保本
            if not td["breakeven"] and current_profit > risk_r * self.breakeven_r:
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

            if not td["breakeven"] and current_profit > risk_r * self.breakeven_r:
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
