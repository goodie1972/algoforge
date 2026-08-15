"""
v6_hybrid 因子归因分析
========================
对每笔交易，记录入场时的因子组合。
对每个因子，统计:
  - 出现次数
  - 胜率
  - 总盈亏
  - 单笔平均盈亏
  - 单因子期望贡献 = (含此因子胜率 - 整体胜率) × 整体均单

目标: 识别赚钱因子和亏钱因子
"""
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backtest.mean_reversion_bt import load_h1_data, generate_v6_signal, Trade


def run_with_factor_logging(candles, sl_atr=2.0, tp_atr=None, gate_sigma=None):
    """跑回测并记录每笔交易的所有入场因子"""
    trades_with_factors = []
    position = None
    entry_price = 0.0
    entry_idx = 0
    entry_signal_dist = 0.0
    entry_long_factors = []
    entry_short_factors = []
    entry_regime = ""
    n = len(candles)

    for i in range(250, n):
        c = candles[i]
        sig_info = generate_v6_signal(candles, i)
        if sig_info is None:
            continue
        signal = sig_info["signal"]

        if signal and position is None:
            if gate_sigma is not None and abs(sig_info["dist_atr"]) >= gate_sigma:
                continue
            position = signal
            entry_price = c['close']
            entry_idx = i
            entry_signal_dist = sig_info["dist_atr"]
            entry_long_factors = list(sig_info["long_factors"])
            entry_short_factors = list(sig_info["short_factors"])
            entry_regime = sig_info["regime"]

        elif position is not None:
            atr_val = sig_info["atr"]
            pnl_pts = (c['close'] - entry_price) if position == "BUY" else (entry_price - c['close'])

            exit_reason = None
            exit_p = c['close']

            if sl_atr is not None and atr_val > 0 and pnl_pts < -atr_val * sl_atr:
                exit_reason = "hard_stop"
                exit_p = entry_price - (atr_val * sl_atr if position == "BUY" else -atr_val * sl_atr)
            elif tp_atr is not None and atr_val > 0 and pnl_pts > atr_val * tp_atr:
                exit_reason = "take_profit"
                exit_p = entry_price + (atr_val * tp_atr if position == "BUY" else -atr_val * tp_atr)
            elif signal and signal != position:
                exit_reason = "reverse_signal"

            if exit_reason:
                final_pnl_pts = (exit_p - entry_price) if position == "BUY" else (entry_price - exit_p)
                pnl = final_pnl_pts * 10 * 0.01 - 0.5
                trades_with_factors.append({
                    "entry_time": candles[entry_idx]['ts_str'],
                    "exit_time": c['ts_str'],
                    "direction": position,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_p, 2),
                    "pnl": round(pnl, 2),
                    "bars": i - entry_idx,
                    "exit_reason": exit_reason,
                    "long_factors": list(entry_long_factors),
                    "short_factors": list(entry_short_factors),
                })
                position = None

    if position is not None:
        c = candles[-1]
        atr_val = sig_info["atr"] if sig_info else 0
        pnl_pts = (c['close'] - entry_price) if position == "BUY" else (entry_price - c['close'])
        exit_reason = "end_of_data"
        exit_p = c['close']
        if sl_atr is not None and atr_val > 0 and pnl_pts < -atr_val * sl_atr:
            exit_reason = "hard_stop"
            exit_p = entry_price - (atr_val * sl_atr if position == "BUY" else -atr_val * sl_atr)
        elif tp_atr is not None and atr_val > 0 and pnl_pts > atr_val * tp_atr:
            exit_reason = "take_profit"
            exit_p = entry_price + (atr_val * tp_atr if position == "BUY" else -atr_val * tp_atr)
        if exit_reason != "end_of_data":
            final_pnl_pts = (exit_p - entry_price) if position == "BUY" else (entry_price - exit_p)
        else:
            final_pnl_pts = pnl_pts
        pnl = final_pnl_pts * 10 * 0.01 - 0.5
        trades_with_factors.append({
            "entry_time": candles[entry_idx]['ts_str'],
            "exit_time": c['ts_str'],
            "direction": position,
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_p, 2),
            "pnl": round(pnl, 2),
            "bars": n - 1 - entry_idx,
            "exit_reason": exit_reason,
            "long_factors": list(entry_long_factors),
            "short_factors": list(entry_short_factors),
        })

    return trades_with_factors


