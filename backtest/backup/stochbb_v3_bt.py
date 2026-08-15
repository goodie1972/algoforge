"""
StochBB v3 — 震荡/趋势双模式策略
==================================
用户设计 2026-06-18:

震荡市 (逆势):
  LONG: Stoch 超卖 + 金叉 + close < MA
  SHORT: Stoch 超买 + 死叉 + close > MA
  LONG 出场: 死叉+close<MA=失败出; 死叉+过MA+非超买+BB≠KD=出; 死叉+过MA+超买=出; 死叉+过MA+非超买+BB=KD=持
  SHORT 出场 (镜像)

趋势市 (顺势):
  LONG: 3根K内有金叉 + BB中线↑ + KD↑ + close > MA
  SHORT: 3根K内有死叉 + BB中线↓ + KD↓ + close < MA
  LONG 出场: 跌破MA-1ATR=出; BB中线走平+3根K内死叉=出
  SHORT 出场 (镜像)

统一: SL = 1 ATR
震荡/趋势判定: ADX<0.55 vs ADX+BB (BB width<0.04)
MA: EMA21 vs SMA50
BB斜率阈值: 0.01 (绝对值)
KD方向: 当前>前值=上升

4 配置: ADX-EMA21, ADX-SMA50, ADX+BB-EMA21, ADX+BB-SMA50
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
                 sl_atr=1.0, bb_slope_threshold=0.01, lot_size=0.01, commission=0.5):
    """单次回测"""
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

        # MA
        ma_val = calc_ma(closes, ma_period, ma_type)
        if ma_val is None:
            continue

        # ATR
        atr_val = calc_atr_from_lists(highs, lows, closes, 20)
        if atr_val is None or atr_val <= 0:
            continue

        # ADX
        adx_p = calc_adx_proxy(highs, lows, 14) or 0

        # BB
        bb = calc_bb(closes, 20, 2.5)
        if bb is None:
            continue
        bb_width = bb["width"]
        bb_mid = bb["sma"]

        # BB 中线斜率 (当前 - 前一根)
        if i >= 1:
            closes_prev_bar = [x['close'] for x in candles[:i]]
            if len(closes_prev_bar) >= 20:
                sma20_prev = sum(closes_prev_bar[-20:]) / 20
                bb_mid_slope = bb_mid - sma20_prev
            else:
                bb_mid_slope = 0
        else:
            bb_mid_slope = 0

        # Stoch
        stoch = calc_stoch([highs, lows, closes], 9, 3, 3)
        if stoch is None:
            continue
        k_curr = stoch["curr_k"]
        k_prev = stoch["prev_k"]
        d_curr = stoch["curr_d"]
        d_prev = stoch["prev_d"]

        # 金叉/死叉检测 (当前 bar)
        cross_up_now = (k_curr > d_curr) and (k_prev <= d_prev)
        cross_down_now = (k_curr < d_curr) and (k_prev >= d_prev)

        # 3 根 K 窗口计数器
        if cross_up_now:
            cross_up_counter = 3
        if cross_down_now:
            cross_down_counter = 3
        if cross_up_counter > 0:
            cross_up_counter -= 1
        if cross_down_counter > 0:
            cross_down_counter -= 1

        # Regime 判定
        if regime_method == "ADX":
            is_ranging = adx_p < 0.55
        else:  # ADX+BB
            is_ranging = (adx_p < 0.55) and (bb_width < 0.04)

        # K 方向 (当前 > 前 = 上升)
        k_rising = k_curr > k_prev

        # BB 中线方向
        bb_rising = bb_mid_slope > bb_slope_threshold
        bb_falling = bb_mid_slope < -bb_slope_threshold
        bb_flat = abs(bb_mid_slope) <= bb_slope_threshold

        # ── 入场 ──
        if position is None:
            if is_ranging:
                # 震荡 LONG: 超卖 + 金叉 + 均线下方
                if (k_curr < 20) and cross_up_now and (close < ma_val):
                    position = "LONG"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "ranging",
                    }
                # 震荡 SHORT: 超买 + 死叉 + 均线上方
                elif (k_curr > 80) and cross_down_now and (close > ma_val):
                    position = "SHORT"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "ranging",
                    }
            else:  # trending
                # 趋势 LONG: 3根K内金叉 + BB中线↑ + KD↑ + 均线上
                if (cross_up_counter > 0) and bb_rising and k_rising and (close > ma_val):
                    position = "LONG"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "trending",
                    }
                # 趋势 SHORT: 3根K内死叉 + BB中线↓ + KD↓ + 均线下方
                elif (cross_down_counter > 0) and bb_falling and (not k_rising) and (close < ma_val):
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

            # 1. SL 1 ATR
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
                        # 死叉 + 价格没过均线 → 走人 (失败)
                        if cross_down_now and (close < entry_info['ma']):
                            exit_reason = "rng_long_fail"
                        # 死叉 + 过均线 + 非超买 + BB中线≠KD → 走人
                        elif cross_down_now and (close >= entry_info['ma']) and (k_curr < 80):
                            aligned = (bb_rising == k_rising)
                            if not aligned:
                                exit_reason = "rng_long_misalign"
                        # 死叉 + 过均线 + 超买区 → 走人 (主出场)
                        elif cross_down_now and (close >= entry_info['ma']) and (k_curr >= 80):
                            exit_reason = "rng_long_main"
                    else:  # SHORT
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
                        # 跌破 MA - 1 ATR → 走人
                        if close < entry_info['ma'] - entry_info['atr'] * 1.0:
                            exit_reason = "trend_long_break_ma"
                        # BB中线走平 + 3根K内死叉 → 走人
                        elif bb_flat and (cross_down_counter > 0):
                            exit_reason = "trend_long_flat_death"
                    else:  # SHORT
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
                    "ma": round(entry_info['ma'], 2),
                    "entry_dist_atr": round((entry_info['price'] - entry_info['ma']) / entry_info['atr'], 2),
                })
                position = None

    # 最后一笔
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
            "ma": round(entry_info['ma'], 2),
            "entry_dist_atr": round((entry_info['price'] - entry_info['ma']) / entry_info['atr'], 2),
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
    print("=" * 80)
    print("  StochBB v3 — 震荡/趋势双模式策略 (用户设计)")
    print("=" * 80)

    candles = load_h1_data()
    print(f"  数据: {len(candles)} 根 H1 K线")
    print(f"  参数: SL=1 ATR, BB斜率阈值=0.01, Stoch(9,3,3)")
    print()

    configs = [
        ("ADX-EMA21",   "ADX",   "EMA", 21),
        ("ADX-SMA50",   "ADX",   "SMA", 50),
        ("ADX+BB-EMA21", "ADX+BB", "EMA", 21),
        ("ADX+BB-SMA50", "ADX+BB", "SMA", 50),
    ]

    all_trades = {}
    results = []
    for name, regime, ma_type, ma_period in configs:
        print(f"  跑 {name} ({regime}, {ma_type}{ma_period})...", end="", flush=True)
        trades = run_backtest(candles, ma_type, ma_period, regime)
        stats = compute_stats(trades)
        stats["name"] = name
        results.append(stats)
        all_trades[name] = trades
        print(f" 完成 ({stats['trades']} 笔, 胜率 {stats['win_rate']:.1f}%, P/L ${stats['total_pnl']:+.2f})")

    print("\n" + "=" * 115)
    print("  对比表")
    print("=" * 115)
    print(f"  {'配置':<14} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} {'均单':>8} {'最大回撤':>10} {'盈亏比':>7} {'震荡':>5} {'趋势':>5} {'L':>4} {'S':>4} {'均K线':>7}")
    print("  " + "-" * 115)
    for r in results:
        print(f"  {r['name']:<14} {r['trades']:>5} {r['wins']:>4} {r['losses']:>4} "
              f"{r['win_rate']:>6.1f}% ${r['total_pnl']:>+8.2f} ${r['avg_pnl']:>+6.2f} "
              f"${r['max_drawdown']:>8.2f} {r['profit_factor']:>6.2f} {r['rng_count']:>5} {r['trend_count']:>5} {r['long_count']:>4} {r['short_count']:>4} {r['avg_bars']:>7.1f}")
    print("=" * 115)

    print("\n" + "=" * 80)
    print("  按 regime 拆分 (震荡 vs 趋势 各自表现)")
    print("=" * 80)
    for name, trades in all_trades.items():
        closed = [t for t in trades if t['exit_reason'] != 'end_of_data']
        if not closed:
            continue
        by_regime = defaultdict(list)
        for t in closed:
            by_regime[t['regime']].append(t)
        print(f"\n  {name}:")
        for regime in ['ranging', 'trending']:
            if regime not in by_regime:
                continue
            ts = by_regime[regime]
            wins = sum(1 for t in ts if t['pnl'] > 0)
            wr = wins / len(ts) * 100
            pnl = sum(t['pnl'] for t in ts)
            avg = pnl / len(ts)
            avg_bars = sum(t['bars'] for t in ts) / len(ts)
            print(f"    {regime:<10}: {len(ts):>4} 笔, 胜率 {wr:.1f}%, P/L ${pnl:+.2f}, 均单 ${avg:+.2f}, 均K线 {avg_bars:.1f}")

    print("\n" + "=" * 80)
    print("  按出场原因拆分")
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

    print("\n" + "=" * 80)
    print("  决策建议")
    print("=" * 80)
    best = max(results, key=lambda r: r['total_pnl'])
    print(f"  最优: {best['name']}  P/L ${best['total_pnl']:+.2f}  胜率 {best['win_rate']:.1f}%  盈亏比 {best['profit_factor']:.2f}")

    profitable = [r for r in results if r['total_pnl'] > 0]
    if profitable:
        print(f"  盈利配置: {[r['name'] for r in profitable]}")
    else:
        print(f"  所有配置仍亏损")
    print()


if __name__ == "__main__":
    main()
