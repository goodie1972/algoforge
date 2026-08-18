"""
Gold-AutoResearch — H1 实盘strategy
===============================
- 4因子共识投票: 趋-trend + 动量 + 波动 + safety
  - EMA10/20 → 趋-trend方向
  - MACD(12,26,9) + Stoch(14,3,3) → 动量
  - ADX + ATR → 波动活性
  - RSI(10) + BB(20,2) → safetyfilter
- all4件一致才触发Signal
- ATR动态trailing止损出场
data源: all指标从 DataFactory TA-Lib read
"""

import logging
import time
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v7"
STRATEGY_MAGIC = 880306
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 880301, "date": "2026-06-08", "desc": "初始上线：4因子共识投票，ATR跟踪止损 trail=3.5 hard=2.0"},
    {"version": "v2", "magic": 880302, "date": "2026-06-08", "desc": "修复出场逻辑：区分盈利/loss阶段，新增 peak_profit 跟踪"},
    {"version": "v3", "magic": 880303, "date": "2026-06-09", "desc": "双重take profit：trail=1.0 hard=2.0，新增 profit_drawdown_pct=0.25，新增 indicator_values return"},
    {"version": "v4", "magic": 880304, "date": "2026-06-11", "desc": "新增 tight_exit_mode newsrisk"},
    {"version": "v5", "magic": 880305, "date": "2026-06-11", "desc": "SAFE-DN改为RSI≤35独立封空，防止接近超卖区开空"},
    {"version": "v6", "magic": 880306, "date": "2026-06-11", "desc": "positionGate：60 candlesK线rangebottom10%禁空、top10%禁多"},
    {"version": "v7", "magic": 880306, "date": "2026-07-01", "desc": "H4 SMA50趋-trendGate：H4下行NO BUY、H4上行NO SELL"},
]


