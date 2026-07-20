# -*- coding: utf-8 -*-
"""
PaperBridge 纸面交易完整分析 (2026-07-15 ~ 2026-07-18)
"""
import csv, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent.parent
CSV_PATH = BASE / "papertest" / "papertest_bridge.csv"

rows = []
with open(CSV_PATH, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

# 合并开仓行+平仓行
trades = {}
for r in rows:
    ticket = r.get("ticket", "")
    if not ticket:
        continue
    if r.get("exit_time") and not r.get("strategy"):
        if ticket in trades:
            trades[ticket].update({
                "exit_time": r["exit_time"],
                "exit_price": r["exit_price"],
                "pnl": r["pnl"],
                "commission": r["commission"],
                "net_pnl": r["net_pnl"],
            })
    else:
        trades[ticket] = {
            "ticket": ticket, "strategy": r.get("strategy",""),
            "magic": r.get("magic",""), "direction": r.get("direction",""),
            "volume": r.get("volume",""), "entry_time": r.get("entry_time",""),
            "entry_price": r.get("entry_price",""), "stop_loss": r.get("stop_loss",""),
            "take_profit": r.get("take_profit",""), "entry_bid": r.get("entry_bid",""),
            "entry_ask": r.get("entry_ask",""),
            "exit_time": "", "exit_price": "", "pnl": "", "commission": "", "net_pnl": "",
        }

closed = {t: d for t, d in trades.items() if d.get("exit_time") and d.get("pnl","") != ""}
open_pos = {t: d for t, d in trades.items() if not d.get("exit_time") or not d.get("pnl","")}

total_pnl = sum(float(d["net_pnl"]) for d in closed.values())
total_commission = sum(float(d["commission"]) for d in closed.values())
total_gross = sum(float(d["pnl"]) for d in closed.values())
pnl_list = [float(d["net_pnl"]) for d in closed.values()]
wins = sum(1 for x in pnl_list if x > 0)
losses = sum(1 for x in pnl_list if x <= 0)
winrate = wins / len(pnl_list) * 100 if pnl_list else 0
winners_list = [x for x in pnl_list if x > 0]
losers_list = [x for x in pnl_list if x <= 0]

print("=" * 70)
print(f"  PaperBridge 纸面交易完整分析")
print(f"  周期: 2026-07-15 ~ 2026-07-18 (3天)")
print(f"  总交易: {len(trades)} 笔 | 已平仓: {len(closed)} 笔 | 持仓中: {len(open_pos)} 笔")
print("=" * 70)

# === 1. 总体 ===
print(f"\n>>> 1. 总体表现")
print(f"   毛盈亏: ${total_gross:.2f}  手续费: ${total_commission:.2f}  净盈亏: ${total_pnl:.2f}")
print(f"   胜: {wins}  负: {losses}  胜率: {winrate:.1f}%")
avg_w = sum(winners_list)/len(winners_list) if winners_list else 0
avg_l = abs(sum(losers_list)/len(losers_list)) if losers_list else 0
print(f"   盈利笔均: ${avg_w:.2f}  亏损笔均: -${avg_l:.2f}")
if winners_list and losers_list:
    print(f"   盈亏比: {avg_w/avg_l:.2f}" if avg_l > 0 else "   盈亏比: N/A")
print(f"   最大盈利: ${max(pnl_list):.2f}  最大亏损: ${min(pnl_list):.2f}")
if open_pos:
    print(f"   持仓中 {len(open_pos)} 笔:")
    for t, d in sorted(open_pos.items()):
        print(f"     #{t} {d['strategy']} {d['direction']} @ {d['entry_price']} SL={d.get('stop_loss','?')}")

# === 2. 按策略 ===
print(f"\n>>> 2. 按策略盈亏")
strat = defaultdict(lambda: {"trades":0, "wins":0, "losses":0, "pnl":0.0, "gross":0.0, "com":0.0})
for d in closed.values():
    s = d["strategy"]
    for suffix in ["_BUY", "_SELL", "_buy", "_sell"]:
        s = s.replace(suffix, "")
    pnl = float(d["net_pnl"])
    strat[s]["trades"] += 1
    strat[s]["pnl"] += pnl
    strat[s]["gross"] += float(d["pnl"])
    strat[s]["com"] += float(d["commission"])
    if pnl > 0: strat[s]["wins"] += 1
    else: strat[s]["losses"] += 1
for d in open_pos.values():
    s = d["strategy"]
    for suffix in ["_BUY", "_SELL", "_buy", "_sell"]:
        s = s.replace(suffix, "")
    strat[s]["trades"] += 1

print(f"  {'策略':30s} {'笔数':>4s} {'胜':>3s} {'负':>3s} {'胜率':>6s} {'净盈亏':>9s} {'均笔':>7s}")
print(f"  {'-'*68}")
for s, d in sorted(strat.items(), key=lambda x: x[1]["pnl"], reverse=True):
    c = d["wins"]+d["losses"]
    wr = d["wins"]/c*100 if c else 0
    avg = d["pnl"]/c if c else 0
    tag = "+" if d["pnl"] > 0 else "-"
    print(f"  {s:30s} {d['trades']:>4d} {d['wins']:>3d} {d['losses']:>3d} {wr:>5.1f}% ${d['pnl']:>+7.2f} ${avg:>+5.2f} [{tag}]")

tw = sum(d["trades"] for d in strat.values())
print(f"  {'-'*68}")
print(f"  {'合计':30s} {tw:>4d} {sum(d['wins'] for d in strat.values()):>3d} {sum(d['losses'] for d in strat.values()):>3d} {winrate:>5.1f}% ${total_pnl:>+7.2f}")

# === 3. 按方向 ===
print(f"\n>>> 3. 按方向")
for dir in ["BUY", "SELL"]:
    vals = [float(d["net_pnl"]) for d in closed.values() if d["direction"] == dir]
    if not vals: continue
    w = sum(1 for x in vals if x > 0)
    pnl = sum(vals)
    avg = pnl/len(vals)
    wr = w/len(vals)*100
    print(f"  {dir:5s}: {len(vals):>3d}笔  胜{w:>2d}({wr:>4.1f}%)  总${pnl:>+7.2f}  均${avg:>+6.2f}")

# === 4. 按日期 ===
print(f"\n>>> 4. 每日盈亏")
days = defaultdict(lambda: {"trades":0, "wins":0, "pnl":0.0})
for d in closed.values():
    day = (d.get("exit_time") or d.get("entry_time",""))[:10]
    pnl = float(d["net_pnl"])
    days[day]["trades"] += 1
    days[day]["pnl"] += pnl
    if pnl > 0: days[day]["wins"] += 1
open_days = defaultdict(int)
for d in trades.values():
    open_days[(d["entry_time"])[:10]] += 1

cum = 0
peak = 0
max_dd = 0
for day in sorted(days.keys()):
    d = days[day]
    wr = d["wins"]/d["trades"]*100 if d["trades"] else 0
    cum += d["pnl"]
    peak = max(peak, cum)
    dd = peak - cum
    max_dd = max(max_dd, dd)
    tag = "+" if d["pnl"] > 0 else "-"
    print(f"  {day:12s} 开{open_days.get(day,0):>2d}笔 平{d['trades']:>2d}笔  胜{d['wins']:>2d}({wr:>4.1f}%)  日${d['pnl']:>+7.2f}  累计${cum:>+7.2f}  [{tag}]")
print(f"  最大回撤: ${max_dd:.2f}")

# === 5. 持仓时间 ===
print(f"\n>>> 5. 持仓时间分析")
hold_times = []
for d in closed.values():
    try:
        et = datetime.strptime(d["entry_time"], "%Y-%m-%d %H:%M:%S")
        xt = datetime.strptime(d["exit_time"], "%Y-%m-%d %H:%M:%S")
        mins = (xt - et).total_seconds() / 60
        hold_times.append((mins, float(d["net_pnl"]), d["strategy"], d["direction"]))
    except:
        pass
if hold_times:
    avg_h = sum(x[0] for x in hold_times)/len(hold_times)
    print(f"   平均持仓: {avg_h:.0f}分  最短: {min(x[0] for x in hold_times):.0f}分  最长: {max(x[0] for x in hold_times):.0f}分")
    for label, lo, hi in [("0-10分",0,10),("10-30分",10,30),("30-60分",30,60),("1-2h",60,120),("2-4h",120,240),("4h+",240,99999)]:
        items = [x for x in hold_times if lo <= x[0] < hi]
        if items:
            p = sum(x[1] for x in items)
            w = sum(1 for x in items if x[1] > 0)
            wr = w/len(items)*100
            print(f"    {label:10s} {len(items):>2d}笔  胜{w:>2d}({wr:>4.1f}%)  总${p:>+7.2f}  均${p/len(items):>+6.2f}")
    # 盈利vs亏损持仓时间对比
    w_hold = [x[0] for x in hold_times if x[1] > 0]
    l_hold = [x[0] for x in hold_times if x[1] <= 0]
    if w_hold and l_hold:
        w_avg_h = sum(w_hold)/len(w_hold)
        l_avg_h = sum(l_hold)/len(l_hold)
        print(f"   盈利单均持: {w_avg_h:.0f}分  亏损单均持: {l_avg_h:.0f}分")
        if w_avg_h < l_avg_h:
            print(f"   ⚠️ 盈利单持有更短！赚就跑亏就扛！")

# === 6. 盈亏分布 ===
print(f"\n>>> 6. 盈亏区间分布")
for label, lo, hi in [("亏损>$10",-999,-10),("亏损$5~10",-10,-5),("亏损$0~5",-5,0),
                       ("盈利$0~5",0,5),("盈利$5~10",5,10),("盈利>$10",10,999)]:
    n = sum(1 for x in pnl_list if lo <= x < hi)
    pct = n/len(pnl_list)*100 if pnl_list else 0
    bar = "#" * min(n, 30)
    print(f"  {label:12s} {n:>3d}笔 ({pct:>4.1f}%) {bar}")

# === 7. 逐笔明细 ===
print(f"\n>>> 7. 逐笔交易明细")
print(f"  {'日期':12s} {'策略':30s} {'方向':4s} {'入场':>7s} {'出场':>7s} {'净盈亏':>8s} {'持仓':>5s}")
print(f"  {'-'*75}")
for ticket in sorted(trades.keys(), key=lambda t: trades[t]["entry_time"]):
    d = trades[ticket]
    s = d["strategy"]
    for suffix in ["_BUY", "_SELL", "_buy", "_sell"]:
        s = s.replace(suffix, "")
    ep = float(d["entry_price"]) if d["entry_price"] else 0
    xp = float(d["exit_price"]) if d.get("exit_price","") else 0
    pnl_s = ""
    hold = ""
    if d.get("pnl","") != "":
        pnl_s = f"${float(d['net_pnl']):.2f}"
        try:
            et = datetime.strptime(d["entry_time"], "%Y-%m-%d %H:%M:%S")
            xt = datetime.strptime(d["exit_time"], "%Y-%m-%d %H:%M:%S")
            hold = f"{int((xt-et).total_seconds()/60)}m"
        except:
            pass
    elif d.get("exit_time"):
        pnl_s = "待更新"
    else:
        pnl_s = "持仓中"
    day = (d["entry_time"])[:10] if d["entry_time"] else "?"
    print(f"  {day:12s} {s:30s} {d['direction']:4s} {ep:>7.2f} {xp:>7.2f} {pnl_s:>8s} {hold:>5s}")

# === 8. 问题诊断 ===
print(f"\n>>> 8. 问题诊断与建议")
print(f"{'='*70}")

# 盈利持时vs亏损持时
if w_hold and l_hold:
    if w_avg_h < l_avg_h:
        print(f"\n  [严重] 盈利单平均持仓 {w_avg_h:.0f}分 < 亏损单 {l_avg_h:.0f}分")
        print(f"  说明: \"赚就跑、亏就扛\" 心态/逻辑")
        print(f"  建议: 放宽 profit_drawdown_pct (0.25->0.4)，给盈利单更多空间")
        print(f"        同时收紧 hard_atr (2.0->1.5)，缩短亏损单持有时间")
    else:
        print(f"\n  [良好] 盈利单持仓 ({w_avg_h:.0f}分) > 亏损单 ({l_avg_h:.0f}分)")

# 胜率vs盈亏比
if winners_list and losers_list:
    ratio = avg_w / avg_l if avg_l > 0 else 0
    if ratio < 1.0:
        print(f"\n  [严重] 盈亏比 {ratio:.2f} < 1.0")
        print(f"  赚${avg_w:.2f}/笔 vs 亏-${avg_l:.2f}/笔")
        print(f"  建议: ")
        print(f"    1) 缩小止损距离 (hard_atr: 2.0->1.5, trail_atr: 1.0->0.8)")
        print(f"    2) 扩大止盈目标 (profit_drawdown_pct: 0.25->0.5)")
        print(f"    3) 或改用固定盈亏比出场 (如 1:2 止盈止损)")

# 策略级诊断
print(f"\n  [策略级诊断]")
for s, d in sorted(strat.items(), key=lambda x: x[1]["trades"], reverse=True):
    c = d["wins"]+d["losses"]
    if c < 2: continue
    wr = d["wins"]/c*100
    print(f"  {s:30s} {c:>2d}笔  胜率{wr:>4.1f}%  净${d['pnl']:>+7.2f}  {'✅' if d['pnl']>0 else '❌'}")
    if d['pnl'] < 0 and wr > 50:
        print(f"       → 高胜率低盈亏比，出场逻辑必须收紧止损或放宽止盈")
    elif d['pnl'] < 0 and wr < 50:
        print(f"       → 低胜率+亏损，信号逻辑需要调整")

# 方向偏差
buy_vals = [float(d["net_pnl"]) for d in closed.values() if d["direction"]=="BUY"]
sell_vals = [float(d["net_pnl"]) for d in closed.values() if d["direction"]=="SELL"]
print(f"\n  [方向偏差]")
print(f"  BUY:  {sum(buy_vals):>+8.2f} ({len(buy_vals)}笔)")
print(f"  SELL: {sum(sell_vals):>+8.2f} ({len(sell_vals)}笔)")
if sum(buy_vals) < 0 and sum(sell_vals) < 0:
    print(f"  → 双方向都亏，系统性问题，非方向选择问题")
elif sum(buy_vals) < 0:
    print(f"  → 做多亏钱，建议检查 BUY 信号的入场条件")
elif sum(sell_vals) < 0:
    print(f"  → 做空亏钱，建议检查 SELL 信号的入场条件")

# 手续费影响
fee_impact = total_commission / max(abs(total_gross), 0.01) * 100
print(f"\n  [成本分析]")
print(f"  手续费: ${total_commission:.2f}  占总盈亏: {fee_impact:.1f}%")
print(f"  平均每笔: ${total_commission/max(len(closed),1):.2f}")

print(f"\n{'='*70}")
print(f"  最终建议")
print(f"{'='*70}")
print(f"""
  核心问题: 盈亏比不足 ({avg_w/avg_l:.2f}) 且 盈利单比亏损单持有更短

  优先级建议:

  1. [高] 统一缩小止损: hard_atr 从 2.0 降到 1.5
     当前亏损笔均 -${avg_l:.2f}，1.5 ATR 止损可控制在 -$20 以内

  2. [高] 放宽利润回撤阈值: profit_drawdown_pct 0.25->0.4
     让盈利单持有更久，当前盈利笔均仅 ${avg_w:.2f}

  3. [中] stoch_trend_h1_optimized 交易最频繁，优先优化
     其他策略验证通过后再逐步启用

  4. [低] 手续费每笔 $1.0，对 0.01 手来说偏高
     检查 commission = 0.5*2 是否正确
""")
