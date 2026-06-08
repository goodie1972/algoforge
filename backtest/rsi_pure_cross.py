"""RSI 纯双线交叉（无布林带）回测"""
import sys
sys.path.insert(0, ".")

from datetime import datetime
from backtest.h1_all_strategies import (
    VariantConfig, run_variant, calc_rsi, OrderType,
)

# 手动导入引擎核心逻辑
from core.bridge import create_bridge

# 信号函数：纯 RSI 双线交叉
def signal_rsi_pure_cross(candles, i, state):
    rsi_fast = state.get("rsi_fast", 3)
    rsi_slow = state.get("rsi_slow", 13)

    if i < rsi_slow + 5:
        return None

    curr_fast = calc_rsi(candles[:i+1], rsi_fast)
    curr_slow = calc_rsi(candles[:i+1], rsi_slow)
    if curr_fast is None or curr_slow is None:
        return None

    prev_fast = state.get("_prev_fast")
    prev_slow = state.get("_prev_slow")
    state["_prev_fast"] = curr_fast
    state["_prev_slow"] = curr_slow

    if prev_fast is None or prev_slow is None:
        return None

    golden = prev_fast <= prev_slow and curr_fast > curr_slow
    death = prev_fast >= prev_slow and curr_fast < curr_slow

    if golden:
        return ("BUY", OrderType.BUY)
    if death:
        return ("SELL", OrderType.SELL)
    return None


# 信号函数：RSI 交叉 + 区域过滤（金叉在低位、死叉在高位）
def signal_rsi_zone_cross(candles, i, state):
    rsi_fast = state.get("rsi_fast", 3)
    rsi_slow = state.get("rsi_slow", 13)
    buy_zone = state.get("buy_zone", 50)
    sell_zone = state.get("sell_zone", 50)

    if i < rsi_slow + 5:
        return None

    curr_fast = calc_rsi(candles[:i+1], rsi_fast)
    curr_slow = calc_rsi(candles[:i+1], rsi_slow)
    if curr_fast is None or curr_slow is None:
        return None

    prev_fast = state.get("_prev_fast")
    prev_slow = state.get("_prev_slow")
    state["_prev_fast"] = curr_fast
    state["_prev_slow"] = curr_slow

    if prev_fast is None or prev_slow is None:
        return None

    golden = prev_fast <= prev_slow and curr_fast > curr_slow
    death = prev_fast >= prev_slow and curr_fast < curr_slow

    if golden and curr_fast < buy_zone:
        return ("BUY", OrderType.BUY)
    if death and curr_fast > sell_zone:
        return ("SELL", OrderType.SELL)
    return None


# 注册到临时 registry
SIGNAL_REGISTRY_TEMP = {
    "rsi_pure_cross": signal_rsi_pure_cross,
    "rsi_zone_cross": signal_rsi_zone_cross,
}

# 复用引擎的 run_variant，但替换 signal registry
# 直接复制 run_variant 逻辑太复杂，改一下导入
import backtest.h1_all_strategies as bt
orig_registry = bt.SIGNAL_REGISTRY.copy()
bt.SIGNAL_REGISTRY.update(SIGNAL_REGISTRY_TEMP)


def quick_run(candles, config):
    return bt.run_variant(candles, config)


bridge = create_bridge()
if not bridge.connect():
    print("MT4 连接失败!")
    sys.exit(1)

raw = bridge.get_candles("XAUUSD", "H1", 4000)
candles = list(reversed(raw))
bridge.disconnect()

start = datetime.fromtimestamp(int(candles[0].time))
end = datetime.fromtimestamp(int(candles[-1].time))
print(f"数据: {len(candles)} 根 H1  {start} ~ {end}\n")

variants = [
    VariantConfig("纯交叉_3x13", "rsi_pure_cross", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"rsi_fast": 3, "rsi_slow": 13}),
    VariantConfig("纯交叉_3x21", "rsi_pure_cross", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"rsi_fast": 3, "rsi_slow": 21}),
    VariantConfig("纯交叉_5x13", "rsi_pure_cross", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"rsi_fast": 5, "rsi_slow": 13}),
    VariantConfig("纯交叉_5x21", "rsi_pure_cross", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"rsi_fast": 5, "rsi_slow": 21}),
    VariantConfig("区域交叉_3x13_下50上50", "rsi_zone_cross", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"rsi_fast": 3, "rsi_slow": 13, "buy_zone": 50, "sell_zone": 50}),
    VariantConfig("区域交叉_3x13_下40上60", "rsi_zone_cross", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"rsi_fast": 3, "rsi_slow": 13, "buy_zone": 40, "sell_zone": 60}),
    # 基线对比
    VariantConfig("RSI单线_30x70(基线)", "rsi_bollinger", exit_mode="ma_trail", sl_mode="bb_035",
                  signal_params={"rsi_oversold": 30, "rsi_overbought": 70}),
]

print(f"{'变体':<28} {'交易':>5} {'盈亏':>10} {'胜率':>7} {'多(胜率)':>12} {'空(胜率)':>12} {'均盈':>7} {'均亏':>7}")
print("-" * 95)

for v in variants:
    result = bt.run_variant(candles, v)
    long_info = f"{result['long_trades']}({result['long_wr']}%)"
    short_info = f"{result['short_trades']}({result['short_wr']}%)"
    print(f"{v.label:<28} {result['trades']:>5} ${result['pnl']:>9.0f} {result['win_rate']:>6.1f}% "
          f"{long_info:>12} {short_info:>12} ${result['avg_win']:>6.0f} ${abs(result['avg_loss']):>6.0f}")

# 恢复
bt.SIGNAL_REGISTRY = orig_registry
