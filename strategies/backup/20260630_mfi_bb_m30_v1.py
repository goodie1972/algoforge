"""
M30 MFI + 布林带均值回归 — 均值回归strategy
=============================
- Open：MFI 极端值 + BB 触轨（3 candlesK线容差）
- close：with-trend（另一极端+另一轨）/ 逆-trend（ midline 或 half-width）
data源: all指标从 DataFactory TA-Lib read
"""

import logging
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType, Position
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v5"
STRATEGY_MAGIC = 661001
STRATEGY_LEGACY_MAGICS: list[int] = []
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 661001, "date": "2026-06-26", "desc": "初始上线：MFI+BB 双模strategy"},
    {"version": "v2", "magic": 661001, "date": "2026-07-01", "desc": "MFI超买 80→70 不对称化"},
    {"version": "v3", "magic": 661001, "date": "2026-07-01", "desc": "趋-trendmode profit_drawdown 放宽至40%"},
    {"version": "v4", "magic": 661001, "date": "2026-07-01", "desc": "趋-trendmodeMFI 值回调(40-60)作为核心Entry件"},
    {"version": "v5", "magic": 661001, "date": "2026-07-03", "desc": "全面重写：纯均值回归，MFI 80/20+BB触轨，3 candlesK线容差， midline/half-width exit仓"},
]


