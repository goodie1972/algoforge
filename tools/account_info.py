"""
账户信息查看器 - 快速查看账户状态和现有持仓
用法: python tools/account_info.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from core.bridge import create_bridge

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def show_account_info():
    bridge = create_bridge()
    if not bridge.connect():
        print("连接 MT4 失败")
        return

    # 账户信息
    info = bridge.get_account_info()
    if info:
        print("=" * 50)
        print("账户信息")
        print("=" * 50)
        print(f"  登录号:     {info.login}")
        print(f"  余额:       {info.balance:,.2f} {info.currency}")
        print(f"  净值:       {info.equity:,.2f} {info.currency}")
        print(f"  已用保证金: {info.margin:,.2f} {info.currency}")
        print(f"  可用保证金: {info.free_margin:,.2f} {info.currency}")
        print(f"  杠杆:       1:{info.leverage}")
        print("=" * 50)

    # 现有持仓
    positions = bridge.get_positions()
    if positions:
        print(f"\n当前持仓 ({len(positions)} 个):")
        print("-" * 90)
        print(f"{'Ticket':<10} {'品种':<10} {'方向':<8} {'手数':<6} {'开仓价':<10} "
              f"{'现价':<10} {'SL':<10} {'TP':<10} {'盈亏':<10}")
        print("-" * 90)
        for p in positions:
            print(f"{p.ticket:<10} {p.symbol:<10} {p.order_type:<8} {p.volume:<6} "
                  f"{p.open_price:<10.2f} {p.current_price:<10.2f} "
                  f"{p.stop_loss:<10.2f} {p.take_profit:<10.2f} {p.profit:<+10.2f}")
        print("-" * 90)
        total_pnl = sum(p.profit for p in positions)
        print(f"总盈亏: {total_pnl:+.2f} {info.currency if info else ''}")
    else:
        print("\n当前无持仓")

    bridge.disconnect()


if __name__ == "__main__":
    show_account_info()
