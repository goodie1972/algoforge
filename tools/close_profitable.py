"""
平掉所有盈利的自动单
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import MAGIC_NUMBER
from core.bridge import create_bridge, OrderType

bridge = create_bridge()
if not bridge.connect():
    print("MT4 连接失败!")
    sys.exit(1)

info = bridge.get_account_info()
print(f"账户: #{info.login} 余额=${info.balance:.2f} 净值=${info.equity:.2f}")

positions = bridge.get_positions("XAUUSD")
my_positions = [p for p in positions if p.magic == MAGIC_NUMBER]

print(f"\n自动持仓: {len(my_positions)} 张")
closed = 0
for pos in my_positions:
    direction = "BUY" if "BUY" in pos.order_type else "SELL"
    print(f"  Ticket={pos.ticket} {direction} @ {pos.open_price} 盈亏=${pos.profit:.2f} SL={pos.stop_loss} TP={pos.take_profit}")
    if pos.profit > 0:
        print(f"    -> 盈利中，平仓!")
        ok = bridge.close_order(pos.ticket)
        print(f"    {'成功' if ok else '失败'}")
        if ok:
            closed += 1

if closed == 0:
    print("\n没有盈利的单")

bridge.disconnect()
