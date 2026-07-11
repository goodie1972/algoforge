"""
纸面交易一周数据分析报告
"""
import csv, json
from collections import defaultdict, Counter
from datetime import datetime

CSV = "D:/backup/baobao/pythonprogram/xauusd/logs/paper_trades.csv"

rows = []
with open(CSV, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

print("=" * 70)
print("  XAUUSD 纸面交易一周分析报告")
print(f"  分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  总交易: {len(rows)} 笔")
print("=" * 70)

# 按策略汇总
strat = defaultdict(list)
for r in rows:
    strat[r["策略"]].append(r)

print(f"\n{'─'*70}")
print(f"  一、各策略总览")
print(f"{'─'*70}")

print(f"\n{'策略':<25} {'笔数':>6} {'胜率':>6} {'总收益':>10} {'均收益':>8} {'最大亏':>8} {'最大赚':>8} {'盈亏比':>6}")
print(f"{'─'*70}")

for sname in sorted(strat.keys(), key=lambda s: -len(strat[s])):
    ss = strat[sname]
    total = len(ss)
    profits = [float(r["收益"]) for r in ss if r["收益"]]
    if not profits: continue
    wins = sum(1 for p in profits if p > 0)
    losses = sum(1 for p in profits if p < 0)
    win_rate = wins / total * 100 if total > 0 else 0
    total_pnl = sum(profits)
    avg_pnl = total_pnl / total if total > 0 else 0
    max_loss = min(profits)
    max_win = max(profits)
    avg_win = sum(p for p in profits if p > 0) / max(wins, 1)
    avg_loss = abs(sum(p for p in profits if p < 0) / max(losses, 1))
    rr = avg_win / max(avg_loss, 0.01)
    print(f"{sname:<25} {total:>6} {win_rate:>5.1f}% {total_pnl:>+10.2f} {avg_pnl:>+8.2f} {max_loss:>8.2f} {max_win:>8.2f} {rr:>5.2f}")

# 整体
all_profits = [float(r["收益"]) for r in rows if r["收益"]]
all_wins = sum(1 for p in all_profits if p > 0)
all_losses = sum(1 for p in all_profits if p < 0)
all_total = sum(all_profits)
print(f"{'─'*70}")
avg_win_all = sum(p for p in all_profits if p>0)/max(all_wins,1)
avg_loss_all = abs(sum(p for p in all_profits if p<0)/max(all_losses,1))
print(f"{'合计':<25} {len(rows):>6} {all_wins/len(rows)*100:>5.1f}% {all_total:>+10.2f} {all_total/len(rows):>+8.2f} {min(all_profits):>8.2f} {max(all_profits):>8.2f} {avg_win_all/avg_loss_all:>5.2f}")

# 时段分析
print(f"\n{'─'*70}")
print(f"  二、时间段分析（从开始时间算起）")
print(f"{'─'*70}")

first_time = min(r["时间"] for r in rows)
last_time = max(r["时间"] for r in rows)
print(f"  数据范围: {first_time} ~ {last_time}")

# 按天分析
day_stats = defaultdict(list)
for r in rows:
    day = r["时间"][:10]
    day_stats[day].append(r)

for day in sorted(day_stats.keys()):
    ss = day_stats[day]
    profits = [float(r["收益"]) for r in ss if r["收益"]]
    if not profits: continue
    wins = sum(1 for p in profits if p > 0)
    print(f"  {day}: {len(ss):>4}笔 胜{wins:>3} 亏{len(ss)-wins:>3} 总{sum(profits):>+8.2f}")

# 方向分析
print(f"\n{'─'*70}")
print(f"  三、方向分析")
print(f"{'─'*70}")
for sname in sorted(strat.keys(), key=lambda s: -len(strat[s])):
    ss = strat[sname]
    buys = [r for r in ss if r["方向"] == "BUY"]
    sells = [r for r in ss if r["方向"] == "SELL"]
    if buys:
        b_prof = [float(r["收益"]) for r in buys]
        b_win = sum(1 for p in b_prof if p>0)
        print(f"  {sname:<20} BUY:{len(buys):>4}笔 胜{b_win:>3} 总{sum(b_prof):>+8.2f}", end="")
    if sells:
        s_prof = [float(r["收益"]) for r in sells]
        s_win = sum(1 for p in s_prof if p>0)
        print(f"  SELL:{len(sells):>4}笔 胜{s_win:>3} 总{sum(s_prof):>+8.2f}", end="")
    print()

# 出场原因分析
print(f"\n{'─'*70}")
print(f"  四、出场原因分析")
print(f"{'─'*70}")
reason_stats = defaultdict(lambda: {"count": 0, "pnl": 0.0})
for r in rows:
    reason = r["出场原因"][:20]
    reason_stats[reason]["count"] += 1
    reason_stats[reason]["pnl"] += float(r["收益"]) if r["收益"] else 0

for reason, data in sorted(reason_stats.items(), key=lambda x: -x[1]["count"]):
    print(f"  {reason:<25} {data['count']:>6}次  总收益{data['pnl']:>+8.2f}")

# 盈亏区间分布
print(f"\n{'─'*70}")
print(f"  五、盈亏区间分布")
print(f"{'─'*70}")
ranges = [
    ("亏>$30", -9999, -30),
    ("亏$10-30", -30, -10),
    ("亏$0-10", -10, 0),
    ("赚$0-10", 0, 10),
    ("赚$10-30", 10, 30),
    ("赚>$30", 30, 9999),
]
for label, lo, hi in ranges:
    n = sum(1 for p in all_profits if lo <= p < hi)
    print(f"  {label:<15} {n:>6}笔 占比{n/len(all_profits)*100:>5.1f}%")

# 策略推荐
print(f"\n{'─'*70}")
print(f"  六、策略评估与建议")
print(f"{'─'*70}")
for sname in sorted(strat.keys(), key=lambda s: -len(strat[s])):
    ss = strat[sname]
    profits = [float(r["收益"]) for r in ss if r["收益"]]
    if not profits: continue
    total = len(ss)
    wins = sum(1 for p in profits if p > 0)
    wr = wins/total*100
    tp = sum(profits)
    avg = tp/total

    rating = "⭐" if wr > 40 and tp > 0 else ("❌" if tp < -500 else "⚠️")
    if wr > 55 and tp > 100: rating = "⭐⭐"
    if wr > 65 and tp > 300: rating = "⭐⭐⭐"

    print(f"  {sname:<25} {rating}  胜率{wr:.0f}%  净利{tp:+.0f}  均利{avg:+.1f}")
