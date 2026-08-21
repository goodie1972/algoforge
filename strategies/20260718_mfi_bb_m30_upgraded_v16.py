"""
M30 MFI + BB Upgraded v8 — 超跌rebound升级版
=============================================
Entry:
  - 收盘价超过BB轨道 (close > bb_upper / close < bb_lower)
  - BB开口扩 >5%时disabledsame-dirEntry（防趋-trend加速接飞刀）
  - 不看MFI
  - 运动员跟踪下一 candlesK线回抽Entry

出场:
  ① trend exit: 价格穿轨后回抽 + MFI穿50线
  ② 逆-trend平1: 回到BB midline
  ③ 逆-trend平2: 走了Entryhalf-width距离

data源: all指标从 DataFactory TA-Lib read
"""
import logging
from typing import Optional

from core.bridge import MT4BridgeBase, OrderType, Position
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v15_upgraded"
STRATEGY_MAGIC = 661003
STRATEGY_LEGACY_MAGICS: list[int] = [661001, 661002]
STRATEGY_CHANGELOG = [
    {"version": "v7_upgraded", "magic": 661003, "date": "2026-07-18",
     "desc": "升级版: entry不看MFI只看出轨; 运动员回抽Entry; trend exit改穿轨回抽+MFI50线"},
    {"version": "v8_upgraded", "magic": 661003, "date": "2026-07-21",
     "desc": "BB开口扩 保护：bb_width_ratio > 1.05时disabledsame-dirEntry(data工厂预calc)"},
    {"version": "v9_upgraded", "magic": 661003, "date": "2026-07-28",
     "desc": "2/3 模糊规则改为 ADX>30 same-dir趋-trend拦截 (回测实亏$497, 撤销)"},
    {"version": "v10_upgraded", "magic": 661003, "date": "2026-07-28",
     "desc": "ADX>25 same-dir + ATR 硬止损(same-dir2×reverse1×) (回测实亏$771, 撤销)"},
    {"version": "v11_upgraded", "magic": 661003, "date": "2026-07-28",
     "desc": "加回 BB expand same-dir保护; 硬止损统一 2×ATR (回测实亏$248, 撤销)"},
    {"version": "v12_upgraded", "magic": 661003, "date": "2026-07-28",
     "desc": "回归 v8 BB expand  3选2 保护; 加 1.5×ATR 硬止损 (回测 -$194, 仍亏)"},
    {"version": "v13_upgraded", "magic": 661003, "date": "2026-07-28",
     "desc": "BB expand 保护 3选2→严格same-dir + 1.5×ATR 硬止损 (H1  数 292  , 撤销)"},
    {"version": "v14_upgraded", "magic": 661003, "date": "2026-07-28",
     "desc": "去掉 1.5×ATR 硬止损; SL 给极宽; 让 check_ema20_exit 自然出场 (M30  数 142 / H1  数 292)"},
    {"version": "v15_upgraded", "magic": 661003, "date": "2026-07-28",
     "desc": "v14 BB expand same-dir+加回价格positionfilter (BB expand+方向+价同侧+MFIsame-dir 4 件全满足才禁same-dir)"},
    {"version": "v16", "magic": 661003, "date": "2026-08-11",
     "desc": "中线出场条件 ② 改用 entry_bb_mid（入场时中线），避免动态中线漂移导致过早出场"},
]
class M30MFIBBUpgraded(BaseStrategy):
    """M30 MFI+BB 升级版 v16 — 收盘穿轨Entry + BB expand 严格对称保护 (4件) + 中线出场跟踪穿越+固定参照 + 无硬止损"""

    name = "mfi_bb_m30_upgraded"
    legacy_magics = STRATEGY_LEGACY_MAGICS

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        super().__init__(bridge, magic, timeframe)
        self._trail_data: dict[int, dict] = {}

        # Entry params
        self.tolerance_bars = 2  # 2 candlesK线容差（check最近 N  candles收盘是否出轨）

    # ─────────────── Open ───────────────

    def _check_bb_breakout(self) -> tuple[bool, bool, Optional[dict]]:
        """checkcurrent收盘是否出 BB 轨道。
        所有指标从 DataFactory read。
        加入 BB 开口扩 保护：bb_width_ratio > 1.05 时disabledsame-dirEntry。
        """
        closes = self.get_close_prices()
        if len(closes) < 2:
            return False, False, None

        bb = self.get_indicator("bb")
        close = closes[-1]
        if bb is None:
            return False, False, None

        # ── BB 扩 same-dir趋-trend拦截（防接飞刀，严格对称版 v15）──
        # 4 件全满足 → 禁做same-dir单:
        #   1. BB 宽度扩  (>1.05)
        #   2. BB 方向 and 价格方向一致
        #   3. MFI 方向 and 价格方向一致
        #   4. 价格在 midline同侧
        #   - 强上涨: BB expand+BB上开+价格> midline+MFI不向下 → block short
        #   - 强下跌: BB expand+BB下开+价格< midline+MFI不向上 → block long
        # 矛盾时（BB up 但 MFI down）→ 可能是反转初期，不拦
        _bwr = self.get_indicator("bb_width_ratio")
        _bwd = self.get_indicator("bb_width_direction")
        _mfi = self.get_indicator("mfi")
        _mfi_dir = self.get_indicator("mfi_direction")
        _block_short = False
        _block_long = False
        _bbm = bb.get("mid", 0)
        if _bwr is not None and _bwr > 1.05 and _bwd is not None and _mfi_dir is not None and _bbm > 0:
            if _bwd == "up" and close > _bbm and _mfi_dir in ("up", "flat"):
                _block_short = True
                logger.info(f"[{self.name}] BB expand+upper open+price>mid+MFI not falling({_mfi:.0f}), strong up, block short")
            elif _bwd == "down" and close < _bbm and _mfi_dir in ("down", "flat"):
                _block_long = True
                logger.info(f"[{self.name}] BB expand+lower open+price<mid+MFI not rising({_mfi:.0f}), strong down, block long")

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
            f"[{self.name}] [升级版] Score: {score_long}/{score_short}  {signal_str}  "
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
        """v14: 不设硬止损，让 check_ema20_exit 用 BB midline/half-width/with-trend穿轨 自然出场
        SL 给极宽（50% 兜底防爆仓），实际靠 check_ema20_exit   midline出场
        """
        if direction == OrderType.BUY:
            return round(entry_price * 0.50, 2), round(entry_price * 10, 2)
        else:
            return round(entry_price * 1.50, 2), round(entry_price * 0.01, 2)

    # ─────────────── close ───────────────

    def check_ema20_exit(self, position: Position, bid: float, ask: float) -> bool:
        """
        v7 close逻辑:
        ① trend exit: 价格穿过轨道后回抽 + MFI穿50线
        ② 逆-trend平1: 回到BB midline
        ③ 逆-trend平2: 走了Open时BB宽度 一半
        """
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")

        # 从 DataFactory readcurrent指标
        bb = self.get_indicator("bb")
        mfi = self.get_indicator("mfi")
        if bb is None or mfi is None:
            return False

        current_price = bid if is_buy else ask

        # 初始化trailingdata
        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "entry_price": position.open_price,
                "entry_bb_width": bb["upper"] - bb["lower"],
                "entry_bb_mid": bb["mid"],
                "is_buy": is_buy,
                "has_crossed_band": False,
                "has_crossed_mid": False,
            }

        td = self._trail_data[ticket]

        # ── ① trend exit: 穿轨后回抽 + MFI穿50线 ──
        if is_buy:
            if not td["has_crossed_band"] and bid > bb["upper"]:
                td["has_crossed_band"] = True
                logger.info(f"[{self.name}] BUY cross up through upper band ticket={ticket} bid={bid:.2f} upper={bb['upper']:.2f}")
            if td["has_crossed_band"] and bid <= bb["upper"] + 0.01 and mfi > 50:
                logger.info(f"[{self.name}] BUY trend exit (band cross & pullback) ticket={ticket} price={bid:.2f} mfi={mfi:.1f}")
                self._trail_data.pop(ticket, None)
                return True
        else:
            if not td["has_crossed_band"] and ask < bb["lower"]:
                td["has_crossed_band"] = True
                logger.info(f"[{self.name}] SELL cross down through lower band ticket={ticket} ask={ask:.2f} lower={bb['lower']:.2f}")
            if td["has_crossed_band"] and ask >= bb["lower"] - 0.01 and mfi < 50:
                logger.info(f"[{self.name}] SELL trend exit (band cross & pullback) ticket={ticket} price={ask:.2f} mfi={mfi:.1f}")
                self._trail_data.pop(ticket, None)
                return True

        # ── ② 逆-trend平1: 价格先越过入场时中线，再返回时才出场 ──
        # 用固定 entry_bb_mid（入场时中线）做参照，避免动态中线漂移
        # SELL: 价格先涨过入场中线，再回落到入场中线以下才出场
        # BUY:  价格先跌破入场中线，再回到入场中线以上才出场
        _mid = td["entry_bb_mid"]
        if is_buy:
            if not td.get("has_crossed_mid"):
                if current_price <= _mid:
                    td["has_crossed_mid"] = True
                    logger.info(f"[{self.name}] BUY cross down mid ticket={ticket} price={current_price:.2f} mid={_mid:.2f}")
            elif current_price >= _mid:
                logger.info(f"[{self.name}] BUY midline exit ticket={ticket} price={current_price:.2f} mid={_mid:.2f}")
                self._trail_data.pop(ticket, None)
                return True
        else:
            if not td.get("has_crossed_mid"):
                if current_price >= _mid:
                    td["has_crossed_mid"] = True
                    logger.info(f"[{self.name}] SELL cross up mid ticket={ticket} price={current_price:.2f} mid={_mid:.2f}")
            elif current_price <= _mid:
                logger.info(f"[{self.name}] SELL midline exit ticket={ticket} price={current_price:.2f} mid={_mid:.2f}")
                self._trail_data.pop(ticket, None)
                return True

        # ── ③ 逆-trend平2: 走了Open时BB宽度 一半 ──
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
    def _verify_entry(signal: dict, tick_price: float, latest: dict, item: dict = None) -> bool:
        """
        v7 verify：跟踪下一 candlesK线 回抽。
        latest 来自 DataFactory 缓存，包含 bb/mfi 等指标。
        """
        direction = signal.get("direction", "BUY")
        bb = latest.get("bb") or {}
        bb_u = bb.get("upper", 0)
        bb_l = bb.get("lower", 0)

        # 初始化/readtrailing状态
        if item is None:
            if direction == "BUY":
                return bool(bb_l and tick_price <= bb_l)
            else:
                return bool(bb_u and tick_price >= bb_u)

        vs = item.setdefault("verify_state", {})
        if "tick_extreme" not in vs:
            vs["tick_extreme"] = tick_price

        # update极端值
        if direction == "SELL":
            vs["tick_extreme"] = max(vs["tick_extreme"], tick_price)
            if tick_price < bb_u:
                return False
            if tick_price < vs["tick_extreme"] and tick_price >= bb_u:
                logger.info(f"[verify_v7] SELL ENTER: price={tick_price:.2f} from high points{vs['tick_extreme']:.2f}falling to {bb_u:.2f}")
                return True
            return False
        else:  # BUY
            vs["tick_extreme"] = min(vs["tick_extreme"], tick_price)
            if tick_price > bb_l:
                return False
            if tick_price > vs["tick_extreme"] and tick_price <= bb_l:
                logger.info(f"[verify_v7] BUY ENTER: price={tick_price:.2f} from low points{vs['tick_extreme']:.2f}rebound to {bb_l:.2f}")
                return True
            return False