def main():
    print("=" * 80)
    print("  v6_hybrid 因子归因分析 (模式 A-baseline: SL=2, 无 TP, 无门禁)")
    print("=" * 80)

    candles = load_h1_data()
    print(f"  数据: {len(candles)} 根 H1 K线\n")

    # 跑 baseline (与原策略一致)
    trades = run_with_factor_logging(candles, sl_atr=2.0, tp_atr=None, gate_sigma=None)
    print(f"  交易数: {len(trades)}")
    closed = [t for t in trades if t["exit_reason"] != "end_of_data"]
    total_pnl = sum(t['pnl'] for t in closed)
    wins = sum(1 for t in closed if t['pnl'] > 0)
    overall_wr = wins / len(closed) * 100 if closed else 0
    overall_avg = total_pnl / len(closed) if closed else 0
    print(f"  胜率: {overall_wr:.1f}%  总盈亏: ${total_pnl:+.2f}  均单: ${overall_avg:+.2f}\n")

    # ── 1. 按因子统计（按方向归一化）──
    print("=" * 80)
    print("  [1] 因子盈亏归因 (按方向归一化)")
    print("=" * 80)

    factor_stats = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0, "pnl_list": []})

    for t in closed:
        # 归一化因子：BUY 用 long_factors, SELL 用 short_factors
        if t['direction'] == "BUY":
            factors = t['long_factors']
        else:
            factors = t['short_factors']
        for f in factors:
            factor_stats[f]["count"] += 1
            factor_stats[f]["pnl"] += t['pnl']
            factor_stats[f]["pnl_list"].append(t['pnl'])
            if t['pnl'] > 0:
                factor_stats[f]["wins"] += 1

    print(f"  {'因子':<14} {'次数':>5} {'占比':>7} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'vs基准':>10}  评价")
    print("  " + "-" * 80)
    rows = []
    for f, st in factor_stats.items():
        wr = st["wins"] / st["count"] * 100
        avg = st["pnl"] / st["count"]
        # 因子贡献 = (含此因子均单 - 整体均单)
        contribution = avg - overall_avg
        # 用颜色标记
        if st["pnl"] > 20 and wr >= overall_wr:
            verdict = "✅ 赚钱"
        elif st["pnl"] < -20 and wr < overall_wr:
            verdict = "🔴 亏钱"
        else:
            verdict = "🟡 中性"
        rows.append((f, st["count"], st["count"]/len(closed)*100, wr, st["pnl"], avg, contribution, verdict))

    # 按总盈亏降序
    for f, cnt, pct, wr, pnl, avg, contrib, verdict in sorted(rows, key=lambda x: -x[4]):
        print(f"  {f:<14} {cnt:>5} {pct:>6.1f}% {wr:>6.1f}% ${pnl:>+8.2f} ${avg:>+6.2f} ${contrib:>+6.2f}    {verdict}")

    # ── 2. 因子组合分析：哪些因子是"必须"哪些是"可选" ──
    print("\n" + "=" * 80)
    print("  [2] 因子数量 vs 胜率 (评分与表现关系)")
    print("=" * 80)

    score_stats = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0})
    for t in closed:
        if t['direction'] == "BUY":
            n_factors = len(t['long_factors'])
        else:
            n_factors = len(t['short_factors'])
        score_stats[n_factors]["count"] += 1
        score_stats[n_factors]["pnl"] += t['pnl']
        if t['pnl'] > 0:
            score_stats[n_factors]["wins"] += 1

    print(f"  {'因子数':<8} {'交易':>5} {'胜率':>7} {'总盈亏':>10} {'均单':>8}")
    print("  " + "-" * 50)
    for nf in sorted(score_stats.keys()):
        st = score_stats[nf]
        wr = st["wins"] / st["count"] * 100
        avg = st["pnl"] / st["count"]
        print(f"  {nf:<8} {st['count']:>5} {wr:>6.1f}% ${st['pnl']:>+8.2f} ${avg:>+6.2f}")

    # ── 3. 因子对出现频率 (哪些因子经常一起出现) ──
    print("\n" + "=" * 80)
    print("  [3] 因子共生矩阵 (Top 10 因子对)")
    print("=" * 80)

    pair_stats = defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0})
    for t in closed:
        if t['direction'] == "BUY":
            factors = t['long_factors']
        else:
            factors = t['short_factors']
        # 取所有两两组合
        from itertools import combinations
        for f1, f2 in combinations(sorted(factors), 2):
            key = (f1, f2)
            pair_stats[key]["count"] += 1
            pair_stats[key]["pnl"] += t['pnl']
            if t['pnl'] > 0:
                pair_stats[key]["wins"] += 1

    print(f"  {'因子对':<28} {'次数':>5} {'胜率':>7} {'总盈亏':>10} {'均单':>8}  评价")
    print("  " + "-" * 75)
    pair_rows = []
    for (f1, f2), st in pair_stats.items():
        if st["count"] < 10:
            continue
        wr = st["wins"] / st["count"] * 100
        avg = st["pnl"] / st["count"]
        pair_label = f"{f1}+{f2}"
        if st["pnl"] > 20 and wr >= overall_wr:
            verdict = "✅"
        elif st["pnl"] < -20 and wr < overall_wr:
            verdict = "🔴"
        else:
            verdict = "🟡"
        pair_rows.append((pair_label, st["count"], wr, st["pnl"], avg, verdict))

    for label, cnt, wr, pnl, avg, v in sorted(pair_rows, key=lambda x: -x[3])[:10]:
        print(f"  {label:<28} {cnt:>5} {wr:>6.1f}% ${pnl:>+8.2f} ${avg:>+6.2f}  {v}")
    print(f"\n  ... 最差的 5 个因子对:")
    for label, cnt, wr, pnl, avg, v in sorted(pair_rows, key=lambda x: x[3])[:5]:
        print(f"  {label:<28} {cnt:>5} {wr:>6.1f}% ${pnl:>+8.2f} ${avg:>+6.2f}  {v}")

    # ── 4. 按方向 × 因子 ──
    print("\n" + "=" * 80)
    print("  [4] BUY vs SELL 的因子贡献")
    print("=" * 80)

    by_dir = defaultdict(lambda: defaultdict(lambda: {"count": 0, "wins": 0, "pnl": 0.0}))
    for t in closed:
        d = t['direction']
        if d == "BUY":
            factors = t['long_factors']
        else:
            factors = t['short_factors']
        for f in factors:
            by_dir[d][f]["count"] += 1
            by_dir[d][f]["pnl"] += t['pnl']
            if t['pnl'] > 0:
                by_dir[d][f]["wins"] += 1

    for d in ['BUY', 'SELL']:
        if d not in by_dir:
            continue
        d_trades = [t for t in closed if t['direction'] == d]
        d_total = sum(t['pnl'] for t in d_trades)
        d_avg = d_total / len(d_trades)
        print(f"\n  {d}  ({len(d_trades)} 笔, 总盈亏 ${d_total:+.2f}, 均单 ${d_avg:+.2f})")
        print(f"  {'因子':<14} {'次数':>5} {'胜率':>7} {'总盈亏':>10} {'均单':>8}")
        print("  " + "-" * 55)
        for f, st in sorted(by_dir[d].items(), key=lambda x: -x[1]["pnl"]):
            wr = st["wins"] / st["count"] * 100
            avg = st["pnl"] / st["count"]
            print(f"  {f:<14} {st['count']:>5} {wr:>6.1f}% ${st['pnl']:>+8.2f} ${avg:>+6.2f}")

    # ── 5. 关键建议 ──
    print("\n" + "=" * 80)
    print("  [5] 关键诊断")
    print("=" * 80)

    # 找亏钱因子
    bad_factors = [(f, st) for f, st in factor_stats.items() if st["pnl"] < -20]
    good_factors = [(f, st) for f, st in factor_stats.items() if st["pnl"] > 20]

    if good_factors:
        print(f"\n  ✅ 赚钱因子 (前 5):")
        for f, st in sorted(good_factors, key=lambda x: -x[1]["pnl"])[:5]:
            wr = st["wins"] / st["count"] * 100
            print(f"     {f}: {st['count']} 笔, 胜率 {wr:.1f}%, 总盈亏 ${st['pnl']:+.2f}")

    if bad_factors:
        print(f"\n  🔴 亏钱因子 (前 5):")
        for f, st in sorted(bad_factors, key=lambda x: x[1]["pnl"])[:5]:
            wr = st["wins"] / st["count"] * 100
            print(f"     {f}: {st['count']} 笔, 胜率 {wr:.1f}%, 总盈亏 ${st['pnl']:+.2f}")

    # 计算砍掉亏钱因子能省多少
    if bad_factors:
        total_bad_pnl = sum(st["pnl"] for f, st in bad_factors)
        print(f"\n  亏钱因子累计盈亏: ${total_bad_pnl:+.2f}")
        print(f"  若完全禁止这些因子(条件之一即不开仓)，理论可省 ${-total_bad_pnl:+.2f}")
        print(f"  当前总盈亏: ${total_pnl:+.2f}  → 砍后理论值: ${total_pnl - total_bad_pnl:+.2f}")
    print()


if __name__ == "__main__":
    main()
