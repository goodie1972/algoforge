"""
PyTrader 桥接实现 - 通过 Socket 与 MT4 中的 PyTrader EA 通信
协议: PyTrader V1.02 (自定义 # 分隔格式，非 JSON)
文档参考: Pytrader_API.py (EA 自带的官方 Python SDK)
"""

import socket
import logging
from typing import Optional
from datetime import datetime

from config.settings import PYTRADER_HOST, PYTRADER_PORT, MAGIC_NUMBER, SYMBOL, LOT_SIZE, SLIPPAGE
from core.bridge import (
    MT4BridgeBase, Position, Candle, AccountInfo, OrderType
)

logger = logging.getLogger(__name__)

# MQL4 timeframe 值 (分钟数格式)
TF_MAP = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440, "W1": 10080, "MN1": 43200,
}


class PyTraderBridge(MT4BridgeBase):
    """通过 PyTrader EA V1.02 连接 MT4 - 使用官方 # 分隔协议"""

    def __init__(self):
        self._sock: Optional[socket.socket] = None
        self._connected = False
        # 品种映射 (EA 要求连接时发送)
        self._instrument_map = {"XAUUSD": "XAUUSD", "GOLD": "XAUUSD"}

    def connect(self) -> bool:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(10)
            self._sock.connect((PYTRADER_HOST, PYTRADER_PORT))
            self._connected = True

            # 新 EA 不发问候语，直接用心跳验证
            logger.info(f"[PyTrader] 已连接到 {PYTRADER_HOST}:{PYTRADER_PORT}")

            # 测试连接
            if not self._check_alive():
                logger.error("[PyTrader] 心跳测试失败")
                self.disconnect()
                return False

            info = self.get_account_info()
            if info:
                logger.info(f"[PyTrader] 账户 #{info.login} 余额: {info.balance} {info.currency}")
            return True
        except Exception as e:
            logger.error(f"[PyTrader] 连接失败: {e}")
            self._connected = False
            return False

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._connected = False
            logger.info("[PyTrader] 已断开连接")

    # ======================== 底层通信 ========================

    def _recv_raw(self) -> str:
        """接收直到遇到 ! 终止符"""
        data = b""
        while True:
            chunk = self._sock.recv(500000)
            if not chunk:
                raise ConnectionError("连接已关闭")
            data += chunk
            text = data.decode("utf-8")
            if text.endswith("!"):
                # 去掉结尾的 !
                return text[:-1]

    def _send_cmd(self, cmd: str, _retry: bool = True) -> Optional[list]:
        """
        发送命令并解析响应
        格式: 发送 F001#0#!  -> 接收 F001#OK#data1#data2#!
        返回: ['#' 分隔的字段列表，不含 F-code 和 OK/ERROR 头]
        """
        if not self._connected or not self._sock:
            logger.warning("[PyTrader] 连接已断开，尝试重连...")
            if _retry and self.connect():
                return self._send_cmd(cmd, _retry=False)
            return None
        try:
            full_cmd = cmd + "!"
            self._sock.sendall(full_cmd.encode("utf-8"))
            response = self._recv_raw()
            parts = response.split("#")

            # 验证响应头
            if len(parts) < 2:
                logger.error(f"[PyTrader] 响应格式错误: {response}")
                return None

            if parts[0] != cmd.split("#")[0]:
                logger.error(f"[PyTrader] 响应码不匹配: 期望 {cmd.split('#')[0]}, 收到 {parts[0]}")
                return None

            if parts[1] != "OK":
                error_msg = parts[2] if len(parts) > 2 else "未知错误"
                logger.error(f"[PyTrader] 命令失败 {cmd.split('#')[0]}: {error_msg}")
                return None

            # 返回 data 部分 (去掉 F-code 和 OK/ERROR)
            return parts[2:]

        except socket.timeout:
            logger.error(f"[PyTrader] 超时: {cmd.split('#')[0]}")
            self._connected = False
            if _retry:
                logger.warning("[PyTrader] 超时后尝试重连...")
                if self.connect():
                    return self._send_cmd(cmd, _retry=False)
            return None
        except Exception as e:
            logger.error(f"[PyTrader] 通信错误: {e}")
            self._connected = False
            if _retry:
                logger.warning("[PyTrader] 断线重连中...")
                if self.connect():
                    return self._send_cmd(cmd, _retry=False)
            return None

    def _check_alive(self) -> bool:
        """心跳检测 F000#0#"""
        data = self._send_cmd("F000#0#")
        return data is not None

    def send_heartbeat(self) -> bool:
        """公开心跳方法，用于主循环保活"""
        return self._check_alive()

    # ======================== 账户信息 ========================

    def get_account_info(self) -> Optional[AccountInfo]:
        # F001 - 静态信息
        static = self._send_cmd("F001#0#")
        # F002 - 动态信息
        dynamic = self._send_cmd("F002#0#")

        if not static or not dynamic:
            return None

        # 静态: name, login, currency, type, leverage, trade_allowed, limit_orders, margin_call, margin_close
        login_str = static[1] if len(static) > 1 else "0"
        currency = static[2] if len(static) > 2 else "USD"
        leverage_str = static[4] if len(static) > 4 else "100"

        # 动态: balance, equity, profit, margin, margin_level, margin_free
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
        """F020 - 获取最新 tick"""
        data = self._send_cmd(f"F020#1#{symbol}#")
        if not data:
            return (0.0, 0.0)
        # 返回: date, ask, bid, last, volume
        bid = float(data[2]) if len(data) > 2 else 0
        ask = float(data[1]) if len(data) > 1 else 0
        return bid, ask

    def get_candles(self, symbol: str, timeframe: str, count: int) -> list[Candle]:
        """F042 - 获取历史K线"""
        tf = TF_MAP.get(timeframe, TF_MAP["H1"])
        data = self._send_cmd(f"F042#4#{symbol}#{tf}#0#{count}#")
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
        """F061 - 获取所有持仓，每 13 个 $ 分隔字段为一组"""
        data = self._send_cmd("F061#0#")
        if not data:
            return []

        # 合并所有 data 项，按 $ 分割，每 13 个字段一组
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

    # ======================== 下单/平仓 ========================

    def open_order(self, symbol: str, order_type: OrderType, volume: float,
                   price: float = 0, sl: float = 0, tp: float = 0,
                   comment: str = "", magic: int = 0) -> Optional[int]:
        """F070 - 开仓"""
        if magic == 0:
            magic = MAGIC_NUMBER
        type_str = order_type.value.lower()  # "buy" or "sell"

        data = self._send_cmd(
            f"F070#8#{symbol}#{type_str}#{volume}#{price}#{SLIPPAGE}#{magic}#{sl}#{tp}#{comment}#"
        )
        if not data:
            return None

        # 返回: ticket, "ORDER_OPEN"
        try:
            ticket = int(data[0])
            logger.info(f"[PyTrader] 开仓成功: {order_type.value} {symbol} {volume}手 Ticket={ticket}")
            return ticket
        except (ValueError, IndexError):
            logger.error(f"[PyTrader] 开仓响应解析失败: {data}")
            return None

    def close_order(self, ticket: int, volume: float = 0) -> bool:
        """F071 - 全平, F072 - 部分平仓"""
        if volume > 0:
            cmd = f"F072#2#{ticket}#{volume}#"
        else:
            cmd = f"F071#1#{ticket}#"

        data = self._send_cmd(cmd)
        if data:
            logger.info(f"[PyTrader] 平仓成功: Ticket={ticket}")
            return True
        logger.error(f"[PyTrader] 平仓失败: Ticket={ticket}")
        return False

    def modify_order(self, ticket: int, sl: float = 0, tp: float = 0) -> bool:
        """F075 - 修改止损止盈"""
        data = self._send_cmd(f"F075#3#{ticket}#{sl}#{tp}#")
        if data:
            logger.info(f"[PyTrader] 修改成功: Ticket={ticket} SL={sl} TP={tp}")
            return True
        logger.error(f"[PyTrader] 修改失败: Ticket={ticket}")
        return False
