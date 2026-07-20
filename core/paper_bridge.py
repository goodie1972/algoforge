"""
纸面交易桥接器 — PaperBridge

架构：三轨分离，数据委托给真实桥接，交易操作本地模拟
┌─────────────────────────────────────────────────┐
│  Engine (self.bridge → PaperBridge)              │
│    ├─ get_tick_price / get_candles → real_bridge │  ← 真实行情
│    ├─ open_order / close_order → 本地记录        │  ← 不发给MT4
│    └─ get_positions → 返回本地模拟数据           │
└─────────────────────────────────────────────────┘

策略代码未改一行 —— strategy.check_ema20_exit() 原样运行
"""
import csv
import logging
import time
from datetime import datetime
from pathlib import Path

from core.bridge import MT4BridgeBase, AccountInfo, Position, Candle, OrderType
from config.settings import LOCAL_TZ

logger = logging.getLogger(__name__)

# 纸面交易记录
_PAPERTEST_DIR = Path(__file__).resolve().parent.parent / "papertest"
_PAPERTEST_DIR.mkdir(parents=True, exist_ok=True)
CSV_TRADES = _PAPERTEST_DIR / "papertest_bridge.csv"
CSV_HEADERS = [
    "ticket", "strategy", "magic", "direction", "volume",
    "entry_time", "entry_price", "exit_time", "exit_price",
    "pnl", "commission", "net_pnl", "exit_reason",
    "stop_loss", "take_profit", "entry_bid", "entry_ask",
]


