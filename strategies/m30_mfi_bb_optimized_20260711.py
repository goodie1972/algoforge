"""
M30 MFI + 布林带均值回归 (优化版) — 均值回归策略
========================================
- 开仓：MFI 极端值 + BB 触轨（2根K线容差，更精确）
- 平仓：顺势（另一极端+另一轨）/ 逆势（中轴 或 半宽）
- 特点：更严格的 MFI 阈值（85/15），更高信号质量
数据源: 全部指标从 DataFactory TA-Lib 读取
"""

import logging
import math
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType, Position
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v6_optimized"
STRATEGY_MAGIC = 661002
STRATEGY_LEGACY_MAGICS: list[int] = [661001]
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 661001, "date": "2026-06-26", "desc": "初始上线：MFI+BB 双模策略"},
    {"version": "v2", "magic": 661001, "date": "2026-07-01", "desc": "MFI超买 80→70 不对称化"},
    {"version": "v3", "magic": 661001, "date": "2026-07-01", "desc": "趋势模式 profit_drawdown 放宽至40%"},
    {"version": "v4", "magic": 661001, "date": "2026-07-01", "desc": "趋势模式MFI中值回调(40-60)作为核心入场条件"},
    {"version": "v5", "magic": 661001, "date": "2026-07-03", "desc": "全面重写：纯均值回归，MFI 80/20+BB触轨，3根K线容差，中轴/半宽平仓"},
    {"version": "v6_optimized", "magic": 661002, "date": "2026-07-11", "desc": "优化版：MFI阈值收紧至85/15，容差降至2根，提高信号质量"},
]


