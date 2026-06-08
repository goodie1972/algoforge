"""RSI 单线 vs 双线交叉 对比回测 — 复用 h1_all_strategies.py 引擎"""
import sys
sys.path.insert(0, ".")

from datetime import datetime
from core.bridge import create_bridge
from backtest.h1_all_strategies import (
    VariantConfig, run_variant, calc_ema,
    OrderType, BB_PERIOD, BB_STD, ATR_PERIOD,
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
print(f"H1: {len(candles)} 根  {start} ~ {end}\n")

variants = [
    VariantConfig("RSI单线_30x70", "rsi_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"rsi_oversold": 30, "rsi_overbought": 70}),
    VariantConfig("RSI单线_35x65", "rsi_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"rsi_oversold": 35, "rsi_overbought": 65}),
    VariantConfig("RSI交叉_3x13", "rsi_cross_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"rsi_fast": 3, "rsi_slow": 13}),
    VariantConfig("RSI交叉_3x21", "rsi_cross_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"rsi_fast": 3, "rsi_slow": 21}),
    VariantConfig("RSI交叉_5x13", "rsi_cross_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"rsi_fast": 5, "rsi_slow": 13}),
]

print(f"{'变体':<20} {'交易':>5} {'盈亏':>10} {'胜率':>7} {'均盈':>7} {'均亏':>7}")
print("-" * 60)

for v in variants:
    result = run_variant(candles, v)
    win_rate = result["win_rate"]
    avg_win = result["avg_win"]
    avg_loss = abs(result["avg_loss"])
    print(f"{v.label:<20} {result['trades']:>5} ${result['pnl']:>9.0f} {win_rate:>6.1f}% ${avg_win:>6.0f} ${avg_loss:>6.0f}")
