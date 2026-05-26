"""
MT4 导出 K线数据到 CSV
需要 MT4 终端运行中 + PyTrader 已连接
用法: python tools/export_history.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from core.bridge import create_bridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def export_history(symbol: str = "XAUUSD", timeframe: str = "H1", count: int = 10000,
                   output_path: str = None):
    """从 MT4 导出历史K线数据"""
    if output_path is None:
        output_path = os.path.join("data", f"{symbol}_{timeframe}.csv")

    bridge = create_bridge()
    if not bridge.connect():
        logger.error("无法连接 MT4")
        return

    logger.info(f"正在获取 {symbol} {timeframe} {count} 条K线...")
    candles = bridge.get_candles(symbol, timeframe, count)
    logger.info(f"获取到 {len(candles)} 条K线")

    if not candles:
        logger.error("未获取到数据")
        bridge.disconnect()
        return

    # 写入 CSV
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("time,open,high,low,close,volume\n")
        for c in candles:
            f.write(f"{c.time},{c.open},{c.high},{c.low},{c.close},{c.volume}\n")

    logger.info(f"数据已导出: {output_path}")
    bridge.disconnect()


if __name__ == "__main__":
    export_history()
