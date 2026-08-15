"""
StochBB v9 — 双路并行验证
==========================
路 1: 跨品种/跨周期稳健性 (用 GC 期货数据)
  L1: GC_H1 F3 (2 年, 11,400 根)
  L2: GC_M30 F3 (60 天, 1,895 根)
  L3: M30 F3 (复测, 88 天)

路 2: M30 稳健性测试 (5 个变种)
  R1: G5 K阈值 25/75 (更宽松 main 触发)
  R2: G6 移动止盈 (peak 回撤 50% 出场)
  R3: G7 BB 宽度过滤 (只在 BB 收缩时入场)
  R4: R1+R2+R3 三合一
  R5: R4 + SL=1.2 (激进稳健)

⚠️ GC 是 COMEX 黄金期货, 跟 XAUUSD 现货略有差异, 但相关性 99%+
⚠️ 仍然是 F3 思路 (no-fail + SL=1 ATR)
"""
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backtest.mean_reversion_bt import (
    load_ohlcv, calc_ema, calc_sma, calc_atr_from_lists,
    calc_stoch, calc_adx_proxy, calc_bb
)


def calc_ma(closes, period, ma_type):
    if ma_type == "EMA":
        return calc_ema(closes, period)
    return calc_sma(closes, period)


def run_backtest(candles, ma_type, ma_period, regime_method,
                 sl_atr=1.0, bb_slope_threshold=0.01,
                 k_oversold=20, k_overbought=80,    # G5: K 阈值
                 bb_width_max=1.0,                  # G7: BB 宽度过滤 (1.0=不限制)
                 trailing_stop_pct=0.0,             # G6: 移动止盈回撤 (0=关闭)
                 lot_size=0.01, commission=0.5):
    """F3 思路 + G5/G6/G7 微调"""
    trades = []
    position = None
    entry_info = {}
    cross_up_counter = 0
    cross_down_counter = 0

    n = len(candles)

    for i in range(251, n):
        c = candles[i]
        sub = candles[:i + 1]
        closes = [x['close'] for x in sub]
        highs = [x['high'] for x in sub]
        lows = [x['low'] for x in sub]
        close = closes[-1]

        ma_val = calc_ma(closes, ma_period, ma_type)
        if ma_val is None:
            continue
        atr_val = calc_atr_from_lists(highs, lows, closes, 20)
        if atr_val is None or atr_val <= 0:
            continue
        adx_p = calc_adx_proxy(highs, lows, 14) or 0
        bb = calc_bb(closes, 20, 2.5)
        if bb is None:
            continue
        bb_width = bb["width"]
        bb_mid = bb["sma"]

        if i >= 1:
            closes_prev_bar = [x['close'] for x in candles[:i]]
            if len(closes_prev_bar) >= 20:
                sma20_prev = sum(closes_prev_bar[-20:]) / 20
                bb_mid_slope = bb_mid - sma20_prev
            else:
                bb_mid_slope = 0
        else:
            bb_mid_slope = 0

        stoch = calc_stoch([highs, lows, closes], 9, 3, 3)
        if stoch is None:
            continue
        k_curr = stoch["curr_k"]
        k_prev = stoch["prev_k"]
        d_curr = stoch["curr_d"]
        d_prev = stoch["prev_d"]

        cross_up_now = (k_curr > d_curr) and (k_prev <= d_prev)
        cross_down_now = (k_curr < d_curr) and (k_prev >= d_prev)

        if cross_up_now:
            cross_up_counter = 3
        if cross_down_now:
            cross_down_counter = 3
        if cross_up_counter > 0:
            cross_up_counter -= 1
        if cross_down_counter > 0:
            cross_down_counter -= 1

        if regime_method == "ADX":
            is_ranging = adx_p < 0.55
        else:
            is_ranging = (adx_p < 0.55) and (bb_width < 0.04)

        k_rising = k_curr > k_prev
        bb_rising = bb_mid_slope > bb_slope_threshold
        bb_falling = bb_mid_slope < -bb_slope_threshold
        bb_flat = abs(bb_mid_slope) <= bb_slope_threshold

        # ── 入场 ──
        if position is None:
            if is_ranging and bb_width <= bb_width_max:
                if (k_curr < k_oversold) and cross_up_now and (close < ma_val):
                    position = "LONG"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "ranging",
                        "peak_pnl_pts": 0.0,  # 移动止盈跟踪
                    }
                elif (k_curr > k_overbought) and cross_down_now and (close > ma_val):
                    position = "SHORT"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "ranging",
                        "peak_pnl_pts": 0.0,
                    }

        # ── 出场 ──
        else:
            pnl_pts = (close - entry_info['price']) if position == "LONG" else (entry_info['price'] - close)

            # 跟踪 peak (用于移动止盈)
            if pnl_pts > entry_info['peak_pnl_pts']:
                entry_info['peak_pnl_pts'] = pnl_pts

            exit_reason = None
            exit_p = close

            # 1. SL
            if pnl_pts < -entry_info['atr'] * sl_atr:
                exit_reason = "hard_stop"
                if position == "LONG":
                    exit_p = entry_info['price'] - entry_info['atr'] * sl_atr
                else:
                    exit_p = entry_info['price'] + entry_info['atr'] * sl_atr

            # 2. 移动止盈 (G6): 从 peak 回撤 trailing_stop_pct 就出
            if exit_reason is None and trailing_stop_pct > 0 and entry_info['peak_pnl_pts'] > 0:
                if pnl_pts < entry_info['peak_pnl_pts'] * (1 - trailing_stop_pct):
                    exit_reason = "trailing_stop"
                    exit_p = close

            # 3. main / misalign 出场 (no-fail)
            if exit_reason is None:
                regime = entry_info['regime']
                if regime == "ranging":
                    if position == "LONG":
                        if cross_down_now and (close >= entry_info['ma']) and (k_curr < 80):
                            aligned = (bb_rising == k_rising)
                            if not aligned:
                                exit_reason = "rng_long_misalign"
                        elif cross_down_now and (close >= entry_info['ma']) and (k_curr >= 80):
                            exit_reason = "rng_long_main"
                    else:
                        if cross_up_now and (close <= entry_info['ma']) and (k_curr > 20):
                            aligned = (bb_rising == k_rising)
                            if not aligned:
                                exit_reason = "rng_short_misalign"
                        elif cross_up_now and (close <= entry_info['ma']) and (k_curr <= 20):
                            exit_reason = "rng_short_main"

            if exit_reason:
                final_pnl_pts = (exit_p - entry_info['price']) if position == "LONG" else (entry_info['price'] - exit_p)
                pnl = final_pnl_pts * 10 * lot_size - commission
                trades.append({
                    "entry_time": entry_info['time'],
                    "exit_time": c['ts_str'],
                    "direction": position,
                    "entry_price": round(entry_info['price'], 2),
                    "exit_price": round(exit_p, 2),
                    "pnl": round(pnl, 2),
                    "bars": i - entry_info['idx'],
                    "exit_reason": exit_reason,
                    "regime": entry_info['regime'],
                })
                position = None

    if position is not None:
        c = candles[-1]
        close = c['close']
        final_pnl_pts = (close - entry_info['price']) if position == "LONG" else (entry_info['price'] - close)
        pnl = final_pnl_pts * 10 * lot_size - commission
        trades.append({
            "entry_time": entry_info['time'],
            "exit_time": c['ts_str'],
            "direction": position,
            "entry_price": round(entry_info['price'], 2),
            "exit_price": round(close, 2),
            "pnl": round(pnl, 2),
            "bars": n - 1 - entry_info['idx'],
            "exit_reason": "end_of_data",
            "regime": entry_info['regime'],
        })

    return trades


