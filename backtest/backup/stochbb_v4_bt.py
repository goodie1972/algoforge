"""
StochBB v4 — 多种参数组合并行测试
==============================
基线: stochbb_v3 (震荡/趋势双模式)

A 类 - SL/止损变种
  A1: SL=1.5 ATR
  A2: SL=2.0 ATR
  A3: 无硬止损
  A4: 趋势 SL=2.5, 震荡 SL=1.0

B 类 - 入场过滤放宽
  B1: 趋势去 KD 方向限制
  B2: 趋势只要 BB+价格 vs MA (去掉 cross + KD)
  B3: 震荡 K 阈值放宽 20/80 → 30/70

C 类 - 趋势强化
  C1: BB 斜率阈值 0.005 (更敏感)
  C2: 趋势加 TP=3 ATR

默认: ADX regime + EMA21 (表现最优基线)
"""
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backtest.mean_reversion_bt import (
    load_h1_data, calc_ema, calc_sma, calc_atr_from_lists,
    calc_stoch, calc_adx_proxy, calc_bb
)


def calc_ma(closes, period, ma_type):
    if ma_type == "EMA":
        return calc_ema(closes, period)
    return calc_sma(closes, period)


def run_backtest(candles, ma_type, ma_period, regime_method,
                 sl_atr=1.0, bb_slope_threshold=0.01,
                 trend_tp_atr=None,           # 趋势模式 TP ATR (None=无 TP)
                 use_hard_stop=True,           # 是否使用硬止损
                 relax_trend_entry=False,      # B1: 趋势去 KD 限制
                 relax_trend_entry_2=False,    # B2: 趋势去 cross+KD
                 relax_range_kn=20,            # B3: 震荡 K 阈值 (20/80)
                 lot_size=0.01, commission=0.5):
    """v4: 多种参数组合"""
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
                if (k_curr < relax_range_kn) and cross_up_now and (close < ma_val):
                    position = "LONG"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "ranging",
                    }
                elif (k_curr > (100 - relax_range_kn)) and cross_down_now and (close > ma_val):
                    position = "SHORT"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "ranging",
                    }
            else:  # trending
                # 完整入场: cross + bb + kd + 价格
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
                # B1: 趋势去 KD 限制
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
                # B2: 趋势只要 BB + 价格 vs MA
                elif relax_trend_entry_2 and bb_rising and (close > ma_val):
                    position = "LONG"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "trending",
                    }
                elif relax_trend_entry_2 and bb_falling and (close < ma_val):
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

            # 1. SL (可选)
            if use_hard_stop and pnl_pts < -entry_info['atr'] * sl_atr:
                exit_reason = "hard_stop"
                if position == "LONG":
                    exit_p = entry_info['price'] - entry_info['atr'] * sl_atr
                else:
                    exit_p = entry_info['price'] + entry_info['atr'] * sl_atr

            # 2. 趋势 TP (C2)
            if exit_reason is None and trend_tp_atr is not None and entry_info['regime'] == "trending":
                if pnl_pts >= entry_info['atr'] * trend_tp_atr:
                    exit_reason = "trend_tp"
                    if position == "LONG":
                        exit_p = entry_info['price'] + entry_info['atr'] * trend_tp_atr
                    else:
                        exit_p = entry_info['price'] - entry_info['atr'] * trend_tp_atr

            # 3. 模式特定出场
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
        pnl_pts = (close - entry_info['price']) if position == "LONG" else (entry_info['price'] - close)
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
                "rng_count": 0, "trend_count": 0, "long_count": 0, "short_count": 0,
                "hard_stop_count": 0, "fail_count": 0, "main_count": 0}

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

    hard_stop_count = sum(1 for t in closed if t['exit_reason'] == "hard_stop")
    fail_count = sum(1 for t in closed if 'fail' in t['exit_reason'])
    main_count = sum(1 for t in closed if 'main' in t['exit_reason'])

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
        "hard_stop_count": hard_stop_count,
        "fail_count": fail_count,
        "main_count": main_count,
    }


