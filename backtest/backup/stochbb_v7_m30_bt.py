"""
StochBB v7 — M30 强化方向
=========================
基于 v6 最优 E2 (dist=0.5), 试 4 个方向:

  F1 严距离门禁:   dist=0.7
  F2 拉宽SL组合:   dist=0.7, SL=1.2
  F3 砍fail出场:   不用 fail 逻辑, 只用 hard_stop + main
  F4 F1+F2+F3 组合: dist=0.7, SL=1.2, 砍 fail

基线对比:
  E1 base (v5/v6): dist=0.0,  SL=1.0, fail逻辑=开
  E2 dist=0.5:     dist=0.5,  SL=1.0, fail逻辑=开

⚠️ M30 数据仅 88 天, 2845 根, 样本很小
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
                 use_fail_exit=True,    # F3: 是否用 fail 出场
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

            # 1. SL
            if pnl_pts < -entry_info['atr'] * sl_atr:
                exit_reason = "hard_stop"
                if position == "LONG":
                    exit_p = entry_info['price'] - entry_info['atr'] * sl_atr
                else:
                    exit_p = entry_info['price'] + entry_info['atr'] * sl_atr

            # 2. 模式特定出场
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
    print("  StochBB v7 — M30 强化方向")
    print("=" * 90)
    print("  基线参考:")
    print("    E1 base (v5):  dist=0.0, SL=1.0 → P/L -$22.60, 盈亏比 0.81, 胜率 29.9%")
    print("    E2 dist=0.5:   dist=0.5, SL=1.0 → P/L -$16.33, 盈亏比 0.85, 胜率 31.4%")
    print()

    candles = load_ohlcv("M30")

    configs = [
        ("E1 base (v6)",  {"dist_gate": 0.0, "sl_atr": 1.0, "use_fail_exit": True}),
        ("E2 dist=0.5",   {"dist_gate": 0.5, "sl_atr": 1.0, "use_fail_exit": True}),
        ("F1 dist=0.7",   {"dist_gate": 0.7, "sl_atr": 1.0, "use_fail_exit": True}),
        ("F2 +SL=1.2",    {"dist_gate": 0.7, "sl_atr": 1.2, "use_fail_exit": True}),
        ("F3 no-fail",    {"dist_gate": 0.5, "sl_atr": 1.0, "use_fail_exit": False}),
        ("F4 三合一",      {"dist_gate": 0.7, "sl_atr": 1.2, "use_fail_exit": False}),
    ]

    base_kwargs = dict(candles=candles, ma_type="EMA", ma_period=21, regime_method="ADX")

    all_trades = {}
    results = []
    for name, kw in configs:
        print(f"  跑 {name}...", end="", flush=True)
        trades = run_backtest(**base_kwargs, **kw)
        stats = compute_stats(trades)
        stats["name"] = name
        results.append(stats)
        all_trades[name] = trades
        print(f" {stats['trades']} 笔, 胜率 {stats['win_rate']:.1f}%, P/L ${stats['total_pnl']:+.2f}, 盈亏比 {stats['profit_factor']:.2f}")

    print("\n" + "=" * 130)
    print("  对比表 (按 P/L 降序)")
    print("=" * 130)
    print(f"  {'配置':<15} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'最大回撤':>10} {'盈亏比':>7} {'L':>4} {'S':>4} {'均K线':>7}")
    print("  " + "-" * 130)
    for r in sorted(results, key=lambda x: -x['total_pnl']):
        print(f"  {r['name']:<15} {r['trades']:>5} {r['wins']:>4} {r['losses']:>4} "
              f"{r['win_rate']:>6.1f}% ${r['total_pnl']:>+8.2f} ${r['avg_pnl']:>+6.2f} "
              f"${r['max_drawdown']:>8.2f} {r['profit_factor']:>6.2f} {r['long_count']:>4} {r['short_count']:>4} {r['avg_bars']:>7.1f}")
    print("=" * 130)

    # 出场原因
    print("\n" + "=" * 80)
    print("  出场原因分布")
    print("=" * 80)
    for name, trades in all_trades.items():
        closed = [t for t in trades if t['exit_reason'] != 'end_of_data']
        if not closed:
            continue
        by_reason = defaultdict(list)
        for t in closed:
            by_reason[t['exit_reason']].append(t)
        print(f"\n  {name}:")
        for reason, ts in sorted(by_reason.items(), key=lambda x: -len(x[1])):
            wins = sum(1 for t in ts if t['pnl'] > 0)
            wr = wins / len(ts) * 100
            pnl = sum(t['pnl'] for t in ts)
            avg = pnl / len(ts)
            print(f"    {reason:<22}: {len(ts):>4} 笔, 胜率 {wr:.1f}%, P/L ${pnl:+.2f}, 均单 ${avg:+.2f}")

    # 决策
    print("\n" + "=" * 80)
    print("  决策建议")
    print("=" * 80)
    best = max(results, key=lambda r: r['total_pnl'])
    print(f"  最优: {best['name']}  P/L ${best['total_pnl']:+.2f}  胜率 {best['win_rate']:.1f}%  盈亏比 {best['profit_factor']:.2f}")
    profitable = [r for r in results if r['total_pnl'] > 0]
    if profitable:
        print(f"  🏆 盈利配置数: {len(profitable)}/{len(results)}")
        for r in profitable:
            print(f"     {r['name']}: P/L ${r['total_pnl']:+.2f}, 胜率 {r['win_rate']:.1f}%, 盈亏比 {r['profit_factor']:.2f}")
    else:
        print(f"  仍无盈利, 但最接近: {best['name']}")

    print(f"\n  各方向 vs E1 base (-$22.60):")
    base_pnl = next(r['total_pnl'] for r in results if r['name'] == "E1 base (v6)")
    for r in results:
        if r['name'] == "E1 base (v6)":
            continue
        delta = r['total_pnl'] - base_pnl
        sign = "↑" if delta > 0 else "↓"
        print(f"    {r['name']:<15}: {sign} ${delta:+.2f}  ({base_pnl:+.2f} → {r['total_pnl']:+.2f})")
    print()


if __name__ == "__main__":
    main()
