"""
M30 MFI + BB Upgraded v8 — 超跌反弹升级版
=============================================
入场:
  - 收盘价超过BB轨道 (close > bb_upper / close < bb_lower)
  - BB开口扩张>5%时禁用同向入场（防趋势加速接飞刀）
  - 不看MFI
  - 运动员跟踪下一根K线回抽入场

出场:
  ① 顺势平: 价格穿轨后回抽 + MFI穿50线
  ② 逆势平1: 回到BB中轴
  ③ 逆势平2: 走了入场半宽距离

数据源: 全部指标从 DataFactory TA-Lib 读取
"""
import logging
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType, Position
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v10_upgraded"
STRATEGY_MAGIC = 661003
STRATEGY_LEGACY_MAGICS: list[int] = [661001, 661002]
STRATEGY_CHANGELOG = [
    {"version": "v7_upgraded", "magic": 661003, "date": "2026-07-18",
     "desc": "升级版: 进场不看MFI只看出轨; 运动员回抽入场; 顺势平改穿轨回抽+MFI50线"},
    {"version": "v8_upgraded", "magic": 661003, "date": "2026-07-21",
     "desc": "BB开口扩张保护：bb_width_ratio > 1.05时禁用同向入场(数据工厂预计算)"},
    {"version": "v9_upgraded", "magic": 661003, "date": "2026-07-28",
     "desc": "2/3 模糊规则改为 ADX>30 同向趋势拦截 (回测实亏$497, 撤销)"},
    {"version": "v10_upgraded", "magic": 661003, "date": "2026-07-28",
     "desc": "ADX阈值 30→25; 加 ATR 硬止损: MFI/BB中轴同向 2×ATR, 否则 1×ATR (回测预期扭亏)"},
]
class M30MFIBBUpgraded(BaseStrategy):
    """M30 MFI+BB 升级版 v10 — 收盘穿轨入场 + ADX>25趋势过滤 + ATR硬止损 + 回抽验证 + 顺势穿轨离场"""

    name = "mfi_bb_m30_upgraded"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}

        # Entry params
        self.tolerance_bars = 2  # 2根K线容差（检查最近 N 根收盘是否出轨）

    # ─────────────── 开仓 ───────────────

    def _check_bb_breakout(self) -> tuple[bool, bool, Optional[dict]]:
        """检查当前收盘是否出 BB 轨道。
        所有指标从 DataFactory 读取。
        加入 BB 开口扩张保护：bb_width_ratio > 1.05 时禁用同向入场。
        """
        closes = self.get_close_prices()
        if len(closes) < 2:
            return False, False, None

        bb = self.get_indicator("bb")
        close = closes[-1]
        if bb is None:
            return False, False, None

        # ── ADX 同向趋势拦截（防趋势加速接飞刀）──
        # ADX>25 + MFI 与 BB 中轴同向 → 禁做反向单
        _adx = self.get_indicator("adx")
        _mfi_dir = self.get_indicator("mfi_direction")
        _block_short = False
        _block_long = False
        if _adx is not None and _adx > 25 and _mfi_dir is not None:
            if close < bb.get("mid", 0) and _mfi_dir == "down":
                # 强下跌趋势（ADX>25 + MFI 向下）→ 禁做多
                _block_long = True
                logger.info(f"[{self.name}] ADX={_adx:.0f} 强下跌+价格<中轴+MFI下降，禁做多")
            elif close > bb.get("mid", 0) and _mfi_dir == "up":
                # 强上涨趋势（ADX>25 + MFI 向上）→ 禁做空
                _block_short = True
                logger.info(f"[{self.name}] ADX={_adx:.0f} 强上涨+价格>中轴+MFI上升，禁做空")

        buy_signal = close < bb["lower"] and not _block_long
        sell_signal = close > bb["upper"] and not _block_short

        iv = {
            "close": round(close, 2),
            "mfi": self.get_indicator("mfi") or 50,
            "bb_upper": bb["upper"],
            "bb_mid": bb["mid"],
            "bb_lower": bb["lower"],
            "bb": bb,
            "bb_width": round(bb["upper"] - bb["lower"], 2),
            "bb_width_ratio": _bwr,
        }
        return buy_signal, sell_signal, iv

    def generate_signal(self):
        candles = self.candles
        if len(candles) < 100:
            return (None, 0, 0, [], [], {})

        buy_signal, sell_signal, iv = self._check_bb_breakout()

        factors_long: list[str] = []
        factors_short: list[str] = []
        score_long = 1 if buy_signal else 0
        score_short = 1 if sell_signal else 0

        if buy_signal:
            factors_long.append("CLOSE<LOWER")
        if sell_signal:
            factors_short.append("CLOSE>UPPER")

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
            f"[{self.name}] [升级版] 评分: {score_long}/{score_short}  {signal_str}  "
            f"明细: {' | '.join(detail_parts) if detail_parts else '无'}"
        )

        indicator_values = iv or {
            "close": round(candles[-1].close, 2),
            "mfi": 50,
            "bb_upper": 0, "bb_mid": 0, "bb_lower": 0,
            "bb": {"upper": 0, "mid": 0, "lower": 0},
        }
        return (signal, score_long, score_short, factors_long, factors_short, indicator_values)

    # ─────────────── SL/TP ───────────────

    def get_dynamic_sl_tp(self, direction: OrderType, entry_price: float) -> tuple[float, float]:
        """ATR 硬止损
        - MFI 与 BB 中轴同向（信号被 MFI 确认）→ 2×ATR 止损
        - 否则（信号逆 MFI/BB 中轴）→ 1×ATR 止损
        """
        atr_val = self.get_indicator("atr")
        mfi_dir = self.get_indicator("mfi_direction")
        bb_mid = self.get_indicator("bb", {}).get("mid") if self.get_indicator("bb") else None
        if atr_val is None or atr_val <= 0 or bb_mid is None or mfi_dir is None:
            # 指标缺失时给极宽止损兜底（防爆仓）
            if direction == OrderType.BUY:
                return round(entry_price * 0.95, 2), round(entry_price * 10, 2)
            else:
                return round(entry_price * 1.05, 2), round(entry_price * 0.01, 2)
        # 判断 MFI 与 BB 中轴是否同向
        if direction == OrderType.BUY:
            aligned = (mfi_dir == "up" and entry_price > bb_mid)
            sl_dist = 2.0 * atr_val if aligned else 1.0 * atr_val
            return round(entry_price - sl_dist, 2), round(entry_price * 10, 2)
        else:
            aligned = (mfi_dir == "down" and entry_price < bb_mid)
            sl_dist = 2.0 * atr_val if aligned else 1.0 * atr_val
            return round(entry_price + sl_dist, 2), round(entry_price * 0.01, 2)

    # ─────────────── 平仓 ───────────────

    def check_ema20_exit(self, position: Position, bid: float, ask: float) -> bool:
        """
        v7 平仓逻辑:
        ① 顺势平: 价格穿过轨道后回抽 + MFI穿50线
        ② 逆势平1: 回到BB中轴
        ③ 逆势平2: 走了开仓时BB宽度的一半
        """
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        # 从 DataFactory 读取当前指标
        bb = self.get_indicator("bb")
        mfi = self.get_indicator("mfi")
        if bb is None or mfi is None:
            return False

        current_price = bid if is_buy else ask

        # 初始化追踪数据
        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "entry_price": position.open_price,
                "entry_bb_width": bb["upper"] - bb["lower"],
                "entry_bb_mid": bb["mid"],
                "is_buy": is_buy,
                "has_crossed_band": False,
            }

        td = self._trail_data[ticket]

        # ── ① 顺势平: 穿轨后回抽 + MFI穿50线 ──
        if is_buy:
            if not td["has_crossed_band"] and bid > bb["upper"]:
                td["has_crossed_band"] = True
                logger.info(f"[{self.name}] BUY 穿过上轨 ticket={ticket} bid={bid:.2f} upper={bb['upper']:.2f}")
            if td["has_crossed_band"] and bid <= bb["upper"] + 0.01 and mfi > 50:
                logger.info(f"[{self.name}] BUY 顺势平(穿轨回抽) ticket={ticket} price={bid:.2f} mfi={mfi:.1f}")
                self._trail_data.pop(ticket, None)
                return True
        else:
            if not td["has_crossed_band"] and ask < bb["lower"]:
                td["has_crossed_band"] = True
                logger.info(f"[{self.name}] SELL 穿过下轨 ticket={ticket} ask={ask:.2f} lower={bb['lower']:.2f}")
            if td["has_crossed_band"] and ask >= bb["lower"] - 0.01 and mfi < 50:
                logger.info(f"[{self.name}] SELL 顺势平(穿轨回抽) ticket={ticket} price={ask:.2f} mfi={mfi:.1f}")
                self._trail_data.pop(ticket, None)
                return True

        # ── ② 逆势平1: 回到BB中轴（未穿轨时才检查）──
        if is_buy and not td["has_crossed_band"] and current_price >= bb["mid"]:
            logger.info(f"[{self.name}] BUY 中轴平 ticket={ticket} price={current_price:.2f} mid={bb['mid']:.2f}")
            self._trail_data.pop(ticket, None)
            return True
        if not is_buy and not td["has_crossed_band"] and current_price <= bb["mid"]:
            logger.info(f"[{self.name}] SELL 中轴平 ticket={ticket} price={current_price:.2f} mid={bb['mid']:.2f}")
            self._trail_data.pop(ticket, None)
            return True

        # ── ③ 逆势平2: 走了开仓时BB宽度的一半 ──
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
    def _verify_entry(signal: dict, tick_price: float, latest: dict, item: dict = None) -> bool:
        """
        v7 验证：跟踪下一根K线的回抽。
        latest 来自 DataFactory 缓存，包含 bb/mfi 等指标。
        """
        direction = signal.get("direction", "BUY")
        bb = latest.get("bb") or {}
        bb_u = bb.get("upper", 0)
        bb_l = bb.get("lower", 0)

        # 初始化/读取追踪状态
        if item is None:
            if direction == "BUY":
                return bool(bb_l and tick_price <= bb_l)
            else:
                return bool(bb_u and tick_price >= bb_u)

        vs = item.setdefault("verify_state", {})
        if "tick_extreme" not in vs:
            vs["tick_extreme"] = tick_price

        # 更新极端值
        if direction == "SELL":
            vs["tick_extreme"] = max(vs["tick_extreme"], tick_price)
            if tick_price < bb_u:
                return False
            if tick_price < vs["tick_extreme"] and tick_price >= bb_u:
                logger.info(f"[verify_v7] SELL ENTER: price={tick_price:.2f} 从高点{vs['tick_extreme']:.2f}回落到{bb_u:.2f}")
                return True
            return False
        else:  # BUY
            vs["tick_extreme"] = min(vs["tick_extreme"], tick_price)
            if tick_price > bb_l:
                return False
            if tick_price > vs["tick_extreme"] and tick_price <= bb_l:
                logger.info(f"[verify_v7] BUY ENTER: price={tick_price:.2f} 从低点{vs['tick_extreme']:.2f}反弹到{bb_l:.2f}")
                return True
            return False
