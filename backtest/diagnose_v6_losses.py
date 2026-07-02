"""
v6_hybrid 模式 A 亏损诊断
==========================
分析维度：
  1. 按月拆分 — 哪几个月在亏
  2. 按方向拆分 — BUY vs SELL
  3. 按出场原因 — hard_stop vs reverse_signal
  4. 按入场时偏离 EMA21 距离 — 极端位置 vs 正常
  5. 按入场评分 — 3/4/5/6/7 分
  6. 连续亏损序列 — 最长连亏几笔
  7. 盈亏比分解 — 平均盈利 vs 平均亏损
"""
import os
import sys
import csv
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backtest.mean_reversion_bt import (
    load_h1_data, generate_v6_signal, apply_reverse_mode, run_backtest_mode, Trade
)


def diagnose():
    print("=" * 70)
    print("  v6_hybrid 亏损诊断 (模式 A 原始，H1 2024-01 ~ 2026-06)")
    print("=" * 70)

    candles = load_h1_data()
    print(f"  {len(candles)} 根 H1 K线\n")

    # ── 1. 跑回测，收集每笔交易 + 入场时的 dist_atr/regime/long_score/short_score ──
    trades_with_ctx = []
    position = None
    entry_price = 0.0
    entry_idx = 0
    entry_signal_dist = 0.0
    entry_score = 0
    entry_long_factors = []
    entry_short_factors = []
    entry_regime = ""
    reverse_tag = ""
    n = len(candles)

    for i in range(250, n):
        c = candles[i]
        sig_info = generate_v6_signal(candles, i)
        signal, tags = apply_reverse_mode(sig_info, "A")

        if signal and position is None:
            position = signal
            entry_price = c['close']
            entry_idx = i
            entry_signal_dist = sig_info["dist_atr"]
            entry_score = sig_info["long_score"] if signal == "BUY" else sig_info["short_score"]
            entry_long_factors = list(sig_info["long_factors"])
            entry_short_factors = list(sig_info["short_factors"])
            entry_regime = sig_info["regime"]
            reverse_tag = tags[0] if tags else ""

        elif position is not None:
            atr_val = sig_info["atr"] if sig_info else 0
            pnl_pts = (c['close'] - entry_price) if position == "BUY" else (entry_price - c['close'])

            # hard stop
            if atr_val > 0 and pnl_pts < -atr_val * 2.0:
                pnl = pnl_pts * 10 * 0.01 - 0.5
                trades_with_ctx.append({
                    "entry_time": candles[entry_idx]['ts_str'],
                    "exit_time": c['ts_str'],
                    "month": candles[entry_idx]['ts_str'][:7],
                    "direction": position,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(c['close'], 2),
                    "pnl": round(pnl, 2),
                    "bars": i - entry_idx,
                    "exit_reason": "hard_stop",
                    "dist_atr_entry": round(entry_signal_dist, 2),
                    "score_entry": entry_score,
                    "factors_entry": ",".join(entry_long_factors if position == "BUY" else entry_short_factors),
                    "regime_entry": entry_regime,
                })
                position = None

            # reverse signal
            elif signal and signal != position:
                pnl = pnl_pts * 10 * 0.01 - 0.5
                trades_with_ctx.append({
                    "entry_time": candles[entry_idx]['ts_str'],
                    "exit_time": c['ts_str'],
                    "month": candles[entry_idx]['ts_str'][:7],
                    "direction": position,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(c['close'], 2),
                    "pnl": round(pnl, 2),
                    "bars": i - entry_idx,
                    "exit_reason": "reverse_signal",
                    "dist_atr_entry": round(entry_signal_dist, 2),
                    "score_entry": entry_score,
                    "factors_entry": ",".join(entry_long_factors if position == "BUY" else entry_short_factors),
                    "regime_entry": entry_regime,
                })
                position = signal
                entry_price = c['close']
                entry_idx = i
                entry_signal_dist = sig_info["dist_atr"]
                entry_score = sig_info["long_score"] if signal == "BUY" else sig_info["short_score"]
                entry_long_factors = list(sig_info["long_factors"])
                entry_short_factors = list(sig_info["short_factors"])
                entry_regime = sig_info["regime"]
                reverse_tag = tags[0] if tags else ""

    print(f"  共 {len(trades_with_ctx)} 笔交易\n")

    # ── 保存 CSV ──
    csv_path = os.path.join(SCRIPT_DIR, "v6_diagnose_trades.csv")
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        if trades_with_ctx:
            w = csv.DictWriter(f, fieldnames=trades_with_ctx[0].keys())
            w.writeheader()
            w.writerows(trades_with_ctx)
    print(f"  交易明细: {csv_path}\n")

    # ── 2. 按月拆分 ──
    print("=" * 70)
    print("  [1] 按月拆分 (找亏损集中月)")
    print("=" * 70)
    by_month = defaultdict(list)
    for t in trades_with_ctx:
        by_month[t['month']].append(t)

    print(f"  {'月份':<10} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'累计':>10}")
    print("  " + "-" * 70)
    cum = 0
    month_rows = []
    for month in sorted(by_month.keys()):
        ts = by_month[month]
        wins = sum(1 for t in ts if t['pnl'] > 0)
        losses = sum(1 for t in ts if t['pnl'] <= 0)
        pnl = sum(t['pnl'] for t in ts)
        avg = pnl / len(ts)
        wr = wins / len(ts) * 100
        cum += pnl
        month_rows.append((month, len(ts), wins, losses, wr, pnl, avg, cum))
    for month, n_t, w, l, wr, pnl, avg, c in month_rows:
        flag = "🔴" if pnl < -50 else ("🟢" if pnl > 20 else "  ")
        print(f"  {month:<10} {n_t:>5} {w:>4} {l:>4} {wr:>6.1f}% ${pnl:>+8.2f} ${avg:>+6.2f} ${c:>+8.2f}  {flag}")

    # 找出最大亏损月
    worst_month = min(month_rows, key=lambda r: r[5])
    print(f"\n  最大亏损月: {worst_month[0]}  亏损 ${worst_month[5]:+.2f}  ({worst_month[1]} 笔)")

    # ── 3. 按方向拆分 ──
    print("\n" + "=" * 70)
    print("  [2] 按方向拆分 (BUY vs SELL)")
    print("=" * 70)
    by_dir = defaultdict(list)
    for t in trades_with_ctx:
        by_dir[t['direction']].append(t)
    print(f"  {'方向':<8} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'平均K线':>8}")
    print("  " + "-" * 60)
    for d in ['BUY', 'SELL']:
        if d in by_dir:
            ts = by_dir[d]
            wins = sum(1 for t in ts if t['pnl'] > 0)
            losses = sum(1 for t in ts if t['pnl'] <= 0)
            pnl = sum(t['pnl'] for t in ts)
            avg = pnl / len(ts)
            wr = wins / len(ts) * 100
            avg_bars = sum(t['bars'] for t in ts) / len(ts)
            print(f"  {d:<8} {len(ts):>5} {wins:>4} {losses:>4} {wr:>6.1f}% ${pnl:>+8.2f} ${avg:>+6.2f} {avg_bars:>8.1f}")

    # ── 4. 按出场原因拆分 ──
    print("\n" + "=" * 70)
    print("  [3] 按出场原因拆分 (hard_stop vs reverse_signal)")
    print("=" * 70)
    by_exit = defaultdict(list)
    for t in trades_with_ctx:
        by_exit[t['exit_reason']].append(t)
    print(f"  {'出场原因':<16} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'占比':>7}")
    print("  " + "-" * 70)
    for reason in ['hard_stop', 'reverse_signal']:
        if reason in by_exit:
            ts = by_exit[reason]
            wins = sum(1 for t in ts if t['pnl'] > 0)
            losses = sum(1 for t in ts if t['pnl'] <= 0)
            pnl = sum(t['pnl'] for t in ts)
            avg = pnl / len(ts)
            wr = wins / len(ts) * 100
            pct = len(ts) / len(trades_with_ctx) * 100
            print(f"  {reason:<16} {len(ts):>5} {wins:>4} {losses:>4} {wr:>6.1f}% ${pnl:>+8.2f} ${avg:>+6.2f} {pct:>6.1f}%")

    # ── 5. 按入场时偏离 EMA21 距离拆分 ──
    print("\n" + "=" * 70)
    print("  [4] 按入场时偏离 EMA21 距离拆分 (sigma 单位)")
    print("=" * 70)
    bins = [
        ("<-2.0σ 极低",  lambda d: d < -2.0),
        ("-2.0~-1.0σ",  lambda d: -2.0 <= d < -1.0),
        ("-1.0~-0.5σ",  lambda d: -1.0 <= d < -0.5),
        ("-0.5~+0.5σ",  lambda d: -0.5 <= d < 0.5),
        ("+0.5~+1.0σ",  lambda d: 0.5 <= d < 1.0),
        ("+1.0~+2.0σ",  lambda d: 1.0 <= d < 2.0),
        (">+2.0σ 极高",  lambda d: d >= 2.0),
    ]
    print(f"  {'偏离区间':<16} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8}")
    print("  " + "-" * 60)
    for label, fn in bins:
        ts = [t for t in trades_with_ctx if fn(t['dist_atr_entry'])]
        if not ts:
            continue
        wins = sum(1 for t in ts if t['pnl'] > 0)
        losses = sum(1 for t in ts if t['pnl'] <= 0)
        pnl = sum(t['pnl'] for t in ts)
        avg = pnl / len(ts)
        wr = wins / len(ts) * 100
        print(f"  {label:<16} {len(ts):>5} {wins:>4} {losses:>4} {wr:>6.1f}% ${pnl:>+8.2f} ${avg:>+6.2f}")

    # ── 6. 按入场评分拆分 ──
    print("\n" + "=" * 70)
    print("  [5] 按入场评分拆分 (3/4/5/6/7+ 分)")
    print("=" * 70)
    by_score = defaultdict(list)
    for t in trades_with_ctx:
        by_score[t['score_entry']].append(t)
    print(f"  {'评分':<8} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8}")
    print("  " + "-" * 55)
    for score in sorted(by_score.keys()):
        ts = by_score[score]
        wins = sum(1 for t in ts if t['pnl'] > 0)
        losses = sum(1 for t in ts if t['pnl'] <= 0)
        pnl = sum(t['pnl'] for t in ts)
        avg = pnl / len(ts)
        wr = wins / len(ts) * 100
        print(f"  {score:<8} {len(ts):>5} {wins:>4} {losses:>4} {wr:>6.1f}% ${pnl:>+8.2f} ${avg:>+6.2f}")

    # ── 7. 连续亏损序列 ──
    print("\n" + "=" * 70)
    print("  [6] 连续亏损序列 (找最长连亏)")
    print("=" * 70)
    max_streak = 0
    cur_streak = 0
    streak_pnl = 0
    max_streak_pnl = 0
    streak_start = ""
    max_streak_start = ""
    streak_end = ""
    max_streak_end = ""
    streaks = []  # (start, end, length, pnl)
    cur_start = ""
    for t in trades_with_ctx:
        if t['pnl'] <= 0:
            if cur_streak == 0:
                cur_start = t['entry_time']
            cur_streak += 1
            streak_pnl += t['pnl']
            streak_end = t['exit_time']
            if cur_streak > max_streak:
                max_streak = cur_streak
                max_streak_pnl = streak_pnl
                max_streak_start = cur_start
                max_streak_end = streak_end
        else:
            if cur_streak > 0:
                streaks.append((cur_start, streak_end, cur_streak, streak_pnl))
            cur_streak = 0
            streak_pnl = 0
    if cur_streak > 0:
        streaks.append((cur_start, streak_end, cur_streak, streak_pnl))

    print(f"  最长连亏: {max_streak} 笔  累计 ${max_streak_pnl:+.2f}  ({max_streak_start} ~ {max_streak_end})")
    print(f"\n  Top 10 连续亏损序列:")
    print(f"  {'起始':<18} {'结束':<18} {'笔数':>5} {'累计P/L':>10}")
    print("  " + "-" * 55)
    for s in sorted(streaks, key=lambda x: -x[2])[:10]:
        print(f"  {s[0]:<18} {s[1]:<18} {s[2]:>5} ${s[3]:>+8.2f}")

    # ── 8. 盈亏比分解 ──
    print("\n" + "=" * 70)
    print("  [7] 盈亏比分解 (平均盈利 vs 平均亏损)")
    print("=" * 70)
    wins = [t for t in trades_with_ctx if t['pnl'] > 0]
    losses = [t for t in trades_with_ctx if t['pnl'] <= 0]
    if wins:
        avg_win = sum(t['pnl'] for t in wins) / len(wins)
        max_win = max(t['pnl'] for t in wins)
        print(f"  盈利: {len(wins)} 笔, 平均 ${avg_win:+.2f}, 最大 ${max_win:+.2f}")
    if losses:
        avg_loss = sum(t['pnl'] for t in losses) / len(losses)
        max_loss = min(t['pnl'] for t in losses)
        print(f"  亏损: {len(losses)} 笔, 平均 ${avg_loss:+.2f}, 最大 ${max_loss:+.2f}")
    if wins and losses:
        pf = sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses))
        print(f"  盈亏比: {pf:.2f}")
        # 期望值 = 胜率 * 平均盈利 + (1-胜率) * 平均亏损
        wr = len(wins) / len(trades_with_ctx)
        ev = wr * avg_win + (1 - wr) * avg_loss
        print(f"  单笔期望值: ${ev:+.3f}")
        # 需要胜率多少才能打平 (假设平均盈亏比固定)
        if avg_win > 0 and avg_loss < 0:
            breakeven_wr = abs(avg_loss) / (avg_win + abs(avg_loss)) * 100
            print(f"  打平胜率: {breakeven_wr:.1f}% (当前 {wr*100:.1f}%, 差距 {breakeven_wr - wr*100:+.1f}pp)")

    # ── 9. 出场原因 + 方向 交叉分析 ──
    print("\n" + "=" * 70)
    print("  [8] 方向 × 出场原因 交叉分析 (谁在被硬止损?)")
    print("=" * 70)
    cross = defaultdict(list)
    for t in trades_with_ctx:
        cross[(t['direction'], t['exit_reason'])].append(t)
    print(f"  {'方向':<8} {'出场':<16} {'交易':>5} {'胜率':>7} {'总盈亏':>10} {'均单':>8}")
    print("  " + "-" * 55)
    for (d, r), ts in sorted(cross.items()):
        wins = sum(1 for t in ts if t['pnl'] > 0)
        wr = wins / len(ts) * 100
        pnl = sum(t['pnl'] for t in ts)
        avg = pnl / len(ts)
        print(f"  {d:<8} {r:<16} {len(ts):>5} {wr:>6.1f}% ${pnl:>+8.2f} ${avg:>+6.2f}")

    # ── 10. 关键诊断结论 ──
    print("\n" + "=" * 70)
    print("  [9] 关键诊断结论")
    print("=" * 70)

    # 找 hard_stop 占比
    if 'hard_stop' in by_exit:
        hs_pct = len(by_exit['hard_stop']) / len(trades_with_ctx) * 100
        hs_pnl = sum(t['pnl'] for t in by_exit['hard_stop'])
        print(f"  • 硬止损出场: {len(by_exit['hard_stop'])} 笔 ({hs_pct:.1f}%), 总盈亏 ${hs_pnl:+.2f}")

    # 找 SELL 的表现
    if 'SELL' in by_dir:
        sell_ts = by_dir['SELL']
        sell_pnl = sum(t['pnl'] for t in sell_ts)
        sell_wr = sum(1 for t in sell_ts if t['pnl'] > 0) / len(sell_ts) * 100
        print(f"  • SELL 单: {len(sell_ts)} 笔, 胜率 {sell_wr:.1f}%, 总盈亏 ${sell_pnl:+.2f}")
        if sell_pnl < -100:
            print(f"    → 2024-2025 黄金大牛市，做空被反复打止损（推测）")

    # 找极端位置的胜率
    extreme_buy = [t for t in trades_with_ctx if t['direction'] == 'BUY' and t['dist_atr_entry'] > 1.0]
    extreme_sell = [t for t in trades_with_ctx if t['direction'] == 'SELL' and t['dist_atr_entry'] < -1.0]
    if extreme_buy:
        ext_buy_pnl = sum(t['pnl'] for t in extreme_buy)
        ext_buy_wr = sum(1 for t in extreme_buy if t['pnl'] > 0) / len(extreme_buy) * 100
        print(f"  • 高位 BUY (距 EMA21 > +1σ): {len(extreme_buy)} 笔, 胜率 {ext_buy_wr:.1f}%, 盈亏 ${ext_buy_pnl:+.2f}")
    if extreme_sell:
        ext_sell_pnl = sum(t['pnl'] for t in extreme_sell)
        ext_sell_wr = sum(1 for t in extreme_sell if t['pnl'] > 0) / len(extreme_sell) * 100
        print(f"  • 低位 SELL (距 EMA21 < -1σ): {len(extreme_sell)} 笔, 胜率 {ext_sell_wr:.1f}%, 盈亏 ${ext_sell_pnl:+.2f}")


if __name__ == "__main__":
    diagnose()