def compute_stats(trades):
    closed = [t for t in trades if t['exit_reason'] != "end_of_data"]
    if not closed:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0,
                "avg_pnl": 0, "max_drawdown": 0, "profit_factor": 0, "avg_bars": 0,
                "rng_count": 0, "trend_count": 0, "long_count": 0, "short_count": 0}

    wins = [t for t in closed if t['pnl'] > 0]
    losses = [t for t in closed if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in closed)
    avg_pnl = total_pnl / len(closed)

    cum = 0
    peak = 0
    max_dd = 0
    for t in closed:
        cum += t['pnl']
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    gross_profit = sum(t['pnl'] for t in wins)
    gross_loss = abs(sum(t['pnl'] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) * 100,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "max_drawdown": round(max_dd, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_bars": round(sum(t['bars'] for t in closed) / len(closed), 1),
        "rng_count": sum(1 for t in closed if t['regime'] == 'ranging'),
        "trend_count": sum(1 for t in closed if t['regime'] == 'trending'),
        "long_count": sum(1 for t in closed if t['direction'] == "LONG"),
        "short_count": sum(1 for t in closed if t['direction'] == "SHORT"),
    }


def main():
    print("=" * 100)
    print("  StochBB v9 — 双路并行验证 (跨品种稳健性 + M30 微调)")
    print("=" * 100)
    print("  v8 突破: F3 在 M30 = +$70.77, 胜率 37%, 盈亏比 1.66")
    print()

    m30 = load_ohlcv("M30")
    gc_h1 = load_ohlcv("GC_H1")
    gc_m30 = load_ohlcv("GC_M30")

    # 路 1: 跨品种/跨周期
    path1 = [
        ("L1 GC_H1 F3",  "GC_H1", gc_h1, {}),
        ("L2 GC_M30 F3", "GC_M30", gc_m30, {}),
        ("L3 M30 F3 (复测)", "M30", m30, {}),
    ]
    # 路 2: M30 稳健性
    path2 = [
        ("R1 G5 K=25/75",          "M30", m30, {"k_oversold": 25, "k_overbought": 75}),
        ("R2 G6 trailing=50%",     "M30", m30, {"trailing_stop_pct": 0.5}),
        ("R3 G7 BB<0.025",         "M30", m30, {"bb_width_max": 0.025}),
        ("R4 G5+G6+G7 三合一",      "M30", m30, {"k_oversold": 25, "k_overbought": 75, "trailing_stop_pct": 0.5, "bb_width_max": 0.025}),
        ("R5 R4 + SL=1.2",         "M30", m30, {"k_oversold": 25, "k_overbought": 75, "trailing_stop_pct": 0.5, "bb_width_max": 0.025, "sl_atr": 1.2}),
    ]

    all_trades = {}
    results = []

    print("  ── 路 1: 跨品种跨周期 ──")
    for name, tf, candles, kw in path1:
        print(f"  跑 {name} ({tf}, {len(candles)} 根)...", end="", flush=True)
        trades = run_backtest(candles, ma_type="EMA", ma_period=21, regime_method="ADX", **kw)
        stats = compute_stats(trades)
        stats["name"] = name
        stats["tf"] = tf
        stats["path"] = "L"
        results.append(stats)
        all_trades[name] = trades
        mark = " ✅" if stats['total_pnl'] > 0 else " ❌"
        print(f" {stats['trades']} 笔, 胜率 {stats['win_rate']:.1f}%, P/L ${stats['total_pnl']:+.2f}, 盈亏比 {stats['profit_factor']:.2f}{mark}")

    print()
    print("  ── 路 2: M30 稳健性微调 ──")
    for name, tf, candles, kw in path2:
        print(f"  跑 {name} ({tf}, {len(candles)} 根)...", end="", flush=True)
        trades = run_backtest(candles, ma_type="EMA", ma_period=21, regime_method="ADX", **kw)
        stats = compute_stats(trades)
        stats["name"] = name
        stats["tf"] = tf
        stats["path"] = "R"
        results.append(stats)
        all_trades[name] = trades
        mark = " ✅" if stats['total_pnl'] > 0 else " ❌"
        print(f" {stats['trades']} 笔, 胜率 {stats['win_rate']:.1f}%, P/L ${stats['total_pnl']:+.2f}, 盈亏比 {stats['profit_factor']:.2f}{mark}")

    print("\n" + "=" * 135)
    print("  对比表 (按 path + P/L 降序)")
    print("=" * 135)
    print(f"  {'配置':<22} {'TF':<8} {'路':<3} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'最大回撤':>10} {'盈亏比':>7} {'L':>4} {'S':>4} {'均K线':>7}")
    print("  " + "-" * 135)
    for path in ["L", "R"]:
        path_results = [r for r in results if r['path'] == path]
        for r in sorted(path_results, key=lambda x: -x['total_pnl']):
            mark = " ✅" if r['total_pnl'] > 0 else " ❌"
            print(f"  {r['name']:<22} {r['tf']:<8} {r['path']:<3} {r['trades']:>5} {r['wins']:>4} {r['losses']:>4} "
                  f"{r['win_rate']:>6.1f}% ${r['total_pnl']:>+8.2f} ${r['avg_pnl']:>+6.2f} "
                  f"${r['max_drawdown']:>8.2f} {r['profit_factor']:>6.2f} {r['long_count']:>4} {r['short_count']:>4} {r['avg_bars']:>7.1f}{mark}")
    print("=" * 135)

    # 出场原因
    print("\n" + "=" * 80)
    print("  出场原因 (盈利配置)")
    print("=" * 80)
    for name, trades in all_trades.items():
        closed = [t for t in trades if t['exit_reason'] != 'end_of_data']
        if not closed:
            continue
        pnl = sum(t['pnl'] for t in closed)
        if pnl <= 0:
            continue
        by_reason = defaultdict(list)
        for t in closed:
            by_reason[t['exit_reason']].append(t)
        print(f"\n  ✅ {name}:")
        for reason, ts in sorted(by_reason.items(), key=lambda x: -len(x[1])):
            wins = sum(1 for t in ts if t['pnl'] > 0)
            wr = wins / len(ts) * 100
            rpnl = sum(t['pnl'] for t in ts)
            avg = rpnl / len(ts)
            print(f"    {reason:<22}: {len(ts):>4} 笔, 胜率 {wr:.1f}%, P/L ${rpnl:+.2f}, 均单 ${avg:+.2f}")

    # 决策
    print("\n" + "=" * 80)
    print("  决策建议")
    print("=" * 80)

    # 路 1 一致性
    l1 = next((r for r in results if r['name'] == "L1 GC_H1 F3"), None)
    l2 = next((r for r in results if r['name'] == "L2 GC_M30 F3"), None)
    l3 = next((r for r in results if r['name'] == "L3 M30 F3 (复测)"), None)
    if l1 and l2 and l3:
        print(f"  路 1 (跨品种/跨周期):")
        print(f"    L1 GC_H1:  P/L ${l1['total_pnl']:+.2f}, 胜率 {l1['win_rate']:.1f}%, 盈亏比 {l1['profit_factor']:.2f}")
        print(f"    L2 GC_M30: P/L ${l2['total_pnl']:+.2f}, 胜率 {l2['win_rate']:.1f}%, 盈亏比 {l2['profit_factor']:.2f}")
        print(f"    L3 M30:    P/L ${l3['total_pnl']:+.2f}, 胜率 {l3['win_rate']:.1f}%, 盈亏比 {l3['profit_factor']:.2f}")

        positive_count = sum(1 for r in [l1, l2, l3] if r['total_pnl'] > 0)
        if positive_count == 3:
            print(f"     ✅✅✅ 三品种/三周期都盈利! 策略稳健性高")
        elif positive_count == 2:
            print(f"     ✅ {positive_count}/3 盈利, 跨周期基本一致")
        else:
            print(f"     ❌ 仅 {positive_count}/3 盈利, 跨周期不一致")

    profitable = [r for r in results if r['total_pnl'] > 0]
    print(f"\n  总盈利配置: {len(profitable)}/{len(results)}")
    for r in sorted(profitable, key=lambda x: -x['total_pnl']):
        print(f"     {r['name']:<22}: P/L ${r['total_pnl']:+.2f}, 胜率 {r['win_rate']:.1f}%, 盈亏比 {r['profit_factor']:.2f}")

    best = max(results, key=lambda r: r['total_pnl'])
    print(f"\n  🏆 全局最优: {best['name']}  P/L ${best['total_pnl']:+.2f}")
    print()


if __name__ == "__main__":
    main()