class M30MFIBBStrategy(BaseStrategy):
    """M30 MFI + 布林带均值回归strategy (v5)"""

    name = "mfi_bb_m30"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}

        # Entry params
        self.mfi_overbought = 80
        self.mfi_oversold = 20
        self.bb_period = 20
        self.bb_std = 2.0
        self.tolerance_bars = 3  # 3 candlesK线容差

        # Exit params (无 ATR，用 BB  midline/half-width)

    # ─────────────── 从 DataFactory 缓存读取当前指标 ───────────────

    def _check_3bar_condition(self) -> tuple[bool, bool, Optional[dict]]:
        """
        检查当前K线是否满足开仓条件。
        从 DataFactory 缓存读取当前 bb / mfi 扁平值。
        return: (has_buy_signal, has_sell_signal, indicator_values)
        """
        candles = self.candles
        if len(candles) < max(self.bb_period, 14) + 1:
            return False, False, None

        bb = self.get_indicator("bb")
        mfi = self.get_indicator("mfi")
        if bb is None or mfi is None:
            return False, False, None

        close = candles[-1].close
        high = candles[-1].high
        low = candles[-1].low

        bb_touch_upper = high >= bb["upper"]
        bb_touch_lower = low <= bb["lower"]
        mfi_overbought = mfi >= self.mfi_overbought
        mfi_oversold = mfi <= self.mfi_oversold

        # SELL: MFI≥80 + price≥BBupper
        sell_signal = bb_touch_upper and mfi_overbought
        # BUY: MFI≤20 + price≤BBlower
        buy_signal = bb_touch_lower and mfi_oversold

        iv = {
            "close": round(close, 2),
            "mfi": mfi,
            "bb_upper": bb["upper"],
            "bb_mid": bb["mid"],
            "bb_lower": bb["lower"],
            "has_bb_upper_3bar": bb_touch_upper,
            "has_bb_lower_3bar": bb_touch_lower,
            "has_mfi_ob_3bar": mfi_overbought,
            "has_mfi_os_3bar": mfi_oversold,
        }
        return buy_signal, sell_signal, iv

    # ─────────────── Open ───────────────

    def generate_signal(self) -> Optional[OrderType]:
        candles = self.candles
        if len(candles) < 100:
            logger.debug(f"[{self.name}] datainsufficient: {len(candles)} < 100")
            return None

        buy_signal, sell_signal, iv = self._check_3bar_condition()

        # ── build因子明细 ──
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
        signal_str = "No signal"
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
            f"[{self.name}] [avg回归] Score: {score_long}/{score_short}  {signal_str}  "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )

        indicator_values = iv or {
            "close": round(candles[-1].close, 2),
            "mfi": self.get_indicator("mfi"),
            "bb_upper": 0, "bb_mid": 0, "bb_lower": 0,
            "has_bb_upper_3bar": False, "has_bb_lower_3bar": False,
            "has_mfi_ob_3bar": False, "has_mfi_os_3bar": False,
        }
        # 补充嵌套 bb 键， and data工厂缓存结构对齐（_verify_entry 回退路径需要）
        if "bb" not in indicator_values:
            indicator_values["bb"] = {
                "upper": indicator_values.get("bb_upper", 0),
                "mid": indicator_values.get("bb_mid", 0),
                "lower": indicator_values.get("bb_lower", 0),
            }
        return (signal, score_long, score_short, factors_long, factors_short, indicator_values)

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """不用传统SL/TP，all交给 check_ema20_exit 管理"""
        # 给一极宽止损防爆仓
        if direction == OrderType.BUY:
            return round(entry_price * 0.95, 2), round(entry_price * 10, 2)
        else:
            return round(entry_price * 1.05, 2), round(entry_price * 0.01, 2)

    # ─────────────── close ───────────────

    def check_ema20_exit(self, position: Position, bid: float, ask: float) -> bool:
        """
        v5 close逻辑：
        - trend exit：MFI另一极端 + 碰另一轨（3 candles容差）
        - 逆-trend平1：价格回到BB midline
        - 逆-trend平2：价格走了Open时BB宽度 一半
        """
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        # 从缓存读取当前 BB/MFI
        curr_bb = self.get_indicator("bb")
        curr_mfi = self.get_indicator("mfi")
        if curr_bb is None or curr_mfi is None:
            return False

        current_price = bid if is_buy else ask

        # ── 初始化trailingdata ──
        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "entry_price": position.open_price,
                "entry_bb_width": curr_bb["upper"] - curr_bb["lower"],
                "entry_bb_mid": curr_bb["mid"],
                "is_buy": is_buy,
            }

        td = self._trail_data[ticket]

        # ── ① trend exit：MFI另一极端 + 另一轨（3 candles容差检测） ──
        buy_signal, sell_signal, _ = self._check_3bar_condition()
        if is_buy and sell_signal:
            # BUYPositions → 出现SELLSignal（MFI≤20+BBlower band）
            logger.info(f"[{self.name}] BUY with-trendexit ticket={ticket} price={current_price:.2f}")
            self._trail_data.pop(ticket, None)
            return True
        if not is_buy and buy_signal:
            # SELLPositions → 出现BUYSignal（MFI≥80+BBupper band）
            logger.info(f"[{self.name}] SELL with-trendexit ticket={ticket} price={current_price:.2f}")
            self._trail_data.pop(ticket, None)
            return True

        # ── ② 逆-trend平1：价格回到BB midline ──
        if is_buy and current_price >= curr_bb["mid"]:
            logger.info(f"[{self.name}] BUY midline exit ticket={ticket} price={current_price:.2f} mid={curr_bb['mid']:.2f}")
            self._trail_data.pop(ticket, None)
            return True
        if not is_buy and current_price <= curr_bb["mid"]:
            logger.info(f"[{self.name}] SELL midline exit ticket={ticket} price={current_price:.2f} mid={curr_bb['mid']:.2f}")
            self._trail_data.pop(ticket, None)
            return True

        # ── ③ 逆-trend平2：走了Open时BB宽度 一半 ──
        half_width = td["entry_bb_width"] / 2
        if is_buy:
            if current_price >= td["entry_price"] + half_width:
                logger.info(f"[{self.name}] BUY half-widthexit ticket={ticket} price={current_price:.2f} "
                            f"entry={td['entry_price']:.2f} half={half_width:.2f}")
                self._trail_data.pop(ticket, None)
                return True
        else:
            if current_price <= td["entry_price"] - half_width:
                logger.info(f"[{self.name}] SELL half-widthexit ticket={ticket} price={current_price:.2f} "
                            f"entry={td['entry_price']:.2f} half={half_width:.2f}")
                self._trail_data.pop(ticket, None)
                return True

        return False

    # ─────────────── verifyEntry ───────────────

    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict) -> bool:
        """
        v5 verify：3 candles内容差由 generate_signal confirm，这里只verifySignal有效性：
        - SELL: 价格还在BBupper band±1%以内，MFI未跌到20以下
        - BUY:  价格还在BBlower band±1%以内，MFI未涨到80以上
        """
        direction = signal.get("direction", "BUY")
        bb = latest.get("bb") or {}
        mfi = latest.get("mfi", 50)
        bb_u = bb.get("upper", 0)
        bb_l = bb.get("lower", 0)

        logger = logging.getLogger(__name__)

        if direction == "BUY":
            if bb_l and tick_price > bb_l * 1.01:
                logger.info(f"[verify] BUY REJECT: price={tick_price:.2f} > bb_lower*1.01={bb_l*1.01:.2f}")
                return False
            if mfi > 80:
                logger.info(f"[verify] BUY REJECT: mfi={mfi:.1f} > 80")
                return False
            logger.info(f"[verify] BUY PASS: price={tick_price:.2f} bb_l={bb_l:.2f} mfi={mfi:.1f}")
        else:
            if bb_u and tick_price < bb_u * 0.99:
                logger.info(f"[verify] SELL REJECT: price={tick_price:.2f} < bb_upper*0.99={bb_u*0.99:.2f} bb_u={bb_u}")
                return False
            if mfi < 20:
                logger.info(f"[verify] SELL REJECT: mfi={mfi:.1f} < 20")
                return False
            logger.info(f"[verify] SELL PASS: price={tick_price:.2f} bb_u={bb_u:.2f} mfi={mfi:.1f}")
        return True
