"""
修改现有持仓 TP 为极远值（新 K-D 衰减出场逻辑需要）
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

# 获取带宽
candles = bridge.get_candles("XAUUSD", "M30", 100)
closes = [float(c.close) for c in candles]
sma = sum(closes[-BB_PERIOD:]) / BB_PERIOD
variance = sum((c - sma) ** 2 for c in closes[-BB_PERIOD:]) / BB_PERIOD
std = math.sqrt(variance)
bandwidth = std * BB_STD

target_tickets = [89420780, 89420782, 89420784]
positions = bridge.get_positions("XAUUSD")

for pos in positions:
    if pos.ticket not in target_tickets:
        continue
    is_buy = "BUY" in pos.order_type
    new_tp = round(pos.open_price + bandwidth * 100, 2) if is_buy else round(pos.open_price - bandwidth * 100, 2)
    print(f"Ticket={pos.ticket}: TP {pos.take_profit} → {new_tp}")
    ok = bridge.modify_order(pos.ticket, sl=pos.stop_loss, tp=new_tp)
    print(f"  {'成功' if ok else '失败'}")

bridge.disconnect()
