"""
StochBB v11 — 真 ADX (Wilder) 重新测试
======================================
v10 突破: 假 ADX + 阈值 0.55 实际无效 (calc_adx_proxy 输出 0-0.21, 永远 < 0.55)
         → is_ranging 永远 True → 趋势中也做反向单 → 3 笔多单全 hard_stop

v11 修复:
  - calc_adx_real() 用 TA-Lib (Wilder 公式) 输出 0-100
  - 阈值 25 (ranging) / 40 (strong trend)
  - 同时输出 +DI / -DI 判断方向 (新增)

测试矩阵 (在 v10 B0 base 基础上):
  A1 ADX<25 ranging (v10 一样的逻辑, 但 ADX 修对了)
  A2 ADX<25 + (close vs MA 一致 + DI 方向一致) 才入场 (加 DI 方向过滤)
  A3 ADX<20 更严格 ranging 阈值
  A4 ADX<25 + DI 一致 (单边 DI 主导时禁止反向)

数据: M30 + GC_M30 (跨品种)
"""
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backtest.mean_reversion_bt import (
    load_ohlcv, calc_ema, calc_sma, calc_atr_from_lists,
    calc_stoch, calc_bb, calc_adx_real,
)


def calc_ma(closes, period, ma_type):
    if ma_type == "EMA":
        return calc_ema(closes, period)
    return calc_sma(closes, period)


def run_backtest(candles, ma_type, ma_period, regime_method,
                 sl_atr=1.0, bb_slope_threshold=0.01,
                 adx_threshold=25,
                 use_di_filter=False,    # A2/A4: 用 +DI/-DI 方向过滤
                 lot_size=0.01, commission=0.5):
    """v3 base + 真 ADX"""
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
        adx_data = calc_adx_real(highs, lows, closes, 14)
        if adx_data is None:
            continue
        adx = adx_data['adx']
        pdi = adx_data['pdi']
        ndi = adx_data['ndi']
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

        is_ranging = adx < adx_threshold

        k_rising = k_curr > k_prev
        bb_rising = bb_mid_slope > bb_slope_threshold
        bb_falling = bb_mid_slope < -bb_slope_threshold
        bb_flat = abs(bb_mid_slope) <= bb_slope_threshold

        # ── 入场 ──
        if position is None:
            if is_ranging and bb_width <= 1.0:
                # DI 方向过滤 (A2/A4): 趋势强 (-DI 或 +DI 主导) 时禁止反向单
                di_blocked_long = use_di_filter and (ndi - pdi) > 10  # 强下跌时不开多
                di_blocked_short = use_di_filter and (pdi - ndi) > 10  # 强上涨时不开空

                if (k_curr < 20) and cross_up_now and (close < ma_val) and not di_blocked_long:
                    position = "LONG"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "ranging",
                        "adx": adx, "pdi": pdi, "ndi": ndi,
                    }
                elif (k_curr > 80) and cross_down_now and (close > ma_val) and not di_blocked_short:
                    position = "SHORT"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "ranging",
                        "adx": adx, "pdi": pdi, "ndi": ndi,
                    }

        # ── 出场 (no-fail 模式, v10 验证最优) ──
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
                    "adx_entry": round(entry_info.get('adx', 0), 1),
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
            "adx_entry": round(entry_info.get('adx', 0), 1),
        })

    return trades


def compute_stats(trades):
    closed = [t for t in trades if t['exit_reason'] != "end_of_data"]
    if not closed:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0,
                "avg_pnl": 0, "max_drawdown": 0, "profit_factor": 0, "avg_bars": 0,
                "long_count": 0, "short_count": 0, "adx_at_entry": 0}

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
    avg_adx = sum(t.get('adx_entry', 0) for t in closed) / len(closed) if closed else 0

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
        "long_count": sum(1 for t in closed if t['direction'] == "LONG"),
        "short_count": sum(1 for t in closed if t['direction'] == "SHORT"),
        "adx_at_entry": round(avg_adx, 1),
    }