class GoldAutoResearchStrategy(BaseStrategy):
    """Gold-AutoResearch — H1 共识投票strategy"""

    name = "gold_auto_research"

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}
        self._last_exit_detail: Optional[dict] = None
        self._last_profit_exit_time: dict[str, float] = {"BUY": 0.0, "SELL": 0.0}

        # Exit params — 双重take profit：profitdrawdown25% + ATR移动take profit + 硬止损
        self.p_trailing_atr = 1.0   # 回调超过 1 ATR 即take profit（原为 3.5）
        self.p_hard_atr = 2.0
        # profit_drawdown_pct 继承自 BaseStrategy（default 0.25，由 settings.py 控制）

    def get_adx_data(self) -> Optional[dict]:
        _adx = self.get_indicator("adx")
        _pdi = self.get_indicator("pdi")
        _ndi = self.get_indicator("ndi")
        if _adx is not None:
            return {"adx": _adx, "pdi": _pdi, "ndi": _ndi}
        return None

    def refresh_data(self, count: int = 300):
        super().refresh_data(count)

    # ─────────────── Signal generation ───────────────

    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 100:
            return (None, 0, 0, [], [], {})

        closes = self.get_close_prices()
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        close = closes[-1]
        high = highs[-1]
        low = lows[-1]
        n = len(closes)

        # ── ① Trend: EMA10 vs EMA20 ──
        ema10 = self.get_indicator("ema_9")
        ema20 = self.get_indicator("ema_21")
        if ema10 is None or ema20 is None:
            return (None, 0, 0, [], [], {})
        trend_up = ema10 > ema20
        trend_dn = ema10 < ema20

        # ── ② Momentum: MACD + Stoch ──
        macd_data = self.get_indicator("macd") or {}
        stoch_data = self.get_indicator("stoch_5_3_3") or {}
        macd_val = macd_data.get("macd")
        macd_sig = macd_data.get("signal")
        stoch_k = stoch_data.get("k")
        stoch_d = stoch_data.get("d")

        mom_up = False
        mom_dn = False
        macd_up = macd_val is not None and macd_val > macd_sig
        macd_dn = macd_val is not None and macd_val < macd_sig
        stoch_up = stoch_k is not None and stoch_k > stoch_d
        stoch_dn = stoch_k is not None and stoch_k < stoch_d
        # MACD  and  Stoch 一致才给方向，打架时都不加分
        if macd_up and stoch_up:
            mom_up = True
        elif macd_dn and stoch_dn:
            mom_dn = True
        # 某指标不可实时用另一
        elif macd_up and not (stoch_up or stoch_dn):
            mom_up = True
        elif macd_dn and not (stoch_up or stoch_dn):
            mom_dn = True
        elif stoch_up and not (macd_up or macd_dn):
            mom_up = True
        elif stoch_dn and not (macd_up or macd_dn):
            mom_dn = True

        # ── ③ Volatility: ADX > 20 or ATR rising ──
        adx_val = self.get_indicator("adx")
        pdi = self.get_indicator("pdi")
        ndi = self.get_indicator("ndi")
        atr_val = self.get_indicator("atr")

        # ATR SMA(20) for comparison — 使用 DataFactory 缓存的 atr_list
        atr_list = self.get_indicator("atr_list")
        atr_sma20 = None
        if atr_list and len(atr_list) >= 10:
            atr_sma20 = sum(atr_list) / len(atr_list)

        vol_active = False
        if adx_val is not None and adx_val > 20:
            vol_active = True
        elif atr_val and atr_sma20 and atr_val > atr_sma20:
            vol_active = True

        # ── ④ Safety: RSI(10) + BB(20,2) ──
        rsi_val = self.get_indicator("rsi_10")
        bb_data = self.get_indicator("bb") or {}
        bb_mid = bb_data.get("mid")
        bb_up = bb_data.get("upper")
        bb_dn = bb_data.get("lower")

        safe_up = True
        safe_dn = True
        if bb_up is not None and bb_dn is not None:
            if rsi_val is not None:
                if close >= bb_up and rsi_val >= 70:
                    safe_up = False
                # RSI <= 35 独立封空，防止接近超卖区开空
                if rsi_val <= 35:
                    safe_dn = False

        # 高位拦截：price_position > 0.88 且 价格偏离 EMA21 > 4×ATR → 禁BUY追高，但允许SELL
        price_pos = self.get_indicator("price_position")
        _ema21 = self.get_indicator("ema_21")
        _atr = self.get_indicator("atr")
        if price_pos is not None and _ema21 is not None and _atr is not None and _atr > 0:
            _dev = (close - _ema21) / _atr  # 偏离倍数
            if price_pos > 0.82 and _dev > 2.5:
                safe_up = False
                logger.info(f"[{self.name}] 高位拦截 BUY: pp={price_pos:.2f} dev={_dev:.1f}×ATR")
            # 低位拦截：price_position < 0.12 且 偏离 < -4×ATR → 禁SELL，但允许BUY
            if price_pos < 0.18 and _dev < -2.5:
                safe_dn = False
                logger.info(f"[{self.name}] 低位拦截 SELL: pp={price_pos:.2f} dev={_dev:.1f}×ATR")

        self._load_h4_data()
        h4_trend = self._get_h4_trend(50)
        # ── Consensus ──
        logger.info(
            f"[{self.name}] Trend={'UP' if trend_up else 'DOWN'} "
            f"Mom={'UP' if mom_up else 'DOWN'} "
            f"Vol={'ACTIVE' if vol_active else 'QUIET'} "
            f"RSI={rsi_val:.1f} ADX={adx_val} "
            f"Price={close:.2f} "
            f"EMA10={ema10:.2f} EMA20={ema20:.2f} "
            f"H4={h4_trend}"
        )

        # H4 趋-trendGate：H4下行NO BUY，H4上行NO SELL
        h4_block_long = h4_trend == 'DOWN'
        h4_block_short = h4_trend == 'UP'
        if h4_block_long:
            logger.info(f"[{self.name}] H4={h4_trend} NO BUY")
        if h4_block_short:
            logger.info(f"[{self.name}] H4={h4_trend} NO SELL")

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
            "bb_std": 0,
            "h4_trend": h4_trend,
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
        if trend_up and mom_up and vol_active and safe_up and not h4_block_long:
            signal = OrderType.BUY
        elif trend_dn and mom_dn and vol_active and safe_dn and not h4_block_short:
            signal = OrderType.SELL

        return (signal, len(long_factors), len(short_factors), long_factors, short_factors, indicator_values)

    # ─────────────── Trend-aware exit multipliers ───────────────

    def _get_trend(self) -> str:
        """EMA10/20 trend: 'UP' / 'DOWN' / 'NEUTRAL'"""
        ema10 = self.get_indicator("ema_9")
        ema20 = self.get_indicator("ema_21")
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
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return round(entry_price * 0.995, 2), round(entry_price * 100, 2)
        _, hard_mult = self._get_exit_multipliers(direction == OrderType.BUY)
        dist = atr_val * hard_mult
        # 无固定 TP，由 check_ema20_exit 运行时动态管理出场
        if direction == OrderType.BUY:
            return round(entry_price - dist, 2), 0
        else:
            return round(entry_price + dist, 2), 0

    def check_ema20_exit(self, position, bid: float, ask: float) -> bool:
        """出场: 使用 BaseStrategy._run_exit_policy 统一执行出场策略"""
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")
        current_price = bid if is_buy else ask

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
        atr_val = self.get_indicator("atr")
        if atr_val is None or atr_val <= 0:
            return False

        trail_mult = td["trail_mult"]
        hard_mult = td["hard_mult"]
        pdd = self.profit_drawdown_pct
        # ADX>25 趋-trend强 → 放宽drawdown
        _ax = self.get_adx_data()
        if _ax and _ax.get("adx", 0) > 25:
            pdd = max(pdd, 0.5)
            if td.get("peak_profit", 0) > 10:
                pdd = max(pdd, 0.35)

        should_exit, exit_type, detail = self._run_exit_policy(
            td, is_buy, current_price, atr_val,
            trail_mult, hard_mult, pdd=pdd, update_peak_guard=True,
        )
        if not should_exit:
            self._last_exit_detail = None
            return False

        direction = "BUY" if is_buy else "SELL"
        detail["direction"] = direction
        self._last_exit_detail = {"exit_type": exit_type, **detail}

        if exit_type == "breakeven":
            self._last_profit_exit_time[direction] = time.time()

        logger.info(f"[{self.name}] {direction} {exit_type} ticket={ticket} {detail}")
        del self._trail_data[ticket]
        return True

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        direction = signal.get("direction", "BUY")
        ema10, ema20 = latest.get("ema_9"), latest.get("ema_21")
        rsi = latest.get("rsi", 50)
        adx = latest.get("adx", 20)
        trend_up = ema10 and ema20 and ema10 > ema20
        trend_dn = ema10 and ema20 and ema10 < ema20
        factors = signal.get("factors_long", []) if direction == "BUY" else signal.get("factors_short", [])

        if direction == "BUY":
            if any(f == "TREND-UP" for f in factors) and not trend_up:
                return False
            if any(f == "SAFE-UP" for f in factors) and rsi > 72:
                return False
        else:
            if any(f == "TREND-DN" for f in factors) and not trend_dn:
                return False
            if any(f == "SAFE-DN" for f in factors) and rsi < 32:
                return False
        return True
