"""
StochBB v5 — 跨周期 (H1 / M30 / M15) 测试
=========================================
v3 策略 (震荡/趋势双模式) 在多个时间周期上跑.

⚠️ 数据限制:
  H1:  2024-01 → 2026-06, 8734 根, 2.5 年 (缺 2025)
  M30: 2026-03-24 → 2026-06-19, 2845 根, 88 天
  M15: 2026-04-24 → 2026-06-16, 3406 根, 53 天

M15/M30 只有 ~1 个季度的数据, 样本太小, 结果仅作参考.

每个 TF 跑 3 个配置:
  - v3 base:  ADX + EMA21 (v3 最优)
  - v3 SMA:   ADX + SMA50
  - v3 relax: B1 (趋势去 KD 限制) + EMA21

总 9 个回测, 全部按 v3 逻辑 (震荡/趋势双模式, SL=1 ATR, BB斜率=0.01)
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
                 relax_trend_entry=False, lot_size=0.01, commission=0.5):
    """v3 策略 + 可选 B1 趋势放宽"""
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
            if is_ranging:
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
            else:
                if (cross_up_counter > 0) and bb_rising and k_rising and (close > ma_val):
                    position = "LONG"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "trending",
                    }
                elif (cross_down_counter > 0) and bb_falling and (not k_rising) and (close < ma_val):
                    position = "SHORT"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "trending",
                    }
                elif relax_trend_entry and (cross_up_counter > 0) and bb_rising and (close > ma_val):
                    position = "LONG"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "trending",
                    }
                elif relax_trend_entry and (cross_down_counter > 0) and bb_falling and (close < ma_val):
                    position = "SHORT"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "trending",
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
                        if cross_down_now and (close < entry_info['ma']):
                            exit_reason = "rng_long_fail"
                        elif cross_down_now and (close >= entry_info['ma']) and (k_curr < 80):
                            aligned = (bb_rising == k_rising)
                            if not aligned:
                                exit_reason = "rng_long_misalign"
                        elif cross_down_now and (close >= entry_info['ma']) and (k_curr >= 80):
                            exit_reason = "rng_long_main"
                    else:
                        if cross_up_now and (close > entry_info['ma']):
                            exit_reason = "rng_short_fail"
                        elif cross_up_now and (close <= entry_info['ma']) and (k_curr > 20):
                            aligned = (bb_rising == k_rising)
                            if not aligned:
                                exit_reason = "rng_short_misalign"
                        elif cross_up_now and (close <= entry_info['ma']) and (k_curr <= 20):
                            exit_reason = "rng_short_main"
                elif regime == "trending":
                    if position == "LONG":
                        if close < entry_info['ma'] - entry_info['atr'] * 1.0:
                            exit_reason = "trend_long_break_ma"
                        elif bb_flat and (cross_down_counter > 0):
                            exit_reason = "trend_long_flat_death"
                    else:
                        if close > entry_info['ma'] + entry_info['atr'] * 1.0:
                            exit_reason = "trend_short_break_ma"
                        elif bb_flat and (cross_up_counter > 0):
                            exit_reason = "trend_short_flat_golden"

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
    print("  StochBB v5 — 跨周期测试 (H1 / M30 / M15)")
    print("=" * 90)
    print("  数据范围:")
    print("    H1:  2024-01-01 → 2026-06-19  (8734 根, 2.5 年, 缺 2025)")
    print("    M30: 2026-03-24 → 2026-06-19  (2845 根, 88 天)")
    print("    M15: 2026-04-24 → 2026-06-16  (3406 根, 53 天)")
    print("  ⚠️ M30/M15 样本太小, 结果仅作参考")
    print()

    timeframes = {
        "H1": load_ohlcv("H1"),
        "M30": load_ohlcv("M30"),
        "M15": load_ohlcv("M15"),
    }

    config_variants = [
        ("base",   {"ma_type": "EMA", "ma_period": 21, "relax_trend_entry": False}),
        ("sma50",  {"ma_type": "SMA", "ma_period": 50, "relax_trend_entry": False}),
        ("relax",  {"ma_type": "EMA", "ma_period": 21, "relax_trend_entry": True}),
    ]

    all_results = []
    for tf, candles in timeframes.items():
        print(f"  📊 {tf}: {len(candles)} 根 K线")
        print(f"  {'配置':<8} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'最大回撤':>10} {'盈亏比':>7} {'震荡':>5} {'趋势':>5} {'L':>4} {'S':>4} {'均K线':>7}")
        for name, variant in config_variants:
            trades = run_backtest(candles, regime_method="ADX", **variant)
            stats = compute_stats(trades)
            stats["tf"] = tf
            stats["variant"] = name
            all_results.append(stats)
            print(f"  {name:<8} {stats['trades']:>5} {stats['wins']:>4} {stats['losses']:>4} "
                  f"{stats['win_rate']:>6.1f}% ${stats['total_pnl']:>+8.2f} ${stats['avg_pnl']:>+6.2f} "
                  f"${stats['max_drawdown']:>8.2f} {stats['profit_factor']:>6.2f} {stats['rng_count']:>5} {stats['trend_count']:>5} {stats['long_count']:>4} {stats['short_count']:>4} {stats['avg_bars']:>7.1f}")
        print()

    # 总体排名
    print("=" * 100)
    print("  总体排名 (按总盈亏降序)")
    print("=" * 100)
    print(f"  {'TF':<5} {'配置':<8} {'交易':>5} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'盈亏比':>7} {'L':>4} {'S':>4} {'均K线':>7}  注意")
    print("  " + "-" * 100)
    for r in sorted(all_results, key=lambda x: -x['total_pnl']):
        note = ""
        if r['tf'] != "H1" and r['trades'] > 0:
            note = "⚠️ 样本小"
        print(f"  {r['tf']:<5} {r['variant']:<8} {r['trades']:>5} {r['win_rate']:>6.1f}% "
              f"${r['total_pnl']:>+8.2f} ${r['avg_pnl']:>+6.2f} {r['profit_factor']:>6.2f} "
              f"{r['long_count']:>4} {r['short_count']:>4} {r['avg_bars']:>7.1f}  {note}")
    print("=" * 100)

    profitable = [r for r in all_results if r['total_pnl'] > 0]
    print()
    if profitable:
        print(f"  🏆 盈利配置数: {len(profitable)}/{len(all_results)}")
        for r in profitable:
            print(f"     {r['tf']} / {r['variant']}: P/L ${r['total_pnl']:+.2f}, 胜率 {r['win_rate']:.1f}%, 盈亏比 {r['profit_factor']:.2f}")
    else:
        print(f"  ❌ 所有 9 个组合仍亏损")
        best = max(all_results, key=lambda r: r['total_pnl'])
        print(f"     最接近盈利: {best['tf']} / {best['variant']} P/L ${best['total_pnl']:+.2f}")
    print()


if __name__ == "__main__":
    main()
