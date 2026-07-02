"""
StochBB v10 — 最佳参数微调 + 抗尾部风险
========================================
v9 最佳: L3 M30 F3 (no-fail, K=20/80, EMA21, ADX regime) = +$67.55

v10 计划: 3 个最终变种
  T1 = L3 + R1 组合: K 25/75, 其他参数不变 (看 K 阈值是否真的更优)
  T2 = T1 + 每日最多 2 笔 (抗密集开仓, 降低单日黑天鹅风险)
  T3 = T1 + SL=1.2 (略宽止损, 减少 hard_stop 单笔 -$1.81 的拖累)

也复测 L2 GC_M30 看 T1 在期货上是否一致 (跨品种最终验证)
"""
import os
import sys
from collections import defaultdict
from datetime import datetime

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
                 k_oversold=20, k_overbought=80,
                 max_daily_trades=0,         # 每日最大开仓数 (0=无限制)
                 lot_size=0.01, commission=0.5):
    trades = []
    position = None
    entry_info = {}
    cross_up_counter = 0
    cross_down_counter = 0
    daily_open_count = {}  # date_str -> count
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
            # 每日开仓数限制
            if max_daily_trades > 0:
                # 用 K 线日期归类
                day_str = c['ts_str'][:10]
                if daily_open_count.get(day_str, 0) >= max_daily_trades:
                    pass
                else:
                    if is_ranging:
                        if (k_curr < k_oversold) and cross_up_now and (close < ma_val):
                            position = "LONG"
                            entry_info = {
                                "time": c['ts_str'], "price": close, "idx": i,
                                "ma": ma_val, "atr": atr_val, "regime": "ranging",
                            }
                            daily_open_count[day_str] = daily_open_count.get(day_str, 0) + 1
                        elif (k_curr > k_overbought) and cross_down_now and (close > ma_val):
                            position = "SHORT"
                            entry_info = {
                                "time": c['ts_str'], "price": close, "idx": i,
                                "ma": ma_val, "atr": atr_val, "regime": "ranging",
                            }
                            daily_open_count[day_str] = daily_open_count.get(day_str, 0) + 1
            else:
                if is_ranging:
                    if (k_curr < k_oversold) and cross_up_now and (close < ma_val):
                        position = "LONG"
                        entry_info = {
                            "time": c['ts_str'], "price": close, "idx": i,
                            "ma": ma_val, "atr": atr_val, "regime": "ranging",
                        }
                    elif (k_curr > k_overbought) and cross_down_now and (close > ma_val):
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
    print("=" * 90)
    print("  StochBB v10 — 最佳参数微调 + 抗尾部风险")
    print("=" * 90)
    print("  v9 最佳: L3 M30 F3 (K=20/80) = +$67.55, 胜率 36.5%, 盈亏比 1.61")
    print()

    m30 = load_ohlcv("M30")
    gc_m30 = load_ohlcv("GC_M30")

    configs = [
        # M30 主战场
        ("B0 base (L3 复测)",  "M30", m30, {"k_oversold": 20, "k_overbought": 80, "sl_atr": 1.0, "max_daily_trades": 0}),
        ("T1 K=25/75",         "M30", m30, {"k_oversold": 25, "k_overbought": 75, "sl_atr": 1.0, "max_daily_trades": 0}),
        ("T2 T1 + 2笔/日",      "M30", m30, {"k_oversold": 25, "k_overbought": 75, "sl_atr": 1.0, "max_daily_trades": 2}),
        ("T3 T1 + SL=1.2",     "M30", m30, {"k_oversold": 25, "k_overbought": 75, "sl_atr": 1.2, "max_daily_trades": 0}),
        ("T4 T1 + T2 + T3",    "M30", m30, {"k_oversold": 25, "k_overbought": 75, "sl_atr": 1.2, "max_daily_trades": 2}),
        # 跨品种最终验证
        ("B0 GC_M30 (L2 复测)", "GC_M30", gc_m30, {"k_oversold": 20, "k_overbought": 80, "sl_atr": 1.0, "max_daily_trades": 0}),
        ("T1 GC_M30",           "GC_M30", gc_m30, {"k_oversold": 25, "k_overbought": 75, "sl_atr": 1.0, "max_daily_trades": 0}),
    ]

    all_trades = {}
    results = []
    for name, tf, candles, kw in configs:
        print(f"  跑 {name} ({tf}, {len(candles)} 根)...", end="", flush=True)
        trades = run_backtest(candles, ma_type="EMA", ma_period=21, regime_method="ADX", **kw)
        stats = compute_stats(trades)
        stats["name"] = name
        stats["tf"] = tf
        results.append(stats)
        all_trades[name] = trades
        mark = " ✅" if stats['total_pnl'] > 0 else " ❌"
        print(f" {stats['trades']} 笔, 胜率 {stats['win_rate']:.1f}%, P/L ${stats['total_pnl']:+.2f}, 回撤 ${stats['max_drawdown']:.2f}{mark}")

    print("\n" + "=" * 130)
    print("  对比表 (按 TF + P/L 降序)")
    print("=" * 130)
    print(f"  {'配置':<22} {'TF':<8} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'最大回撤':>10} {'盈亏比':>7} {'L':>4} {'S':>4} {'均K线':>7}")
    print("  " + "-" * 130)
    for tf in ["M30", "GC_M30"]:
        tf_results = [r for r in results if r['tf'] == tf]
        for r in sorted(tf_results, key=lambda x: -x['total_pnl']):
            mark = " ✅" if r['total_pnl'] > 0 else " ❌"
            print(f"  {r['name']:<22} {r['tf']:<8} {r['trades']:>5} {r['wins']:>4} {r['losses']:>4} "
                  f"{r['win_rate']:>6.1f}% ${r['total_pnl']:>+8.2f} ${r['avg_pnl']:>+6.2f} "
                  f"${r['max_drawdown']:>8.2f} {r['profit_factor']:>6.2f} {r['long_count']:>4} {r['short_count']:>4} {r['avg_bars']:>7.1f}{mark}")
    print("=" * 130)

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

    # 月度分析 (盈利配置)
    print("\n" + "=" * 80)
    print("  月度 P/L (找最差月)")
    print("=" * 80)
    for name, trades in all_trades.items():
        closed = [t for t in trades if t['exit_reason'] != 'end_of_data']
        if not closed:
            continue
        pnl = sum(t['pnl'] for t in closed)
        if pnl <= 0:
            continue
        by_month = defaultdict(list)
        for t in closed:
            month = t['entry_time'][:7]
            by_month[month].append(t)
        worst = sorted([(m, sum(t['pnl'] for t in ts), len(ts)) for m, ts in by_month.items()], key=lambda x: x[1])
        best = sorted([(m, sum(t['pnl'] for t in ts), len(ts)) for m, ts in by_month.items()], key=lambda x: -x[1])
        print(f"\n  {name}:")
        print(f"    最差月: {[(m, f'${p:+.2f}', f'{n}笔') for m, p, n in worst[:3]]}")
        print(f"    最佳月: {[(m, f'${p:+.2f}', f'{n}笔') for m, p, n in best[:3]]}")

    # 决策
    print("\n" + "=" * 80)
    print("  决策建议")
    print("=" * 80)

    m30_results = [r for r in results if r['tf'] == "M30"]
    gc_results = [r for r in results if r['tf'] == "GC_M30"]
    best_m30 = max(m30_results, key=lambda r: r['total_pnl'])
    best_gc = max(gc_results, key=lambda r: r['total_pnl'])

    print(f"  M30 最优: {best_m30['name']}  P/L ${best_m30['total_pnl']:+.2f}, 胜率 {best_m30['win_rate']:.1f}%, 盈亏比 {best_m30['profit_factor']:.2f}, 回撤 ${best_m30['max_drawdown']:.2f}")
    print(f"  GC_M30 最优: {best_gc['name']}  P/L ${best_gc['total_pnl']:+.2f}, 胜率 {best_gc['win_rate']:.1f}%, 盈亏比 {best_gc['profit_factor']:.2f}, 回撤 ${best_gc['max_drawdown']:.2f}")

    # 跨品种一致性
    if best_m30['total_pnl'] > 0 and best_gc['total_pnl'] > 0:
        print(f"  ✅✅ M30 + GC_M30 双品种最优都盈利 → 跨品种稳健")
    elif best_m30['total_pnl'] > 0:
        print(f"  ⚠️ 仅 M30 盈利, GC_M30 略亏或不显著")

    profitable = [r for r in results if r['total_pnl'] > 0]
    print(f"\n  总盈利配置: {len(profitable)}/{len(results)}")
    for r in sorted(profitable, key=lambda x: -x['total_pnl']):
        print(f"     {r['name']:<22} ({r['tf']}): P/L ${r['total_pnl']:+.2f}, 胜率 {r['win_rate']:.1f}%, 盈亏比 {r['profit_factor']:.2f}")

    best_global = max(results, key=lambda r: r['total_pnl'])
    print(f"\n  🏆 全局最优: {best_global['name']}  P/L ${best_global['total_pnl']:+.2f}")
    print()


if __name__ == "__main__":
    main()