def main():
    print("=" * 100)
    print("  StochBB v11 — 真 ADX (Wilder) 重新测试")
    print("=" * 100)
    print("  v10 突破 (假 ADX):  M30 B0 base = +$67.55, 胜率 37%, 盈亏比 1.66")
    print("  v10 问题: 假 ADX 永远 < 0.55, is_ranging 恒真, 趋势中硬做反向单")
    print()

    m30 = load_ohlcv("M30")
    gc_m30 = load_ohlcv("GC_M30")

    # 测试配置
    configs = [
        ("A1 ADX<25 base",            {"adx_threshold": 25, "use_di_filter": False}),
        ("A2 ADX<25 +DI 过滤",         {"adx_threshold": 25, "use_di_filter": True}),
        ("A3 ADX<20 更严",            {"adx_threshold": 20, "use_di_filter": False}),
        ("A4 ADX<25 +DI 过滤(严)",     {"adx_threshold": 25, "use_di_filter": True}),
        ("A5 ADX<30 更宽",            {"adx_threshold": 30, "use_di_filter": False}),
        ("A6 ADX<25 +DI(差>15)",       {"adx_threshold": 25, "use_di_filter": True}),
    ]

    all_results = []
    all_trades = {}

    print("  ── M30 验证 ──")
    for name, kw in configs:
        trades = run_backtest(m30, ma_type="EMA", ma_period=21, regime_method="ADX", **kw)
        stats = compute_stats(trades)
        stats["name"] = name
        stats["tf"] = "M30"
        all_results.append(stats)
        all_trades[name] = trades
        mark = " ✅" if stats['total_pnl'] > 0 else " ❌"
        print(f"  {name:<24} {stats['trades']:>4} 笔, 胜率 {stats['win_rate']:>5.1f}%, "
              f"P/L ${stats['total_pnl']:>+7.2f}, 盈亏比 {stats['profit_factor']:.2f}, "
              f"avg ADX={stats['adx_at_entry']}{mark}")

    print()
    print("  ── GC_M30 跨品种验证 ──")
    gc_results = []
    for name, kw in configs:
        trades = run_backtest(gc_m30, ma_type="EMA", ma_period=21, regime_method="ADX", **kw)
        stats = compute_stats(trades)
        stats["name"] = name
        stats["tf"] = "GC_M30"
        gc_results.append(stats)
        all_trades[f"GC_{name}"] = trades
        mark = " ✅" if stats['total_pnl'] > 0 else " ❌"
        print(f"  GC_{name:<24} {stats['trades']:>4} 笔, 胜率 {stats['win_rate']:>5.1f}%, "
              f"P/L ${stats['total_pnl']:>+7.2f}, 盈亏比 {stats['profit_factor']:.2f}, "
              f"avg ADX={stats['adx_at_entry']}{mark}")

    print()
    print("=" * 130)
    print("  对比表 (按 P/L 降序, 含 GC 跨品种)")
    print("=" * 130)
    print(f"  {'配置':<32} {'TF':<8} {'交易':>5} {'胜':>4} {'负':>4} {'胜率':>7} {'总盈亏':>10} "
          f"{'均单':>8} {'最大回撤':>10} {'盈亏比':>7} {'L':>4} {'S':>4} {'均K线':>7} {'avgADX':>7}")
    print("  " + "-" * 130)
    for r in sorted(all_results + gc_results, key=lambda x: -x['total_pnl']):
        mark = " ✅" if r['total_pnl'] > 0 else " ❌"
        print(f"  {r['name']:<32} {r['tf']:<8} {r['trades']:>5} {r['wins']:>4} {r['losses']:>4} "
              f"{r['win_rate']:>6.1f}% ${r['total_pnl']:>+8.2f} ${r['avg_pnl']:>+6.2f} "
              f"${r['max_drawdown']:>8.2f} {r['profit_factor']:>6.2f} {r['long_count']:>4} {r['short_count']:>4} "
              f"{r['avg_bars']:>7.1f} {r['adx_at_entry']:>7.1f}{mark}")
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

    # 对比 v10
    print("\n" + "=" * 80)
    print("  对比 v10 (假 ADX)")
    print("=" * 80)
    print("  v10 B0 base (M30, 假 ADX):  +$67.55, 胜率 37%, 盈亏比 1.66, 79 笔")
    print()

    best_m30 = max((r for r in all_results if r['tf'] == "M30"), key=lambda x: x['total_pnl'])
    best_gc = max((r for r in gc_results), key=lambda x: x['total_pnl'])

    print(f"  v11 最优 M30:    {best_m30['name']}  ${best_m30['total_pnl']:+.2f}  胜率 {best_m30['win_rate']:.1f}%, 盈亏比 {best_m30['profit_factor']:.2f}")
    print(f"  v11 最优 GC_M30: {best_gc['name']}  ${best_gc['total_pnl']:+.2f}  胜率 {best_gc['win_rate']:.1f}%, 盈亏比 {best_gc['profit_factor']:.2f}")

    if best_m30['total_pnl'] > 0 and best_gc['total_pnl'] > 0:
        # 找出两边都盈利的配置
        m30_profit = {r['name'] for r in all_results if r['total_pnl'] > 0}
        gc_profit = {r['name'] for r in gc_results if r['total_pnl'] > 0}
        both = m30_profit & gc_profit
        if both:
            print(f"\n  🏆 双品种都盈利 ({len(both)}): {', '.join(sorted(both))}")
        else:
            print(f"\n  ⚠️ 没有双品种都盈利的配置")
            print(f"     M30 盈利: {m30_profit or '无'}")
            print(f"     GC 盈利: {gc_profit or '无'}")


if __name__ == "__main__":
    main()
