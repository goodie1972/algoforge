"""
分析历史 K-D 差值分布
统计过去半年 XAUUSD M30 数据中 K-D 和 D-K 的差值分布
"""
import sys
import os
import math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import STOCH_K, STOCH_D
from core.bridge import create_bridge

bridge = create_bridge()
if not bridge.connect():
    print("MT4 连接失败!")
    sys.exit(1)

# 获取足够多的数据（半年 ≈ 8640 根 M30）
TIMEFRAME = "M30"
CANDLES_NEEDED = 10000
# Stoch 需要至少 K + D 根才能开始算
STOCH_K_VAL = 14
STOCH_D_VAL = 3
MIN_CANDLES = STOCH_K_VAL + STOCH_D_VAL + 2

print(f"正在获取 {TIMEFRAME} 历史数据（{CANDLES_NEEDED} 根）...")
candles = bridge.get_candles("XAUUSD", TIMEFRAME, CANDLES_NEEDED)
print(f"获取到 {len(candles)} 根 K 线")

if len(candles) < MIN_CANDLES:
    print(f"数据不足（需要至少 {MIN_CANDLES} 根）")
    sys.exit(1)

closes = [float(c.close) for c in candles]
highs = [float(c.high) for c in candles]
lows = [float(c.low) for c in candles]
n = len(candles)

# 计算所有 %K 值
k_values = []
for i in range(STOCH_K_VAL - 1, n):
    window_high = max(highs[i - STOCH_K_VAL + 1 : i + 1])
    window_low = min(lows[i - STOCH_K_VAL + 1 : i + 1])
    close = closes[i]
    if window_high == window_low:
        k_values.append(50.0)
    else:
        k_values.append((close - window_low) / (window_high - window_low) * 100)

# 计算所有 %D 值（D = SMA of K）
d_values = []
for i in range(STOCH_D_VAL - 1, len(k_values)):
    d_values.append(sum(k_values[i - STOCH_D_VAL + 1 : i + 1]) / STOCH_D_VAL)

# K_values 和 d_values 对齐
# K 数组起始位置比 closes 晚了 STOCH_K_VAL - 1
# D 数组起始位置比 K 数组晚了 STOCH_D_VAL - 1
# 所以第一个有效 D 位置在 closes 中的索引: (STOCH_K_VAL - 1) + (STOCH_D_VAL - 1)
start_offset = (STOCH_K_VAL - 1) + (STOCH_D_VAL - 1)

# 对齐 k 和 d 数组
k_aligned = k_values[STOCH_D_VAL - 1:]  # 去掉前几个 K 值（还没出 D）
assert len(k_aligned) == len(d_values), f"K({len(k_aligned)}) != D({len(d_values)})"

kd_diff = [k_aligned[i] - d_values[i] for i in range(len(d_values))]

# 分离 K>D 和 D>K
k_gt_d = [d for d in kd_diff if d > 0]
d_gt_k = [d for d in kd_diff if d < 0]

# 时间范围
days_of_data = len(d_values) / 48  # M30 大约 48 根/天
print(f"\n有效 Stoch 数据窗口: {len(d_values)} 根 K 线（约 {days_of_data:.0f} 天）")

print(f"\n{'='*55}")
print("K-D 差值分布分析")
print(f"{'='*55}")

print(f"\n【K > D 多头情况】")
print(f"  {'样本数:':<12} {len(k_gt_d):>8} ({len(k_gt_d)/len(d_values)*100:.1f}% 的时间)")
if k_gt_d:
    k_gt_d.sort()
    print(f"  {'平均值:':<12} {sum(k_gt_d)/len(k_gt_d):>8.2f}")
    print(f"  {'标准差:':<12} {math.sqrt(sum((x - sum(k_gt_d)/len(k_gt_d))**2 for x in k_gt_d) / len(k_gt_d)):>8.2f}")
    print(f"  {'最小值:':<12} {k_gt_d[0]:>8.2f}")
    print(f"  {'最大值:':<12} {k_gt_d[-1]:>8.2f}")
    print(f"  分位数:")
    for pct in [10, 25, 50, 75, 90, 95, 99]:
        idx = int(len(k_gt_d) * pct / 100)
        print(f"    {pct:>2}%: {k_gt_d[idx]:>8.2f}")

print(f"\n【D > K 空头情况】")
d_gt_k_abs = [abs(d) for d in d_gt_k]
if d_gt_k_abs:
    d_gt_k_abs.sort()
    print(f"  {'样本数:':<12} {len(d_gt_k_abs):>8} ({len(d_gt_k)/len(d_values)*100:.1f}% 的时间)")
    print(f"  {'平均值:':<12} {sum(d_gt_k_abs)/len(d_gt_k_abs):>8.2f}")
    print(f"  {'标准差:':<12} {math.sqrt(sum((x - sum(d_gt_k_abs)/len(d_gt_k_abs))**2 for x in d_gt_k_abs) / len(d_gt_k_abs)):>8.2f}")
    print(f"  {'最小值:':<12} {d_gt_k_abs[0]:>8.2f}")
    print(f"  {'最大值:':<12} {d_gt_k_abs[-1]:>8.2f}")
    print(f"  分位数:")
    for pct in [10, 25, 50, 75, 90, 95, 99]:
        idx = int(len(d_gt_k_abs) * pct / 100)
        print(f"    {pct:>2}%: {d_gt_k_abs[idx]:>8.2f}")

print(f"\n【全部差值直方图】")
hist_bins = [(i * 5, (i + 1) * 5) for i in range(0, 10)]  # 0-5, 5-10, ..., 40-45, 45+
for lo, hi in hist_bins:
    count_gt = sum(1 for d in kd_diff if lo <= d < hi)
    count_lt = sum(1 for d in kd_diff if -hi < d <= -lo)
    bar_gt = "█" * int(count_gt / max(len(kd_diff) / 80, 1))
    bar_lt = "█" * int(count_lt / max(len(kd_diff) / 80, 1))
    print(f"  {lo:>2}-{hi:<2}: +{bar_gt:<40} {count_gt:>5}  |  -{bar_lt:<40} {count_lt:>5}")

bridge.disconnect()
