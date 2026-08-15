"""
逆势均值回归 v2 — A vs B, EMA21 vs SMA50
======================================
用户设计:
  - 均价线之上 -> 开空 (逆势)
  - 均价线之下 -> 开多 (逆势)
  - 问题: 长趋势不友好
  - 解决: A=趋势门禁, B=双模式

4 配置: A-EMA21, A-SMA50, B-EMA21, B-SMA50

入场 A (弱趋势逆势):
  LONG:  ADX<0.55 AND close<MA-1.0ATR AND Stoch %K<20
  SHORT: ADX<0.55 AND close>MA+1.0ATR AND Stoch %K>80

入场 B (双模式):
  弱 (ADX<0.55): 逆势 (同 A)
  强 (ADX>=0.55): 顺势 (close>MA -> long, close<MA -> short)

出场 (统一, 固定参数):
  TP: 4 ATR (固定, 简单可预测)
  SL: 2.5 ATR
  Time stop: 48 根 K 线

注: 不用 MA-touch 出场 — MA 移动导致出场位置不可预测
"""
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backtest.mean_reversion_bt import (
    load_h1_data, calc_ema, calc_sma, calc_atr_from_lists,
    calc_stoch, calc_adx_proxy
)


def calc_ma(closes, period, ma_type):
    if ma_type == "EMA":
        return calc_ema(closes, period)
    else:
        return calc_sma(closes, period)


def run_backtest(candles, ma_type, ma_period, strategy_mode,
                 dist_atr=1.0, sl_atr=2.5, tp_atr=4.0, time_stop_bars=48, lot_size=0.01, commission=0.5):
    """单次回测

    Args:
        ma_type: "EMA" or "SMA"
        ma_period: 周期 (21, 50)
        strategy_mode: "A" (弱趋势逆势+ADX门禁) or "B" (双模式)
        dist_atr: 入场要求 |close - MA| > dist_atr * ATR
        sl_atr: 硬止损 ATR 倍数
        tp_atr: 固定止盈 ATR 倍数
        time_stop_bars: 时间止损 (K线数)
    """
    trades = []
    position = None
    entry_price = 0.0
    entry_idx = 0
    entry_ma = 0.0
    entry_atr = 0.0
    n = len(candles)

    for i in range(250, n):
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
        stoch = calc_stoch([highs, lows, closes], 9, 3, 3)
        if stoch is None:
            continue
        k_curr = stoch["curr_k"]

        dist = (close - ma_val) / atr_val

        if position is None:
            if strategy_mode == "A":
                if adx_p >= 0.55:
                    continue
                if dist < -dist_atr and k_curr < 20:
                    position = "LONG"
                    entry_price = close
                    entry_idx = i
                    entry_ma = ma_val
                    entry_atr = atr_val
                elif dist > dist_atr and k_curr > 80:
                    position = "SHORT"
                    entry_price = close
                    entry_idx = i
                    entry_ma = ma_val
                    entry_atr = atr_val
            else:
                if adx_p < 0.55:
                    if dist < -dist_atr and k_curr < 20:
                        position = "LONG"
                        entry_price = close
                        entry_idx = i
                        entry_ma = ma_val
                        entry_atr = atr_val
                    elif dist > dist_atr and k_curr > 80:
                        position = "SHORT"
                        entry_price = close
                        entry_idx = i
                        entry_ma = ma_val
                        entry_atr = atr_val
                else:
                    if close > ma_val:
                        position = "LONG"
                        entry_price = close
                        entry_idx = i
                        entry_ma = ma_val
                        entry_atr = atr_val
                    elif close < ma_val:
                        position = "SHORT"
                        entry_price = close
                        entry_idx = i
                        entry_ma = ma_val
                        entry_atr = atr_val

        else:
            pnl_pts = (close - entry_price) if position == "LONG" else (entry_price - close)

            exit_reason = None
            exit_p = close

            # 1. 固定止盈 (TP)
            if pnl_pts >= entry_atr * tp_atr:
                exit_reason = "take_profit"
                exit_p = entry_price + (entry_atr * tp_atr if position == "LONG" else -entry_atr * tp_atr)

            # 2. 硬止损 (SL)
            if exit_reason is None and pnl_pts < -entry_atr * sl_atr:
                exit_reason = "hard_stop"
                exit_p = entry_price - (entry_atr * sl_atr if position == "LONG" else -entry_atr * sl_atr)

            # 3. 时间止损
            if exit_reason is None and (i - entry_idx) >= time_stop_bars:
                exit_reason = "time_stop"
                exit_p = close

            if exit_reason:
                final_pnl_pts = (exit_p - entry_price) if position == "LONG" else (entry_price - exit_p)
                pnl = final_pnl_pts * 10 * lot_size - commission
                trades.append({
                    "entry_time": candles[entry_idx]['ts_str'],
                    "exit_time": c['ts_str'],
                    "direction": position,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(exit_p, 2),
                    "pnl": round(pnl, 2),
                    "bars": i - entry_idx,
                    "exit_reason": exit_reason,
                    "entry_ma": round(entry_ma, 2),
                    "entry_dist_atr": round((entry_price - entry_ma) / entry_atr, 2),
                })
                position = None

    if position is not None:
        c = candles[-1]
        pnl_pts = (c['close'] - entry_price) if position == "LONG" else (entry_price - c['close'])
        exit_p = c['close']
        if pnl_pts >= entry_atr * tp_atr:
            exit_p = entry_price + (entry_atr * tp_atr if position == "LONG" else -entry_atr * tp_atr)
        elif pnl_pts < -entry_atr * sl_atr:
            exit_p = entry_price - (entry_atr * sl_atr if position == "LONG" else -entry_atr * sl_atr)
        final_pnl_pts = (exit_p - entry_price) if position == "LONG" else (entry_price - exit_p)
        pnl = final_pnl_pts * 10 * lot_size - commission
        trades.append({
            "entry_time": candles[entry_idx]['ts_str'],
            "exit_time": c['ts_str'],
            "direction": position,
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_p, 2),
            "pnl": round(pnl, 2),
            "bars": n - 1 - entry_idx,
            "exit_reason": "end_of_data",
            "entry_ma": round(entry_ma, 2),
            "entry_dist_atr": round((entry_price - entry_ma) / entry_atr, 2),
        })

    return trades


