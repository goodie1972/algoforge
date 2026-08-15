"""Stoch 超卖/超买阈值对比 — 复用 h1_all_strategies.py 引擎"""
import sys
sys.path.insert(0, ".")

from datetime import datetime
from core.bridge import create_bridge
from backtest.h1_all_strategies import (
    VariantConfig, run_variant, OrderType,
)

bridge = create_bridge()
if not bridge.connect():
    print("MT4 连接失败!")
    sys.exit(1)

raw = bridge.get_candles("XAUUSD", "H1", 4000)
candles = list(reversed(raw))
bridge.disconnect()

start = datetime.fromtimestamp(int(candles[0].time))
end = datetime.fromtimestamp(int(candles[-1].time))
print(f"数据: {len(candles)} 根 H1 K线  {start} ~ {end}\n")

variants = [
    VariantConfig("Stoch_20x80(当前)", "stoch_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"stoch_oversold": 20, "stoch_overbought": 80}),
    VariantConfig("Stoch_25x80", "stoch_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"stoch_oversold": 25, "stoch_overbought": 80}),
    VariantConfig("Stoch_30x80", "stoch_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"stoch_oversold": 30, "stoch_overbought": 80}),
    VariantConfig("Stoch_25x75", "stoch_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"stoch_oversold": 25, "stoch_overbought": 75}),
    VariantConfig("Stoch_30x70", "stoch_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"stoch_oversold": 30, "stoch_overbought": 70}),
]

print(f"{'变体':<22} {'交易':>5} {'盈亏':>10} {'胜率':>7} {'多(胜率)':>12} {'空(胜率)':>12} {'均盈':>7} {'均亏':>7}")
print("-" * 85)

for v in variants:
    result = run_variant(candles, v)
    long_info = f"{result['long_trades']}({result['long_wr']}%)"
    short_info = f"{result['short_trades']}({result['short_wr']}%)"
    print(f"{v.label:<22} {result['trades']:>5} ${result['pnl']:>9.0f} {result['win_rate']:>6.1f}% "
          f"{long_info:>12} {short_info:>12} ${result['avg_win']:>6.0f} ${abs(result['avg_loss']):>6.0f}")