class M30MFIBBOptimized(BaseStrategy):
    """M30 MFI + 布林带均值回归策略 (v6_optimized)"""

    name = "mfi_bb_m30_optimized"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}

        # Entry params - tightened for quality
        self.mfi_overbought = 85
        self.mfi_oversold = 15
        self.bb_period = 20
        self.bb_std = 2.0
        self.tolerance_bars = 2  # 2根K线容差（更精确）

        # Exit params (无 ATR，用 BB 中轴/半宽)

    # ─────────────── 本地指标计算（用于历史 tolerance_bars 根容差检测）───────────────

    @staticmethod
    def _calc_stddev(closes: list[float], sma: float) -> float:
        return math.sqrt(sum((c - sma) ** 2 for c in closes) / len(closes))

    def _calc_bb_at(self, candles: list, idx: int) -> Optional[dict]:
        """计算 candle[idx] 时刻的 BB(20,2)"""
        if idx < self.bb_period - 1:
            return None
        sub = candles[idx - self.bb_period + 1: idx + 1]
        closes = [c.close for c in sub]
        sma = sum(closes) / self.bb_period
        std = self._calc_stddev(closes, sma)
        return {
            "upper": round(sma + self.bb_std * std, 2),
            "mid": round(sma, 2),
            "lower": round(sma - self.bb_std * std, 2),
        }

    def _calc_mfi_at(self, candles: list, idx: int, period: int = 14) -> Optional[float]:
        """计算 candle[idx] 时刻的 MFI(14)"""
        if idx < period:
            return None
        sub = candles[idx - period: idx + 1]
        tp = [(c.high + c.low + c.close) / 3 for c in sub]
        mf = [tp[i] * sub[i].volume for i in range(len(sub))]
        pos = neg = 0.0
        for i in range(1, len(mf)):
            if tp[i] > tp[i - 1]:
                pos += mf[i]
            else:
                neg += mf[i]
        if neg == 0:
            return 100.0
        mfr = pos / neg
        return round(100.0 - 100.0 / (1.0 + mfr), 2)

    def _check_3bar_condition(self) -> tuple[bool, bool, Optional[dict]]:
        """
        检查最近 self.tolerance_bars 根K线内是否满足开仓条件。
        返回: (has_buy_signal, has_sell_signal, indicator_values)
        """
        candles = self.candles
        if len(candles) < max(self.bb_period, 14) + self.tolerance_bars:
            return False, False, None

        last3 = candles[-self.tolerance_bars:]
        base_idx = len(candles) - self.tolerance_bars

        bb_touch_upper = [False] * self.tolerance_bars
        bb_touch_lower = [False] * self.tolerance_bars
        mfi_overbought_flag = [False] * self.tolerance_bars
        mfi_oversold_flag = [False] * self.tolerance_bars

        for i, candle in enumerate(last3):
            idx = base_idx + i
            bb = self._calc_bb_at(candles, idx)
            if bb:
                bb_touch_upper[i] = candle.high >= bb["upper"]
                bb_touch_lower[i] = candle.low <= bb["lower"]
            mfi_val = self._calc_mfi_at(candles, idx)
            if mfi_val is not None:
                mfi_overbought_flag[i] = mfi_val >= self.mfi_overbought
                mfi_oversold_flag[i] = mfi_val <= self.mfi_oversold

        has_bb_upper = any(bb_touch_upper)
        has_bb_lower = any(bb_touch_lower)
        has_mfi_ob = any(mfi_overbought_flag)
        has_mfi_os = any(mfi_oversold_flag)

        # SELL: MFI>=85 + price>=BB上轨（tolerance_bars 根内均可）
        sell_signal = has_bb_upper and has_mfi_ob
        # BUY: MFI<=15 + price<=BB下轨（tolerance_bars 根内均可）
        buy_signal = has_bb_lower and has_mfi_os

        # 构建指标值（最新的）
        latest_bb = self._calc_bb_at(candles, len(candles) - 1)
        latest_mfi = self._calc_mfi_at(candles, len(candles) - 1)
        iv = {
            "close": round(candles[-1].close, 2),
            "mfi": latest_mfi,
            "bb_upper": latest_bb["upper"] if latest_bb else 0,
            "bb_mid": latest_bb["mid"] if latest_bb else 0,
            "bb_lower": latest_bb["lower"] if latest_bb else 0,
            "has_bb_upper_3bar": has_bb_upper,
            "has_bb_lower_3bar": has_bb_lower,
            "has_mfi_ob_3bar": has_mfi_ob,
            "has_mfi_os_3bar": has_mfi_os,
        }
        return buy_signal, sell_signal, iv

    # ─────────────── 开仓 ───────────────

    def generate_signal(self) -> Optional[OrderType]:
        candles = self.candles
        if len(candles) < 100:
            logger.debug(f"[{self.name}] 数据不足: {len(candles)} < 100")
            return None

        buy_signal, sell_signal, iv = self._check_3bar_condition()

        # ── 构建因子明细 ──
        factors_long: list[str] = []
        factors_short: list[str] = []
        score_long = 0
        score_short = 0

        if buy_signal:
            score_long = 1
            factors_long.append("BB-LOW+MFI-OS")
        if sell_signal:
            score_short = 1
            factors_short.append("BB-UP+MFI-OB")

        signal = None
        signal_str = "无信号"
        if score_long >= 1:
            signal = OrderType.BUY
            signal_str = "LONG"
        elif score_short >= 1:
            signal = OrderType.SELL
            signal_str = "SELL"

        detail_parts = []
        if factors_long:
            detail_parts.append("LONG: " + " ".join(factors_long))
        if factors_short:
            detail_parts.append("SHORT: " + " ".join(factors_short))

        logger.info(
            f"[{self.name}] [平均回归] 评分: {score_long}/{score_short}  {signal_str}  "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )

        indicator_values = iv or {
            "close": round(candles[-1].close, 2),
            "mfi": self._calc_mfi_at(candles, len(candles) - 1),
            "bb_upper": 0, "bb_mid": 0, "bb_lower": 0,
            "has_bb_upper_3bar": False, "has_bb_lower_3bar": False,
            "has_mfi_ob_3bar": False, "has_mfi_os_3bar": False,
        }
        # 补充嵌套 bb 键，与数据工厂缓存结构对齐（_verify_entry 回退路径需要）
        if "bb" not in indicator_values:
            indicator_values["bb"] = {
                "upper": indicator_values.get("bb_upper", 0),
                "mid": indicator_values.get("bb_mid", 0),
                "lower": indicator_values.get("bb_lower", 0),
            }
        return (signal, score_long, score_short, factors_long, factors_short, indicator_values)

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """不用传统SL/TP，全部交给 check_ema20_exit 管理"""
        # 给一个极宽止损防爆仓
        if direction == OrderType.BUY:
            return round(entry_price * 0.95, 2), round(entry_price * 10, 2)
        else:
            return round(entry_price * 1.05, 2), round(entry_price * 0.01, 2)

    # ─────────────── 平仓 ───────────────

    def check_ema20_exit(self, position: Position, bid: float, ask: float) -> bool:
        """
        v6_optimized 平仓逻辑（与 v5 相同）：
        - 顺势平：MFI另一极端 + 碰另一轨（tolerance_bars 根容差）
        - 逆势平1：价格回到BB中轴
        - 逆势平2：价格走了开仓时BB宽度的一半
        """
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        # 计算当前BB/MFI
        candles = self.candles
        if len(candles) < 30:
            return False

        curr_bb = self._calc_bb_at(candles, len(candles) - 1)
        curr_mfi = self._calc_mfi_at(candles, len(candles) - 1)
        if curr_bb is None or curr_mfi is None:
            return False

        current_price = bid if is_buy else ask

        # ── 初始化追踪数据 ──
        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "entry_price": position.open_price,
                "entry_bb_width": curr_bb["upper"] - curr_bb["lower"],
                "entry_bb_mid": curr_bb["mid"],
                "is_buy": is_buy,
            }

        td = self._trail_data[ticket]

        # ── ① 顺势平：MFI另一极端 + 另一轨（tolerance_bars 根容差检测） ──
        buy_signal, sell_signal, _ = self._check_3bar_condition()
        if is_buy and sell_signal:
            # BUY持仓 → 出现SELL信号（MFI<=15+BB下轨）
            logger.info(f"[{self.name}] BUY 顺势平 ticket={ticket} price={current_price:.2f}")
            self._trail_data.pop(ticket, None)
            return True
        if not is_buy and buy_signal:
            # SELL持仓 → 出现BUY信号（MFI>=85+BB上轨）
            logger.info(f"[{self.name}] SELL 顺势平 ticket={ticket} price={current_price:.2f}")
            self._trail_data.pop(ticket, None)
            return True

        # ── ② 逆势平1：价格回到BB中轴 ──
        if is_buy and current_price >= curr_bb["mid"]:
            logger.info(f"[{self.name}] BUY 中轴平 ticket={ticket} price={current_price:.2f} mid={curr_bb['mid']:.2f}")
            self._trail_data.pop(ticket, None)
            return True
        if not is_buy and current_price <= curr_bb["mid"]:
            logger.info(f"[{self.name}] SELL 中轴平 ticket={ticket} price={current_price:.2f} mid={curr_bb['mid']:.2f}")
            self._trail_data.pop(ticket, None)
            return True

        # ── ③ 逆势平2：走了开仓时BB宽度的一半 ──
        half_width = td["entry_bb_width"] / 2
        if is_buy:
            if current_price >= td["entry_price"] + half_width:
                logger.info(f"[{self.name}] BUY 半宽平 ticket={ticket} price={current_price:.2f} "
                            f"entry={td['entry_price']:.2f} half={half_width:.2f}")
                self._trail_data.pop(ticket, None)
                return True
        else:
            if current_price <= td["entry_price"] - half_width:
                logger.info(f"[{self.name}] SELL 半宽平 ticket={ticket} price={current_price:.2f} "
                            f"entry={td['entry_price']:.2f} half={half_width:.2f}")
                self._trail_data.pop(ticket, None)
                return True

        return False

    # ─────────────── 验证入场 ───────────────

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        """
        v6_optimized 验证：容差检测已由 generate_signal 确认，这里只验证信号有效性。
        更宽松的验证：价格容忍度放宽至±1.5%，MFI阈值匹配收紧后的策略参数。
        - SELL: 价格还在BB上轨±1.5%以内，MFI未跌到15以下
        - BUY:  价格还在BB下轨±1.5%以内，MFI未涨到85以上
        """
        direction = signal.get("direction", "BUY")
        bb = latest.get("bb") or {}
        mfi = latest.get("mfi", 50)
        bb_u = bb.get("upper", 0)
        bb_l = bb.get("lower", 0)

        logger = logging.getLogger(__name__)

        if direction == "BUY":
            if bb_l and tick_price > bb_l * 1.015:
                logger.info(f"[verify] BUY REJECT: price={tick_price:.2f} > bb_lower*1.015={bb_l*1.015:.2f}")
                return False
            if mfi > 85:
                logger.info(f"[verify] BUY REJECT: mfi={mfi:.1f} > 85")
                return False
            logger.info(f"[verify] BUY PASS: price={tick_price:.2f} bb_l={bb_l:.2f} mfi={mfi:.1f}")
        else:
            if bb_u and tick_price < bb_u * 0.985:
                logger.info(f"[verify] SELL REJECT: price={tick_price:.2f} < bb_upper*0.985={bb_u*0.985:.2f} bb_u={bb_u}")
                return False
            if mfi < 15:
                logger.info(f"[verify] SELL REJECT: mfi={mfi:.1f} < 15")
                return False
            logger.info(f"[verify] SELL PASS: price={tick_price:.2f} bb_u={bb_u:.2f} mfi={mfi:.1f}")
        return True