def compute_stats(trades):
    closed = [t for t in trades if t['exit_reason'] != "end_of_data"]
    if not closed:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0,
                "avg_pnl": 0, "max_drawdown": 0, "profit_factor": 0, "avg_bars": 0,
                "tp_count": 0, "sl_count": 0, "time_count": 0, "long_count": 0, "short_count": 0}

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
        "tp_count": sum(1 for t in closed if t['exit_reason'] == "take_profit"),
        "sl_count": sum(1 for t in closed if t['exit_reason'] == "hard_stop"),
        "time_count": sum(1 for t in closed if t['exit_reason'] == "time_stop"),
        "long_count": sum(1 for t in closed if t['direction'] == "LONG"),
        "short_count": sum(1 for t in closed if t['direction'] == "SHORT"),
    }


def main():
    print("=" * 80)
    print("  逆势均值回归 v2 — A vs B, EMA21 vs SMA50")
    print("=" * 80)

    candles = load_h1_data()
    print(f"  数据: {len(candles)} 根 H1 K线")
    print(f"  参数: dist=1.0σ, SL=2.5 ATR, TP=4 ATR, time=48 根")
    print(f"  A=ADX<0.55 门禁(仅逆势), B=双模式(弱逆+强顺)\n")

    configs = [
        ("A-EMA21", "EMA", 21, "A"),
        ("A-SMA50", "SMA", 50, "A"),
        ("B-EMA21", "EMA", 21, "B"),
        ("B-SMA50", "SMA", 50, "B"),
    ]

    all_trades = {}
    results = []
    for name, ma_type, ma_period, mode in configs:
        print(f"  跑 {name} ({ma_type}{ma_period}, {mode})...", end="", flush=True)
        trades = run_backtest(candles, ma_type, ma_period, mode)
        stats = compute_stats(trades)
        stats["name"] = name
        results.append(stats)
        all_trades[name] = trades
        print(f" 完成 ({stats['trades']} 笔, 胜率 {stats['win_rate']:.1f}%, P/L ${stats['total_pnl']:+.2f})")

    print("\n" + "=" * 115)
    print("  对比表 (出场: TP=触MA, SL=硬止损, TIME=时间止损)")
    print("=" * 115)
    print(f"  {'配置':<10} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'最大回撤':>10} {'盈亏比':>7} {'TP':>4} {'SL':>4} {'TIME':>5} {'L':>4} {'S':>4} {'均K线':>7}")
    print("  " + "-" * 115)
    for r in results:
        print(f"  {r['name']:<10} {r['trades']:>5} {r['wins']:>4} {r['losses']:>4} "
              f"{r['win_rate']:>6.1f}% ${r['total_pnl']:>+8.2f} ${r['avg_pnl']:>+6.2f} "
              f"${r['max_drawdown']:>8.2f} {r['profit_factor']:>6.2f} {r['tp_count']:>4} {r['sl_count']:>4} {r['time_count']:>5} {r['long_count']:>4} {r['short_count']:>4} {r['avg_bars']:>7.1f}")
    print("=" * 115)

    print("\n" + "=" * 80)
    print("  方向 × 出场 交叉分析")
    print("=" * 80)
    for name, trades in all_trades.items():
        closed = [t for t in trades if t['exit_reason'] != 'end_of_data']
        if not closed:
            continue
        cross = defaultdict(list)
        for t in closed:
            cross[(t['direction'], t['exit_reason'])].append(t)
        print(f"\n  {name}:")
        print(f"  {'方向':<8} {'出场':<14} {'笔数':>5} {'胜率':>7} {'总盈亏':>10} {'均单':>8}")
        print("  " + "-" * 55)
        for (d, r), ts in sorted(cross.items()):
            wins = sum(1 for t in ts if t['pnl'] > 0)
            wr = wins / len(ts) * 100 if ts else 0
            pnl = sum(t['pnl'] for t in ts)
            avg = pnl / len(ts)
            print(f"  {d:<8} {r:<14} {len(ts):>5} {wr:>6.1f}% ${pnl:>+8.2f} ${avg:>+6.2f}")

    print("\n" + "=" * 80)
    print("  月度分析 (找亏损集中月)")
    print("=" * 80)
    for name, trades in all_trades.items():
        closed = [t for t in trades if t['exit_reason'] != 'end_of_data']
        if not closed:
            continue
        by_month = defaultdict(list)
        for t in closed:
            month = t['entry_time'][:7]
            by_month[month].append(t)
        worst = sorted([(m, sum(t['pnl'] for t in ts), len(ts)) for m, ts in by_month.items()], key=lambda x: x[1])[:3]
        best = sorted([(m, sum(t['pnl'] for t in ts), len(ts)) for m, ts in by_month.items()], key=lambda x: -x[1])[:3]
        print(f"\n  {name}:")
        print(f"    最差 3 月: {[(m, f'${p:+.2f}', f'{n}笔') for m, p, n in worst]}")
        print(f"    最佳 3 月: {[(m, f'${p:+.2f}', f'{n}笔') for m, p, n in best]}")

    print("\n" + "=" * 80)
    print("  决策建议")
    print("=" * 80)
    best = max(results, key=lambda r: r['total_pnl'])
    print(f"  最优: {best['name']}  P/L ${best['total_pnl']:+.2f}  胜率 {best['win_rate']:.1f}%  盈亏比 {best['profit_factor']:.2f}")

    if best['total_pnl'] > 0:
        print(f"  转亏为盈! 建议先用 {best['name']} 小仓位试运行")
    else:
        print(f"  仍亏损, 需进一步调整入场距离 (1.5σ) 或加更多过滤")

    profitable = [r for r in results if r['total_pnl'] > 0]
    if profitable:
        print(f"\n  盈利配置: {[r['name'] for r in profitable]}")
    else:
        print(f"\n  所有配置仍亏损")
    print()


if __name__ == "__main__":
    main()