class PaperBridge(MT4BridgeBase):
    """纸面交易桥接器 — 数据委托 + 交易模拟"""

    LOT_SCALE = 100  # 0.01 手 → 1 盎司

    def __init__(self, real_bridge: MT4BridgeBase):
        self._real = real_bridge                     # 真实桥接（只用于数据）
        self._positions: dict[int | str, Position] = {}  # ticket → 模拟持仓
        self._closed: list[dict] = []                    # 已平仓记录
        self._ticket_seq_next: int = 0                   # 当天 seq
        self._ticket_day_key: str = ""                   # 当前 YYMMDD
        self._init_ticket_seq()
        self._balance: float = 0.0
        self._start_balance: float = 0.0
        self._connected: bool = False
        self._tick_cache: tuple[float, float] = (0.0, 0.0)  # (bid, ask)
        self._tick_time: float = 0
        self._equity: float = 0.0

    def _init_ticket_seq(self):
        """扫描已有 ticket，初始化当天的 seq 计数器"""
        from datetime import datetime
        now = datetime.now(tz=LOCAL_TZ)
        yy = str(now.year)[-2:]
        mm = f"{now.month:02d}"
        dd = f"{now.day:02d}"
        self._ticket_day_key = f"{yy}{mm}{dd}"
        max_seq = -1

        # 从 CSV 扫描当天
        if CSV_TRADES.exists():
            try:
                with open(str(CSV_TRADES), 'r') as f:
                    for line in f:
                        if line.strip():
                            tid = line.split(',')[0].strip()
                            if len(tid) == 8 and tid[:6] == self._ticket_day_key:
                                try:
                                    s = int(tid[6:8])
                                    if s > max_seq:
                                        max_seq = s
                                except ValueError:
                                    pass
            except Exception:
                pass
        # 从 DB 扫描当天
        try:
            from data.database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT ticket FROM trades WHERE ticket LIKE ?",
                (self._ticket_day_key + '%',)
            ).fetchall()
            conn.close()
            for row in rows:
                tid = str(row[0])
                if len(tid) == 8 and tid[:6] == self._ticket_day_key:
                    try:
                        s = int(tid[6:8])
                        if s > max_seq:
                            max_seq = s
                    except ValueError:
                        pass
        except Exception:
            pass

        self._ticket_seq_next = max_seq + 1

    def _generate_ticket(self) -> str:
        """生成 8 位纯数字票号: YYMMDDSEQ (26072000)，每天重置"""
        from datetime import datetime
        now = datetime.now(tz=LOCAL_TZ)
        yy = str(now.year)[-2:]
        mm = f"{now.month:02d}"
        dd = f"{now.day:02d}"
        key = f"{yy}{mm}{dd}"

        # 天变了 → 重置 seq
        if key != self._ticket_day_key:
            self._ticket_day_key = key
            self._ticket_seq_next = 0

        seq = self._ticket_seq_next
        if seq > 99:
            seq = 0  # wrap，一天 100 张几乎不可能
        self._ticket_seq_next = seq + 1

        return f"{key}{seq:02d}"

    # ═══════════════ 连接管理 ═══════════════

    def connect(self) -> bool:
        """连接真实桥接（仅用于数据），保存初始余额"""
        ok = self._real.connect()
        if ok:
            info = self._real.get_account_info()
            if info:
                self._balance = info.balance
                self._equity = info.equity
                self._start_balance = info.balance
                logger.info(f"[PaperBridge] 启动，初始余额=${self._balance:.2f}")
            self._connected = True
        return ok

    def disconnect(self):
        self._real.disconnect()
        self._connected = False

    def send_heartbeat(self) -> bool:
        return self._real.send_heartbeat()

    def get_server_time(self, symbol: str = "XAUUSD") -> int:
        return self._real.get_server_time(symbol)

    # ═══════════════ 数据操作 → 委托真实桥接 ═══════════════

    def get_tick_price(self, symbol: str) -> tuple[float, float]:
        """从真实桥接获取最新行情"""
        bid, ask = self._real.get_tick_price(symbol)
        if bid > 0:
            self._tick_cache = (bid, ask)
            self._tick_time = time.time()
        elif self._tick_cache[0] > 0:
            bid, ask = self._tick_cache
        return bid, ask

    def get_candles(self, symbol: str, timeframe: str, count: int, offset: int = 0) -> list[Candle]:
        return self._real.get_candles(symbol, timeframe, count, offset)

    def get_account_info(self) -> Optional[AccountInfo]:
        """返回模拟余额 + 浮动盈亏"""
        info = self._real.get_account_info()
        if info is None:
            return None
        # 计算浮动盈亏
        floating = self._calc_floating_pnl()
        equity = self._balance + floating
        return AccountInfo(
            login=info.login,
            balance=round(self._balance, 2),
            equity=round(max(equity, 0), 2),
            margin=info.margin,
            free_margin=info.free_margin,
            currency=info.currency,
            leverage=info.leverage,
        )

    # ═══════════════ 持仓操作 → 本地模拟 ═══════════════

    def get_positions(self, symbol: str = None) -> list[Position]:
        """返回模拟持仓（更新浮动盈亏）"""
        bid, ask = self.get_tick_price("XAUUSD")
        result = []
        for pos in list(self._positions.values()):
            if symbol and pos.symbol != symbol:
                continue
            # 更新当前价格和浮动盈亏
            if pos.order_type in ("OP_BUY", "BUY"):
                pos.current_price = bid
                pos.profit = round((bid - pos.open_price) * pos.volume * self.LOT_SCALE, 2)
            else:
                pos.current_price = ask
                pos.profit = round((pos.open_price - ask) * pos.volume * self.LOT_SCALE, 2)
            result.append(pos)
        return result

    def get_order_history(self, symbol: str = None) -> list[dict]:
        """返回已平仓记录（兼容引擎的 get_order_history 调用）"""
        result = []
        for t in self._closed:
            if symbol and t.get("symbol") and t["symbol"] != symbol:
                continue
            result.append({
                "ticket": t["ticket"],
                "symbol": t.get("symbol", "XAUUSD"),
                "order_type": t["direction"],
                "magic": t["magic"],
                "volume": t["volume"],
                "open_price": t["entry_price"],
                "open_time": t["entry_unix"],
                "close_price": t["exit_price"],
                "close_time": t["exit_unix"],
                "profit": t["pnl"],
                "swap": 0.0,
                "commission": t["commission"],
                "stop_loss": t.get("stop_loss", 0),
                "take_profit": t.get("take_profit", 0),
                "comment": t.get("comment", ""),
            })
        return result

    def open_order(self, symbol: str, order_type: OrderType, volume: float,
                   price: float = 0, sl: float = 0, tp: float = 0,
                   comment: str = "", magic: int = 0) -> str | None:
        """用当前价格模拟开仓"""
        bid, ask = self.get_tick_price(symbol)
        open_price = ask if order_type == OrderType.BUY else bid
        if price > 0:
            open_price = price
        if bid <= 0:
            logger.error(f"[PaperBridge] 无法开仓：无行情数据")
            return None

        ticket = self._generate_ticket()

        self._positions[ticket] = Position(
            ticket=ticket,
            symbol=symbol,
            order_type="OP_BUY" if order_type == OrderType.BUY else "OP_SELL",
            volume=volume,
            open_price=open_price,
            current_price=open_price,
            stop_loss=sl,
            take_profit=tp,
            profit=0.0,
            swap=0.0,
            commission=0.0,
            magic=magic,
            comment=comment,
            open_time=str(int(time.time())),
        )

        logger.info(f"[PaperBridge] 模拟开仓: {order_type.value} {symbol} "
                    f"{volume}手 @ {open_price:.2f} "
                    f"SL={sl:.2f} TP={tp:.2f} Ticket={ticket} "
                    f"策略={comment} Magic={magic}")

        # 记录到 CSV（入场行，出场行为空）
        self._append_csv({
            "ticket": ticket,
            "strategy": comment,
            "magic": magic,
            "direction": order_type.value,
            "volume": volume,
            "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "entry_price": round(open_price, 2),
            "exit_time": "",
            "exit_price": "",
            "pnl": "",
            "commission": "",
            "net_pnl": "",
            "exit_reason": "",
            "stop_loss": round(sl, 2) if sl else "",
            "take_profit": round(tp, 2) if tp else "",
            "entry_bid": round(bid, 2),
            "entry_ask": round(ask, 2),
        })
        return ticket

    def close_order(self, ticket: int | str, volume: float = 0) -> bool:
        """用当前价格模拟平仓"""
        if ticket not in self._positions:
            logger.warning(f"[PaperBridge] 平仓失败：Ticket={ticket} 不存在")
            return False

        pos = self._positions.pop(ticket)
        bid, ask = self.get_tick_price(pos.symbol)

        if pos.order_type in ("OP_BUY", "BUY"):
            exit_price = bid
            pnl = (bid - pos.open_price) * pos.volume * self.LOT_SCALE
        else:
            exit_price = ask
            pnl = (pos.open_price - ask) * pos.volume * self.LOT_SCALE

        commission = 0.5 * 2  # 开仓+平仓，0.5/张
        net_pnl = pnl - commission
        self._balance += net_pnl

        record = {
            "ticket": ticket,
            "magic": pos.magic,
            "strategy": pos.comment,
            "direction": "BUY" if pos.order_type in ("OP_BUY", "BUY") else "SELL",
            "volume": pos.volume,
            "symbol": pos.symbol,
            "entry_price": pos.open_price,
            "exit_price": exit_price,
            "pnl": round(pnl, 2),
            "commission": commission,
            "net_pnl": round(net_pnl, 2),
            "stop_loss": pos.stop_loss,
            "take_profit": pos.take_profit,
            "entry_unix": int(pos.open_time) if pos.open_time.isdigit() else 0,
            "exit_unix": int(time.time()),
            "comment": pos.comment,
        }
        self._closed.append(record)

        logger.info(f"[PaperBridge] 模拟平仓: Ticket={ticket} "
                    f"{pos.order_type} {pos.comment} "
                    f"入场={pos.open_price:.2f} 出场={exit_price:.2f} "
                    f"盈亏=${pnl:.2f} 净=${net_pnl:.2f}")

        # CSV 追加出场信息
        self._append_csv({
            "ticket": ticket,
            "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exit_price": round(exit_price, 2),
            "pnl": round(pnl, 2),
            "commission": round(commission, 2),
            "net_pnl": round(net_pnl, 2),
            # 下面的字段留空（入场时已写）
            "strategy": "",
            "magic": "",
            "direction": "",
            "volume": "",
            "entry_time": "",
            "entry_price": "",
            "exit_reason": "",
            "stop_loss": "",
            "take_profit": "",
            "entry_bid": "",
            "entry_ask": "",
        })
        return True

    def modify_order(self, ticket: int | str, sl: float = 0, tp: float = 0) -> bool:
        """本地更新 SL/TP"""
        if ticket in self._positions:
            self._positions[ticket].stop_loss = sl
            self._positions[ticket].take_profit = tp
            logger.info(f"[PaperBridge] 修改 Ticket={ticket} SL={sl:.2f} TP={tp:.2f}")
            return True
        return False

    def takeover_existing_positions(self, symbol: str = None, magic: int = 0) -> list[Position]:
        """纸面模式无真实持仓需要接管，返回空"""
        logger.info(f"[PaperBridge] 纸面模式：跳过真实持仓接管")
        return []

    # ═══════════════ 内部 ═══════════════

    def _calc_floating_pnl(self) -> float:
        """计算所有持仓的浮动盈亏"""
        bid, ask = self.get_tick_price("XAUUSD")
        total = 0.0
        for pos in self._positions.values():
            if pos.order_type in ("OP_BUY", "BUY"):
                total += (bid - pos.open_price) * pos.volume * self.LOT_SCALE
            else:
                total += (pos.open_price - ask) * pos.volume * self.LOT_SCALE
        return total

    def _append_csv(self, row: dict):
        """追加一行到 CSV（开仓或平仓字段）"""
        exists = CSV_TRADES.exists()
        full = {}
        for h in CSV_HEADERS:
            full[h] = str(row.get(h, ""))
        with open(CSV_TRADES, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, CSV_HEADERS)
            if not exists:
                w.writeheader()
            w.writerow(full)

    def get_trade_stats(self) -> dict:
        """获取当前纸面交易统计"""
        wins = sum(1 for t in self._closed if t["net_pnl"] > 0)
        losses = sum(1 for t in self._closed if t["net_pnl"] <= 0)
        total_pnl = sum(t["net_pnl"] for t in self._closed)
        return {
            "total_trades": len(self._closed),
            "open_positions": len(self._positions),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(self._closed) * 100, 1) if self._closed else 0,
            "total_pnl": round(total_pnl, 2),
            "balance": round(self._balance, 2),
            "floating_pnl": round(self._calc_floating_pnl(), 2),
            "start_balance": round(self._start_balance, 2),
            "return_pct": round((self._balance - self._start_balance) / self._start_balance * 100, 2) if self._start_balance else 0,
        }
