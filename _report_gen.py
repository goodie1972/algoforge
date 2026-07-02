from datetime import datetime, timedelta
uptime_sec = 36652.62
uptime_h = uptime_sec / 3600
uptime_str = f'{uptime_h:.1f}h' if uptime_h >= 1 else f'{int(uptime_sec/60)}min'

trades = [
    ('2026-06-13 03:24:04', 'sanqing_h1', 'BUY', 7.27),
    ('2026-06-13 02:33:05', 'sanqing_h1', 'BUY', 12.11),
    ('2026-06-13 01:49:54', 'H1_v6_hybrid', 'SELL', 10.84),
]

print(f"**引擎**: GREEN | 桥接: 已连接 | 运行时间: {uptime_str}")
print()
print("### 账户")
print("| 指标 | 数值 |")
print("|------|------|")
print("| 余额 | **$871.53** |")
print("| 净值 | **$806.94** |")
print("| 浮动盈亏 | **-$64.79** |")
print("| 保证金占用 | $83.70 (可用 $723.24) |")
print()
print("### 持仓 (2 张)")
print("| 策略 | 方向 | 手数 | 浮盈/亏 |")
print("|------|------|------|---------|")
print("| H1_v6_hybrid | SELL | 0.01 | -$33.22 |")
print("| M30_rsi_bb | SELL | 0.01 | -$30.75 |")
print()
print("### 策略信号")
print("| 策略 | 周期 | 多头 | 空头 | 信号 |")
print("|------|------|------|------|------|")
print("| M30_rsi_bb | M30 | 1 | 3 | SELL |")
print("| H1_v6_hybrid | H1 | 1 | 3 | SELL |")
print("| sanqing_h1 | H1 | 4 | 0 | 等待 |")
print("| gold_auto_research | H1 | 3 | 2 | 等待 |")
print()
print("### 最近成交 (3笔)")
print("| 时间(本地) | 策略 | 方向 | 盈亏 |")
print("|------|------|------|------|")
for t, name, d, pnl in trades:
    local_time = (datetime.strptime(t, '%Y-%m-%d %H:%M:%S') + timedelta(hours=5)).strftime('%H:%M')
    print(f"| {local_time} | {name} | {d} | +${pnl:.2f} |")
print()
print("### 风控")
print("- 当日盈亏: +$32.39 | 阻断: 无")
print("- 数据库: 8338 根 K 线 (H1, M15, M30)")
