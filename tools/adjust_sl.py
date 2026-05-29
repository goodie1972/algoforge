"""
调整现有持仓止损到 0.35 带宽
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import math
from config.settings import BB_PERIOD, BB_STD
from core.bridge import create_bridge, OrderType

bridge = create_bridge()
if not bridge.connect():
    print("MT4 连接失败!")
    sys.exit(1)

info = bridge.get_account_info()
if info:
    print(f"账户: #{info.login} 余额: ${info.balance:.2f}")

# 获取 K 线计算带宽
candles = bridge.get_candles("XAUUSD", "M30", 100)
closes = [float(c.close) for c in candles]
sma = sum(closes[-BB_PERIOD:]) / BB_PERIOD
variance = sum((c - sma) ** 2 for c in closes[-BB_PERIOD:]) / BB_PERIOD
std = math.sqrt(variance)
bandwidth = std * BB_STD

print(f"SMA={sma:.2f} STD={std:.2f} 带宽={bandwidth:.2f}")

# 获取当前持仓
positions = bridge.get_positions("XAUUSD")
print(f"\n当前 {len(positions)} 个持仓:")

target_tickets = [89420780, 89420782, 89420784]
for pos in positions:
    if pos.ticket not in target_tickets:
        continue
    direction = "BUY" if "BUY" in pos.order_type else "SELL"
    new_sl = round(pos.open_price - bandwidth * 0.35, 2)
    print(f"  Ticket={pos.ticket} {direction} @ {pos.open_price}")
    print(f"    旧 SL={pos.stop_loss} 新 SL={new_sl}")

    ok = bridge.modify_order(pos.ticket, sl=new_sl, tp=pos.take_profit)
    if ok:
        print(f"    -> 修改成功!")
    else:
        print(f"    -> 修改失败!")

bridge.disconnect()
