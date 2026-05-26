"""
实时监控仪表板 - 在终端显示当前行情和策略信号
用法: python tools/monitor.py
按 Ctrl+C 退出
"""

import logging
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from core.bridge import create_bridge, OrderType
from strategies.double_ma import DoubleMAStrategy
from strategies.atr_breakout import ATRBreakoutStrategy

logging.basicConfig(level=logging.INFO, format="%(message)s")


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def run_monitor(interval: int = 30):
    """运行监控仪表板"""
    bridge = create_bridge()
    if not bridge.connect():
        print("连接 MT4 失败，退出")
        return

    strategies = [
        DoubleMAStrategy(bridge),
        ATRBreakoutStrategy(bridge),
    ]

    try:
        while True:
            clear_screen()
            print("=" * 70)
            print(f"  XAUUSD 实时监控  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 70)

            # 账户信息
            info = bridge.get_account_info()
            if info:
                print(f"\n  账户 #{info.login} | 余额: ${info.balance:,.2f} | "
                      f"净值: ${info.equity:,.2f} | "
                      f"可用: ${info.free_margin:,.2f} | 杠杆: 1:{info.leverage}")

                # 浮动盈亏
                floating = info.equity - info.balance
                color = "+" if floating >= 0 else ""
                print(f"  浮动盈亏: {color}${floating:,.2f}")

            # 当前价格
            bid, ask = bridge.get_tick_price(settings.SYMBOL)
            spread = ask - bid
            print(f"\n  {settings.SYMBOL}  Bid: {bid:.2f}  Ask: {ask:.2f}  "
                  f"Spread: {spread:.2f}")

            # 现有持仓
            positions = bridge.get_positions(settings.SYMBOL)
            if positions:
                print(f"\n  持仓 ({len(positions)}个):")
                print(f"  {'Ticket':<10} {'方向':<8} {'手数':<6} {'开仓价':<10} "
                      f"{'现价':<10} {'SL':<10} {'TP':<10} {'盈亏':<10}")
                print(f"  {'-' * 80}")
                for p in positions:
                    print(f"  {p.ticket:<10} {p.order_type:<8} {p.volume:<6} "
                          f"{p.open_price:<10.2f} {p.current_price:<10.2f} "
                          f"{p.stop_loss:<10.2f} {p.take_profit:<10.2f} "
                          f"{p.profit:<+10.2f}")
            else:
                print(f"\n  当前无持仓")

            # 策略信号
            print(f"\n  策略信号:")
            for s in strategies:
                s.refresh_data(200)
                candles_count = len(s.candles)
                signal = s.generate_signal() if candles_count >= 10 else None
                status = "等待中"
                if signal == OrderType.BUY:
                    status = ">>> 做多信号 <<<"
                elif signal == OrderType.SELL:
                    status = ">>> 做空信号 <<<"
                print(f"    {s.name:<20} K线: {candles_count:>4}  |  {status}")

                # 显示均线信息
                if hasattr(s, '_calc_ma'):
                    fast = s._calc_ma(s.ma_fast_period)
                    slow = s._calc_ma(s.ma_slow_period)
                    if fast and slow:
                        print(f"      MA{s.ma_fast_period}={fast:.2f}  MA{s.ma_slow_period}={slow:.2f}")

                # 显示 ATR 信息
                if hasattr(s, '_calc_atr'):
                    atr = s._calc_atr()
                    if atr:
                        highest, lowest = s._get_channel()
                        print(f"      ATR={atr:.2f}  通道: [{lowest:.2f} - {highest:.2f}]")

            print(f"\n  刷新间隔: {interval}秒 | 按 Ctrl+C 退出")
            print("=" * 70)
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\n监控已停止")
    finally:
        bridge.disconnect()


if __name__ == "__main__":
    run_monitor()