def main():
    print("=" * 80)
    print("  StochBB v4 — 多种参数组合并行测试")
    print("=" * 80)

    candles = load_h1_data()
    print(f"  数据: {len(candles)} 根 H1 K线\n")

    # 默认基线: ADX + EMA21 (v3 最优)
    base_kwargs = dict(
        candles=candles, ma_type="EMA", ma_period=21, regime_method="ADX",
        bb_slope_threshold=0.01, lot_size=0.01, commission=0.5,
    )

    configs = [
        # A 类 - SL 变种
        ("A1: SL=1.5 ATR",        {**base_kwargs, "sl_atr": 1.5, "use_hard_stop": True}),
        ("A2: SL=2.0 ATR",        {**base_kwargs, "sl_atr": 2.0, "use_hard_stop": True}),
        ("A3: 无硬止损 (纯逻辑)",  {**base_kwargs, "sl_atr": 1.0, "use_hard_stop": False}),
        # B 类 - 入场放宽
        ("B1: 趋势去 KD 限制",    {**base_kwargs, "sl_atr": 1.0, "use_hard_stop": True, "relax_trend_entry": True}),
        ("B2: 趋势仅 BB+价格",    {**base_kwargs, "sl_atr": 1.0, "use_hard_stop": True, "relax_trend_entry_2": True}),
        ("B3: 震荡 K 30/70",      {**base_kwargs, "sl_atr": 1.0, "use_hard_stop": True, "relax_range_kn": 30}),
        # C 类 - 趋势强化
        ("C1: BB 斜率 0.005",     {**base_kwargs, "sl_atr": 1.0, "use_hard_stop": True, "bb_slope_threshold": 0.005}),
        ("C2: 趋势 TP=3 ATR",     {**base_kwargs, "sl_atr": 1.0, "use_hard_stop": True, "trend_tp_atr": 3.0}),
    ]

    results = []
    all_trades = {}
    for name, kw in configs:
        print(f"  跑 {name}...", end="", flush=True)
        trades = run_backtest(**kw)
        stats = compute_stats(trades)
        stats["name"] = name
        results.append(stats)
        all_trades[name] = trades
        print(f" {stats['trades']} 笔, 胜率 {stats['win_rate']:.1f}%, P/L ${stats['total_pnl']:+.2f}, "
              f"hard_stop {stats['hard_stop_count']}, fail {stats['fail_count']}, main {stats['main_count']}")

    print("\n" + "=" * 130)
    print("  对比表 (基线: ADX + EMA21)")
    print("=" * 130)
    print(f"  {'配置':<25} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'最大回撤':>10} {'盈亏比':>7} {'震荡':>5} {'趋势':>5} {'L':>4} {'S':>4} {'均K线':>7}")
    print("  " + "-" * 130)
    # 按总盈亏降序
    for r in sorted(results, key=lambda x: -x['total_pnl']):
        print(f"  {r['name']:<25} {r['trades']:>5} {r['wins']:>4} {r['losses']:>4} "
              f"{r['win_rate']:>6.1f}% ${r['total_pnl']:>+8.2f} ${r['avg_pnl']:>+6.2f} "
              f"${r['max_drawdown']:>8.2f} {r['profit_factor']:>6.2f} {r['rng_count']:>5} {r['trend_count']:>5} {r['long_count']:>4} {r['short_count']:>4} {r['avg_bars']:>7.1f}")
    print("=" * 130)

    # 出场原因分析 (每个配置)
    print("\n" + "=" * 80)
    print("  出场原因分布 (按配置)")
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

    # 决策建议
    print("\n" + "=" * 80)
    print("  决策建议")
    print("=" * 80)
    profitable = [r for r in results if r['total_pnl'] > 0]
    if profitable:
        best = max(results, key=lambda r: r['total_pnl'])
        print(f"  🏆 最优: {best['name']}  P/L ${best['total_pnl']:+.2f}  胜率 {best['win_rate']:.1f}%  盈亏比 {best['profit_factor']:.2f}")
        print(f"  盈利配置数: {len(profitable)}/{len(results)}")
    else:
        # 找最接近盈利的
        best = max(results, key=lambda r: r['total_pnl'])
        print(f"  仍无盈利配置")
        print(f"  最接近盈利: {best['name']}  P/L ${best['total_pnl']:+.2f}  胜率 {best['win_rate']:.1f}%  盈亏比 {best['profit_factor']:.2f}")
        print(f"  排名:")
        for i, r in enumerate(sorted(results, key=lambda x: -x['total_pnl']), 1):
            print(f"    {i}. {r['name']:<25} P/L ${r['total_pnl']:+.2f}")
    print()


if __name__ == "__main__":
    main()
