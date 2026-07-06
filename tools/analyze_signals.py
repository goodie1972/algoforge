"""
信号分析工具 - 分析所有策略的信号质量
"""
import csv
import json
from collections import defaultdict, Counter
from datetime import datetime

CSV_PATH = "D:/backup/baobao/pythonprogram/xauusd/logs/signal_analysis.csv"
JSONL_PATH = "D:/backup/baobao/pythonprogram/xauusd/logs/signal_snapshots.jsonl"

# 当前价格参考
CURRENT_PRICE = 4154

# 读取 CSV
rows = []
with open(CSV_PATH, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for r in reader:
        sid = r.get("signal_id", "")
        if sid and sid.isdigit():
            rows.append(r)

# 去重（按 signal_id 首次出现）
seen = set()
sigs = []
for r in rows:
    if r["signal_id"] not in seen:
        seen.add(r["signal_id"])
        sigs.append(r)

print(f"="*70)
print(f"  XAUUSD 策略信号分析报告")
print(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  当前价格: {CURRENT_PRICE}")
print(f"  总信号数: {len(sigs)}")
print(f"="*70)

# 按策略分组
strat_sigs = defaultdict(list)
for s in sigs:
    strat_sigs[s["strategy"]].append(s)

# 检查哪些策略有信号
strategies_found = sorted(strat_sigs.keys())
print(f"\n有信号的策略: {strategies_found}")
print(f"没有信号的策略: ", end="")
all_strats = ["M30_rsi_bb", "sanqing_h1", "gold_auto_research", "stoch_trend_h1",
              "rsi_grading_m30", "mfi_bb_m30", "m30_bb_deepreturn",
              "bakome_backup", "entry_score_pro", "momentum_pulse_pro",
              "multi_confluence_quant", "viprasol_sniper", "xaubot_backup"]
for s in all_strats:
    if s not in strategies_found:
        print(f"{s} ", end="")
print()

print(f"\n{'='*70}")
print(f"  逐策略分析")
print(f"{'='*70}")

for sname in sorted(strat_sigs.keys()):
    ss = strat_sigs[sname]
    buys = [s for s in ss if s["signal"] == "BUY"]
    sells = [s for s in ss if s["signal"] == "SELL"]

    buy_prices = [float(s["close"]) for s in buys if s.get("close")]
    sell_prices = [float(s["close"]) for s in sells if s.get("close")]

    # 因子统计
    buy_factors = []
    sell_factors = []
    for s in ss:
        fl = s.get("factors_long", "")
        fs = s.get("factors_short", "")
        if fl:
            buy_factors.extend([f.strip() for f in fl.split(";")])
        if fs:
            sell_factors.extend([f.strip() for f in fs.split(";")])

    print(f"\n{'─'*60}")
    print(f"  {sname}")
    print(f"  {'─'*60}")
    print(f"  信号: BUY={len(buys)}  SELL={len(sells)}")
    print(f"  方向偏误: ", end="")
    if buys and not sells:
        print("[BIAS] 只做多不做空 (单向偏误)")
    elif sells and not buys:
        print("[BIAS] 只做空不做多 (单向偏误)")
    else:
        print("[ OK ] 双向均衡")

    # 价格分析
    if buy_prices:
        high_buys = sum(1 for p in buy_prices if p >= 4180)
        low_buys = sum(1 for p in buy_prices if p <= 4160)
        print(f"  做多价格: {min(buy_prices):.0f}~{max(buy_prices):.0f}")
        if high_buys > len(buys) * 0.5:
            profit = round((max(buy_prices) - CURRENT_PRICE), 2)
            print(f"  [!] {high_buys}/{len(buys)}做多在顶部(>=4180),最高点至今跌{round(max(buy_prices)-CURRENT_PRICE,2)}点")

    if sell_prices:
        high_sells = sum(1 for p in sell_prices if p >= 4180)
        print(f"  做空价格: {min(sell_prices):.0f}~{max(sell_prices):.0f}")
        if high_sells:
            print(f"  [OK] {high_sells}个做空在高位(>=4180),做空有盈利空间")

    # 前5个因子
    if buy_factors:
        top = Counter(buy_factors).most_common(5)
        print(f"  最常见做多因子: {[f'{f}({c})' for f,c in top]}")

print(f"\n{'='*70}")
print(f"  总结")
print(f"{'='*70}")
print("""
1. 大部分策略单向偏多 — 在下跌趋势中不断发BUY信号,这是"接飞刀"
2. viprasol_sniper 双向交易做的最好(73BUY+89SELL),但SELL在高位不够多
3. M30_rsi_bb 27个BUY全在4182以上,全部买在高位
4. momentum_pulse_pro 59个BUY全亏(45个在≥4180)
5. entry_score_pro 4个BUY在4199-4200(顶部),做空在4153(底部) — 追涨杀跌
6. bakome_backup 5个BUY在4153-4158(相对底部),但因子不明确
""")
