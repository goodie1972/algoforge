"""
StochBB v8 — F3 跨周期验证 + 微调
================================
基于 v7 突破: F3 no-fail = M30 上 +$73.82, 胜率 38%, 盈亏比 1.71

目标:
  1. 微调 F3 找更优 (G1/G2)
  2. 跨周期验证 F3 稳健性 (G3 = M15 上跑 F3)
  3. 组合叠加 (G4)

  G1: F3 + SL=1.2           (让 hard_stop 来晚一点)
  G2: F3 + dist=0.3         (轻度距离门禁)
  G3: F3 in M15             (跨周期验证)
  G4: F3 + SL=1.2 + dist=0.3 (组合)

⚠️ M30 数据 88 天 (2845 根), M15 数据 53 天 (3406 根)
⚠️ 样本很小, 跨周期验证是关键
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
                 dist_gate=0.0,
                 use_fail_exit=True,
                 lot_size=0.01, commission=0.5):
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
            dist = abs(close - ma_val) / atr_val
            if dist_gate > 0 and dist < dist_gate:
                pass
            elif is_ranging:
                if (k_curr < 20) and cross_up_now and (close < ma_val):
                    position = "LONG"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "ranging",
                    }
                elif (k_curr > 80) and cross_down_now and (close > ma_val):
                    position = "SHORT"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "ranging",
                    }

        # ── 出场 ──
        else:
            pnl_pts = (close - entry_info['price']) if position == "LONG" else (entry_info['price'] - close)
            exit_reason = None
            exit_p = close

            if pnl_pts < -entry_info['atr'] * sl_atr:
                exit_reason = "hard_stop"
                if position == "LONG":
                    exit_p = entry_info['price'] - entry_info['atr'] * sl_atr
                else:
                    exit_p = entry_info['price'] + entry_info['atr'] * sl_atr

            if exit_reason is None:
                regime = entry_info['regime']
                if regime == "ranging":
                    if position == "LONG":
                        if use_fail_exit and cross_down_now and (close < entry_info['ma']):
                            exit_reason = "rng_long_fail"
                        elif cross_down_now and (close >= entry_info['ma']) and (k_curr < 80):
                            aligned = (bb_rising == k_rising)
                            if not aligned:
                                exit_reason = "rng_long_misalign"
                        elif cross_down_now and (close >= entry_info['ma']) and (k_curr >= 80):
                            exit_reason = "rng_long_main"
                    else:
                        if use_fail_exit and cross_up_now and (close > entry_info['ma']):
                            exit_reason = "rng_short_fail"
                        elif cross_up_now and (close <= entry_info['ma']) and (k_curr > 20):
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
    print("=" * 90)
    print("  StochBB v8 — F3 跨周期验证 + 微调")
    print("=" * 90)
    print("  v7 突破: F3 (no-fail) 在 M30 = +$73.82, 胜率 38%, 盈亏比 1.71")
    print()

    m30 = load_ohlcv("M30")
    m15 = load_ohlcv("M15")

    # 配置: (label, TF, kwargs)
    configs = [
        # M30 微调
        ("F3 base (M30)",     "M30", {"sl_atr": 1.0, "dist_gate": 0.0, "use_fail_exit": False}),
        ("G1 +SL=1.2 (M30)",  "M30", {"sl_atr": 1.2, "dist_gate": 0.0, "use_fail_exit": False}),
        ("G2 +dist=0.3 (M30)","M30", {"sl_atr": 1.0, "dist_gate": 0.3, "use_fail_exit": False}),
        ("G4 三合一 (M30)",    "M30", {"sl_atr": 1.2, "dist_gate": 0.3, "use_fail_exit": False}),
        # M15 跨周期验证
        ("F3 base (M15)",     "M15", {"sl_atr": 1.0, "dist_gate": 0.0, "use_fail_exit": False}),
        ("G1 +SL=1.2 (M15)",  "M15", {"sl_atr": 1.2, "dist_gate": 0.0, "use_fail_exit": False}),
        ("G2 +dist=0.3 (M15)","M15", {"sl_atr": 1.0, "dist_gate": 0.3, "use_fail_exit": False}),
        # M15 + fail (反向验证 fail 是否真的没用)
        ("M15 +fail (对照)",   "M15", {"sl_atr": 1.0, "dist_gate": 0.0, "use_fail_exit": True}),
    ]

    all_trades = {}
    results = []
    for name, tf, kw in configs:
        candles = m30 if tf == "M30" else m15
        print(f"  跑 {name}...", end="", flush=True)
        trades = run_backtest(candles, ma_type="EMA", ma_period=21, regime_method="ADX", **kw)
        stats = compute_stats(trades)
        stats["name"] = name
        stats["tf"] = tf
        results.append(stats)
        all_trades[name] = trades
        print(f" {stats['trades']} 笔, 胜率 {stats['win_rate']:.1f}%, P/L ${stats['total_pnl']:+.2f}, 盈亏比 {stats['profit_factor']:.2f}")

    print("\n" + "=" * 130)
    print("  对比表 (按 TF 然后 P/L 降序)")
    print("=" * 130)
    print(f"  {'配置':<22} {'TF':<4} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'最大回撤':>10} {'盈亏比':>7} {'L':>4} {'S':>4} {'均K线':>7}")
    print("  " + "-" * 130)
    # 按 TF 分组, 组内按 P/L 降序
    for tf in ["M30", "M15"]:
        tf_results = [r for r in results if r['tf'] == tf]
        for r in sorted(tf_results, key=lambda x: -x['total_pnl']):
            mark = " ✅" if r['total_pnl'] > 0 else " ❌"
            print(f"  {r['name']:<22} {r['tf']:<4} {r['trades']:>5} {r['wins']:>4} {r['losses']:>4} "
                  f"{r['win_rate']:>6.1f}% ${r['total_pnl']:>+8.2f} ${r['avg_pnl']:>+6.2f} "
                  f"${r['max_drawdown']:>8.2f} {r['profit_factor']:>6.2f} {r['long_count']:>4} {r['short_count']:>4} {r['avg_bars']:>7.1f}{mark}")
    print("=" * 130)

    # 出场原因
    print("\n" + "=" * 80)
    print("  出场原因分布 (盈利配置)")
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

    # 跨周期一致性
    m30_results = [r for r in results if r['tf'] == "M30" and r['name'] == "F3 base (M30)"]
    m15_results = [r for r in results if r['tf'] == "M15" and r['name'] == "F3 base (M15)"]
    if m30_results and m15_results:
        m30_f3 = m30_results[0]
        m15_f3 = m15_results[0]
        if m30_f3['total_pnl'] > 0 and m15_f3['total_pnl'] > 0:
            print(f"  ✅ F3 跨周期一致盈利: M30 ${m30_f3['total_pnl']:+.2f}, M15 ${m15_f3['total_pnl']:+.2f}")
            print(f"     → 策略稳健性高, 可考虑上线试运行")
        elif m30_f3['total_pnl'] > 0 and m15_f3['total_pnl'] < 0:
            print(f"  ⚠️ F3 仅在 M30 盈利: M30 ${m30_f3['total_pnl']:+.2f}, M15 ${m15_f3['total_pnl']:+.2f}")
            print(f"     → 可能是巧合, 需要更多数据验证")
        else:
            print(f"  ❌ F3 在两个周期都亏损")

    profitable = [r for r in results if r['total_pnl'] > 0]
    print(f"\n  盈利配置数: {len(profitable)}/{len(results)}")
    for r in sorted(profitable, key=lambda x: -x['total_pnl']):
        print(f"     {r['name']:<22}: P/L ${r['total_pnl']:+.2f}, 胜率 {r['win_rate']:.1f}%, 盈亏比 {r['profit_factor']:.2f}")

    # fail 对照 (M15)
    fail_m15 = next((r for r in results if r['name'] == "M15 +fail (对照)"), None)
    nofail_m15 = next((r for r in results if r['name'] == "F3 base (M15)"), None)
    if fail_m15 and nofail_m15:
        delta = nofail_m15['total_pnl'] - fail_m15['total_pnl']
        print(f"\n  fail vs no-fail 在 M15 上: ${fail_m15['total_pnl']:+.2f} vs ${nofail_m15['total_pnl']:+.2f} (差 {delta:+.2f})")
        if delta > 0:
            print(f"     no-fail 在 M15 上也更好 (+${delta:.2f})")
        else:
            print(f"     no-fail 在 M15 上反而更差 ({delta:+.2f}), 跨周期效果不一致")
    print()


if __name__ == "__main__":
    main()
