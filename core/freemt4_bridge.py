"""
FreeMT4 桥接实现 - 通过 Socket 与 MT4 中的 FreeMT4Bridge EA 通信
协议: 自定义 # 分隔格式 (兼容 PyTrader V1.02 协议)
EA 源码: tools/FreeMT4Bridge.mq4
"""

import socket
import logging
import threading
import time
from typing import Optional
from datetime import datetime

from config.settings import FREEMT4_HOST, FREEMT4_PORT, MAGIC_NUMBER, SYMBOL, LOT_SIZE, SLIPPAGE
from core.bridge import (
    MT4BridgeBase, Position, Candle, AccountInfo, OrderType
)

logger = logging.getLogger(__name__)

# MQL4 timeframe 值 (分钟数格式)
TF_MAP = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440, "W1": 10080, "MN1": 43200,
}


class FreeMT4Bridge(MT4BridgeBase):
    """通过 FreeMT4Bridge EA 连接 MT4 - 自定义 # 分隔协议"""

    RECONNECT_INTERVAL = 3.0  # 重连间隔至少 3 秒

    def __init__(self):
        self._sock: Optional[socket.socket] = None
        self._connected = False
        self._lock = threading.Lock()
        self._last_reconnect = 0.0

    def connect(self) -> bool:
        self.disconnect()

        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(5)
            self._sock.connect((FREEMT4_HOST, FREEMT4_PORT))
            self._connected = True

            if not self._check_alive():
                self.disconnect()
                return False

            logger.info(f"[FreeMT4] 已连接到 {FREEMT4_HOST}:{FREEMT4_PORT}")
            info = self.get_account_info()
            if info:
                logger.info(f"[FreeMT4] 账户 #{info.login} 余额: {info.balance} {info.currency}")
            return True
        except Exception:
            self.disconnect()
            return False

    def disconnect(self):
        self._connected = False
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _try_reconnect(self) -> bool:
        """限速重连，3 秒内不重复尝试"""
        now = time.time()
        if now - self._last_reconnect < self.RECONNECT_INTERVAL:
            return False
        self._last_reconnect = now
        logger.info("[FreeMT4] 尝试重连...")
        ok = self.connect()
        if ok:
            logger.info("[FreeMT4] 重连成功")
        return ok

    # ======================== 底层通信 ========================

    def _recv_raw(self) -> str:
        """接收直到遇到 ! 终止符"""
        data = b""
        while True:
            try:
                chunk = self._sock.recv(500000)
            except Exception:
                raise ConnectionError("连接已关闭")
            if not chunk:
                raise ConnectionError("连接已关闭")
            data += chunk
            text = data.decode("utf-8")
            if text.endswith("!"):
                return text[:-1]

    def _send_cmd(self, cmd: str) -> Optional[list]:
        """非递归发送命令，断连时最多重连一次重试"""
        for attempt in range(2):
            if not self._connected or not self._sock:
                if attempt == 0:
                    self._try_reconnect()
                if not self._connected or not self._sock:
                    return None

            try:
                with self._lock:
                    full_cmd = cmd + "!"
                    self._sock.sendall(full_cmd.encode("utf-8"))
                    response = self._recv_raw()
                parts = response.split("#")

                if len(parts) < 2:
                    return None

                if parts[0] != cmd.split("#")[0]:
                    return None

                if parts[1] != "OK":
                    cmd_type = cmd.split("#")[0] if "#" in cmd else cmd
                    error_detail = "#".join(parts[1:])[:200]
                    logger.error(f"[FreeMT4] EA 错误: {cmd_type} 返回 {error_detail}")
                    return None

                return parts[2:]

            except Exception:
                self.disconnect()
                # 继续下一轮循环尝试重连

        return None

    def _check_alive(self) -> bool:
        data = self._send_cmd("F000#0#")
        return data is not None

    def send_heartbeat(self) -> bool:
        return self._check_alive()

    # ======================== 账户信息 ========================

    def get_account_info(self) -> Optional[AccountInfo]:
        static = self._send_cmd("F001#0#")
        dynamic = self._send_cmd("F002#0#")

        if not static or not dynamic:
            return None

        login_str = static[1] if len(static) > 1 else "0"
        currency = static[2] if len(static) > 2 else "USD"
        leverage_str = static[4] if len(static) > 4 else "100"

        balance = float(dynamic[0]) if len(dynamic) > 0 else 0
        equity = float(dynamic[1]) if len(dynamic) > 1 else 0
        margin = float(dynamic[3]) if len(dynamic) > 3 else 0
        margin_free = float(dynamic[5]) if len(dynamic) > 5 else 0

        return AccountInfo(
            login=int(login_str),
            balance=balance,
            equity=equity,
            margin=margin,
            free_margin=margin_free,
            currency=currency,
            leverage=int(leverage_str),
        )

    # ======================== 行情数据 ========================

    def get_tick_price(self, symbol: str) -> tuple[float, float]:
        data = self._send_cmd(f"F020#1#{symbol}#")
        if not data:
            return (0.0, 0.0)
        bid = float(data[2]) if len(data) > 2 else 0
        ask = float(data[1]) if len(data) > 1 else 0
        return bid, ask

    def get_server_time(self, symbol: str = "XAUUSD") -> int:
        """获取 MT4 服务器当前的 Unix 时间戳（用于时区校准）"""
        data = self._send_cmd(f"F020#1#{symbol}#")
        if not data or len(data) < 1:
            return 0
        try:
            return int(data[0])
        except (ValueError, IndexError):
            return 0

    def get_candles(self, symbol: str, timeframe: str, count: int, offset: int = 0) -> list[Candle]:
        tf = TF_MAP.get(timeframe, TF_MAP["H1"])
        data = self._send_cmd(f"F042#4#{symbol}#{tf}#{offset}#{count}#")
        if not data:
            return []

        candles = []
        for item in data:
            if not item:
                continue
            fields = item.split("$")
            if len(fields) >= 6:
                candles.append(Candle(
                    time=str(fields[0]),
                    open=float(fields[1]),
                    high=float(fields[2]),
                    low=float(fields[3]),
                    close=float(fields[4]),
                    volume=float(fields[5]),
                ))
        return candles

    # ======================== 持仓管理 ========================

    def get_positions(self, symbol: str = None) -> list[Position]:
        data = self._send_cmd("F061#0#")
        if not data:
            return []

        all_fields = "$".join(data).split("$")
        FIELDS_PER_POS = 13

        positions = []
        for i in range(0, len(all_fields) - FIELDS_PER_POS + 1, FIELDS_PER_POS):
            chunk = all_fields[i:i + FIELDS_PER_POS]
            if not chunk[0] or not chunk[0].isdigit():
                continue

            pos_symbol = chunk[1]
            if symbol and pos_symbol != symbol:
                continue

            positions.append(Position(
                ticket=int(chunk[0]),
                symbol=pos_symbol,
                order_type=chunk[2],
                volume=float(chunk[4]),
                open_price=float(chunk[5]),
                current_price=0,
                stop_loss=float(chunk[7]),
                take_profit=float(chunk[8]),
                profit=float(chunk[10]),
                swap=float(chunk[11]),
                commission=float(chunk[12]),
                magic=int(chunk[3]),
                comment=chunk[9],
                open_time=str(chunk[6]),
            ))
        return positions

    def get_order_history(self, symbol: str = None) -> list[dict]:
        """获取 MT4 历史成交记录（需要 EA 支持 F062 指令）"""
        data = self._send_cmd("F062#0#")
        if not data:
            return []

        all_fields = "$".join(data).split("$")
        FIELDS_PER_ORDER = 15

        orders = []
        for i in range(0, len(all_fields) - FIELDS_PER_ORDER + 1, FIELDS_PER_ORDER):
            chunk = all_fields[i:i + FIELDS_PER_ORDER]
            if not chunk[0] or not chunk[0].isdigit():
                continue
            if symbol and chunk[1] != symbol:
                continue
            orders.append({
                "ticket": int(chunk[0]),
                "symbol": chunk[1],
                "order_type": chunk[2],
                "magic": int(chunk[3]),
                "volume": float(chunk[4]),
                "open_price": float(chunk[5]),
                "open_time": int(chunk[6]),
                "close_price": float(chunk[7]),
                "close_time": int(chunk[8]),
                "profit": float(chunk[9]),
                "swap": float(chunk[10]),
                "commission": float(chunk[11]),
                "stop_loss": float(chunk[12]),
                "take_profit": float(chunk[13]),
                "comment": chunk[14],
            })
        return orders

    # ======================== 下单/平仓 ========================

    def open_order(self, symbol: str, order_type: OrderType, volume: float,
                   price: float = 0, sl: float = 0, tp: float = 0,
                   comment: str = "", magic: int = 0) -> Optional[int]:
        if magic == 0:
            magic = MAGIC_NUMBER
        # 防御: None → 0，防止 f-string 格式化为 "None" 导致 EA 无法解析
        sl = sl if sl is not None else 0
        tp = tp if tp is not None else 0
        type_str = order_type.value.lower()

        data = self._send_cmd(
            f"F070#8#{symbol}#{type_str}#{volume}#{price}#{SLIPPAGE}#{magic}#{sl}#{tp}#{comment}#"
        )
        if not data:
            logger.error(f"[FreeMT4] 开仓失败: {symbol} {order_type.value} magic={magic} _send_cmd 返回空")
            return None

        try:
            ticket = int(data[0])
            logger.info(f"[FreeMT4] 开仓成功: {order_type.value} {symbol} {volume}手 Ticket={ticket}")
            return ticket
        except (ValueError, IndexError):
            logger.error(f"[FreeMT4] 开仓响应解析失败: {data}")
            return None

    def close_order(self, ticket: int, volume: float = 0) -> bool:
        if volume > 0:
            cmd = f"F072#2#{ticket}#{volume}#"
        else:
            cmd = f"F071#1#{ticket}#"

        data = self._send_cmd(cmd)
        if data:
            logger.info(f"[FreeMT4] 平仓成功: Ticket={ticket}")
            return True
        logger.error(f"[FreeMT4] 平仓失败: Ticket={ticket}")
        return False

    def modify_order(self, ticket: int, sl: float = 0, tp: float = 0) -> bool:
        data = self._send_cmd(f"F075#3#{ticket}#{sl}#{tp}#")
        if data:
            logger.info(f"[FreeMT4] 修改成功: Ticket={ticket} SL={sl} TP={tp}")
            return True
        logger.error(f"[FreeMT4] 修改失败: Ticket={ticket}")
        return False
