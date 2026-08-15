"""
v13 双模 — 在 v11 A5 (已验证盈利的震荡逻辑) 之上加趋势层
==========================================================
v12 失败教训:
  - 重写出场逻辑 (BB 中轨/RSI 反向) 太激进, 让原本盈利的震荡部分变亏
  - v11 A5 已经在 M30 +$39.71 / GC_M30 +$34.84 双品种盈利
  - 应该保留 v11 A5 的入场+出场, 只在 ADX>=阈值时增加趋势单选项

v13 设计:
  ADX < 30 → v11 A5 原始震荡逻辑 (Stoch 9-3-3 交叉 + EMA21 + BB)
  ADX >= 30 + DI 主导 + EMA21 一致 → 趋势单 (顺势)
  注: 趋势单出场用宽 SL (1.5 ATR) + ADX 衰减出 + DI 反转出

测试矩阵:
  T0  v11 A5 重现 (基线)                      ADX<30, 纯震荡
  T1  T0 + ADX>=30 趋势 LONG                ADX 强 + +DI 主导 + 收 EMA21 上 → 多
  T2  T0 + ADX>=30 趋势 SHORT               ADX 强 + -DI 主导 + 收 EMA21 下 → 空
  T3  T0 + 双向趋势                         T1 + T2
  T4  T3 + 趋势 SL=1.5                       SL 放宽
  T5  T3 + 趋势 SL=2.0 + TP=2.5              更长跟随
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


def run_backtest(candles,
                 ma_period=21,
                 sl_atr=1.0,
                 bb_slope_threshold=0.01,
                 adx_range_threshold=30,
                 # 趋势开关
                 enable_trend_long=False,
                 enable_trend_short=False,
                 adx_trend_threshold=30,
                 di_threshold=10,
                 trend_sl_atr=1.5,
                 trend_tp_atr=2.5,
                 # 震荡硬止盈 (用户建议: 震荡才需要止盈保住果实)
                 range_tp_atr=0,
                 # 趋势 EMA 止盈 — 收破 EMA21 即出
                 trend_exit_ema=False,
                 # 趋势移动止盈 — 从最高点回撤 N 倍 ATR 出
                 trend_trail_atr=0,
                 # 趋势 BB 中轨止盈 — 收破 BB 中轨(SMA20)即出
                 trend_exit_bb=False,
                 lot_size=0.01, commission=0.5):
    """v11 A5 + 可选趋势叠加 (v2: 交换止盈逻辑 — 震荡加硬止盈, 趋势去掉硬止盈)"""
    trades = []
    position = None
    entry_info = {}

    n = len(candles)

    for i in range(251, n):
        c = candles[i]
        sub = candles[:i + 1]
        closes = [x['close'] for x in sub]
        highs = [x['high'] for x in sub]
        lows = [x['low'] for x in sub]
        close = closes[-1]

        ma_val = calc_ema(closes, ma_period)
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

        is_ranging = adx < adx_range_threshold
        k_rising = k_curr > k_prev
        bb_rising = bb_mid_slope > bb_slope_threshold

        # ── 入场 ──
        if position is None:
            # ── 震荡模式 (v11 A5 原版) ──
            if is_ranging and bb_width <= 1.0:
                if (k_curr < 20) and cross_up_now and (close < ma_val):
                    position = "LONG"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "range",
                        "adx": adx, "sl_atr": sl_atr, "tp_atr": None,
                    }
                elif (k_curr > 80) and cross_down_now and (close > ma_val):
                    position = "SHORT"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "range",
                        "adx": adx, "sl_atr": sl_atr, "tp_atr": None,
                    }

            # ── 趋势模式 (新加) ──
            elif (not is_ranging) and adx >= adx_trend_threshold:
                if enable_trend_long and (pdi - ndi) > di_threshold and close > ma_val and cross_up_now:
                    position = "LONG"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "trend",
                        "adx": adx, "sl_atr": trend_sl_atr, "tp_atr": trend_tp_atr,
                    }
                elif enable_trend_short and (ndi - pdi) > di_threshold and close < ma_val and cross_down_now:
                    position = "SHORT"
                    entry_info = {
                        "time": c['ts_str'], "price": close, "idx": i,
                        "ma": ma_val, "atr": atr_val, "regime": "trend",
                        "adx": adx, "sl_atr": trend_sl_atr, "tp_atr": trend_tp_atr,
                    }

        # ── 出场 ──
        else:
            pnl_pts = (close - entry_info['price']) if position == "LONG" else (entry_info['price'] - close)
            exit_reason = None
            exit_p = close

            sl_dist = entry_info['atr'] * entry_info['sl_atr']
            if pnl_pts < -sl_dist:
                exit_reason = "hard_stop"
                if position == "LONG":
                    exit_p = entry_info['price'] - sl_dist
                else:
                    exit_p = entry_info['price'] + sl_dist

            # 趋势模式: 更新最高/最低追踪
            if entry_info['regime'] == "trend":
                if position == "LONG":
                    entry_info['peak'] = max(entry_info.get('peak', entry_info['price']), c['high'])
                else:
                    entry_info['peak'] = min(entry_info.get('peak', entry_info['price']), c['low'])

            if entry_info['regime'] == "range" and exit_reason is None:
                # 震荡硬止盈: 到手就走, 防被振出去
                if range_tp_atr > 0:
                    tp_dist = entry_info['atr'] * range_tp_atr
                    if pnl_pts > tp_dist:
                        exit_reason = "rng_tp"

                # v11 A5 原版震荡出场
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

            if entry_info['regime'] == "trend" and exit_reason is None:
                # 趋势移动止盈: 从最高/最低点回撤 N 倍 ATR 出
                if trend_trail_atr > 0:
                    if position == "LONG":
                        trail_dist = entry_info['atr'] * trend_trail_atr
                        if close < entry_info['peak'] - trail_dist:
                            exit_reason = "trend_trail"
                    else:
                        trail_dist = entry_info['atr'] * trend_trail_atr
                        if close > entry_info['peak'] + trail_dist:
                            exit_reason = "trend_trail"
                # 趋势 BB 中轨止盈: 收破 BB 中轨(SMA20)
                if exit_reason is None and trend_exit_bb:
                    if position == "LONG" and close < bb_mid:
                        exit_reason = "trend_bb_exit"
                    elif position == "SHORT" and close > bb_mid:
                        exit_reason = "trend_bb_exit"
                # 趋势 EMA 止盈: 收破 EMA21 即趋势可能结束
                if exit_reason is None and trend_exit_ema:
                    if position == "LONG" and close < ma_val:
                        exit_reason = "trend_ema_exit"
                    elif position == "SHORT" and close > ma_val:
                        exit_reason = "trend_ema_exit"
                # 趋势硬止盈: 仅当开启时生效 (v1 行为)
                if exit_reason is None and entry_info['tp_atr'] and entry_info['tp_atr'] > 0:
                    tp_dist = entry_info['atr'] * entry_info['tp_atr']
                    if pnl_pts > tp_dist:
                        exit_reason = "trend_tp"
                # ADX 衰减
                if exit_reason is None and adx < 20:
                    exit_reason = "trend_adx_drop"
                # DI 反转
                if exit_reason is None:
                    if position == "LONG" and ndi > pdi:
                        exit_reason = "trend_di_flip_long"
                    elif position == "SHORT" and pdi > ndi:
                        exit_reason = "trend_di_flip_short"

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
                    "adx_entry": round(entry_info['adx'], 1),
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
            "adx_entry": round(entry_info['adx'], 1),
        })

    return trades


def compute_stats(trades):
    closed = [t for t in trades if t['exit_reason'] != "end_of_data"]
    if not closed:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0,
                "avg_pnl": 0, "max_drawdown": 0, "profit_factor": 0,
                "long_count": 0, "short_count": 0, "trend_count": 0, "range_count": 0,
                "avg_bars": 0}
    wins = [t for t in closed if t['pnl'] > 0]
    losses = [t for t in closed if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in closed)
    cum, peak, max_dd = 0, 0, 0
    for t in closed:
        cum += t['pnl']
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    gp = sum(t['pnl'] for t in wins)
    gl = abs(sum(t['pnl'] for t in losses))
    pf = gp / gl if gl > 0 else 0
    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) * 100,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / len(closed), 2),
        "max_drawdown": round(max_dd, 2),
        "profit_factor": round(pf, 2),
        "long_count": sum(1 for t in closed if t['direction'] == "LONG"),
        "short_count": sum(1 for t in closed if t['direction'] == "SHORT"),
        "trend_count": sum(1 for t in closed if t['regime'] == "trend"),
        "range_count": sum(1 for t in closed if t['regime'] == "range"),
        "avg_bars": round(sum(t['bars'] for t in closed) / len(closed), 1),
    }


def main():
    print("=" * 100)
    print("  v13 双模 — v11 A5 震荡基础 + 可选趋势叠加")
    print("=" * 100)
    print()

    m30 = load_ohlcv("M30")
    gc_m30 = load_ohlcv("GC_M30")
    print(f"  M30: {len(m30)} 根 ({m30[0]['ts_str']} -> {m30[-1]['ts_str']})")
    print(f"  GC_M30: {len(gc_m30)} 根 ({gc_m30[0]['ts_str']} -> {gc_m30[-1]['ts_str']})")
    print()

    configs = [
        ("T0 v11 A5 基线",      {}),
        ("T6v8 趋势+Stoch叉+TP4", {"enable_trend_long": True, "enable_trend_short": True, "trend_sl_atr": 2.0, "trend_tp_atr": 4.0}),
        ("T6v9 趋势+Stoch+TP4+RTP2", {"enable_trend_long": True, "enable_trend_short": True, "trend_sl_atr": 2.0, "trend_tp_atr": 4.0, "range_tp_atr": 2.0}),
    ]

    all_m30, all_gc, all_trades = [], [], {}

    print("  ── M30 (生产, 至 2026-06-19) ──")
    for name, kw in configs:
        trades = run_backtest(m30, **kw)
        s = compute_stats(trades)
        s["name"] = name
        all_m30.append(s)
        all_trades[f"M30_{name}"] = trades
        m = " [V]" if s['total_pnl'] > 0 else " [X]"
        print(f"  {name:<26} {s['trades']:>4} 笔, 胜率 {s['win_rate']:>5.1f}%, "
              f"P/L ${s['total_pnl']:>+8.2f}, PF {s['profit_factor']:.2f}, "
              f"L={s['long_count']}/S={s['short_count']}, "
              f"震荡={s['range_count']}/趋势={s['trend_count']}{m}")

    print()
    print("  ── GC_M30 (跨品种验证) ──")
    for name, kw in configs:
        trades = run_backtest(gc_m30, **kw)
        s = compute_stats(trades)
        s["name"] = name
        all_gc.append(s)
        all_trades[f"GC_{name}"] = trades
        m = " [V]" if s['total_pnl'] > 0 else " [X]"
        print(f"  GC_{name:<26} {s['trades']:>4} 笔, 胜率 {s['win_rate']:>5.1f}%, "
              f"P/L ${s['total_pnl']:>+8.2f}, PF {s['profit_factor']:.2f}, "
              f"L={s['long_count']}/S={s['short_count']}, "
              f"震荡={s['range_count']}/趋势={s['trend_count']}{m}")

    print()
    print("=" * 100)
    print("  双品种对比")
    print("=" * 100)
    print(f"  {'配置':<28}  {'M30 P/L':>10}  {'M30 胜率':>8}  {'M30 PF':>7}  | {'GC P/L':>10}  {'GC 胜率':>8}  {'GC PF':>7}  双品种")
    print("  " + "-" * 110)
    for name, _ in configs:
        m = next(r for r in all_m30 if r['name'] == name)
        g = next(r for r in all_gc if r['name'] == name)
        both = "[VV]" if m['total_pnl'] > 0 and g['total_pnl'] > 0 else (
               "[V-]" if m['total_pnl'] > 0 else (
               "[-V]" if g['total_pnl'] > 0 else "[--]"))
        print(f"  {name:<28}  ${m['total_pnl']:>+8.2f}  {m['win_rate']:>6.1f}%  {m['profit_factor']:>6.2f}  | "
              f"${g['total_pnl']:>+8.2f}  {g['win_rate']:>6.1f}%  {g['profit_factor']:>6.2f}  {both}")

    # 出场原因 (双品种盈利的)
    m30_profit = {r['name'] for r in all_m30 if r['total_pnl'] > 0}
    gc_profit = {r['name'] for r in all_gc if r['total_pnl'] > 0}
    both_profit = m30_profit & gc_profit
    if both_profit:
        print()
        print("=" * 100)
        print(f"  *** 双品种盈利配置出场明细 ({len(both_profit)}/{len(configs)})")
        print("=" * 100)
        for name in sorted(both_profit):
            for tf_label in ["M30", "GC"]:
                key = f"{tf_label}_{name}"
                trades = all_trades[key]
                closed = [t for t in trades if t['exit_reason'] != 'end_of_data']
                if not closed:
                    continue
                pnl_total = sum(t['pnl'] for t in closed)
                by_reason = defaultdict(list)
                for t in closed:
                    by_reason[t['exit_reason']].append(t)
                print(f"  [V] {key} (P/L ${pnl_total:+.2f}, {len(closed)} 笔):")
                for reason, ts in sorted(by_reason.items(), key=lambda x: -len(x[1])):
                    wins = sum(1 for t in ts if t['pnl'] > 0)
                    wr = wins / len(ts) * 100
                    rpnl = sum(t['pnl'] for t in ts)
                    print(f"    {reason:<22} {len(ts):>4} 笔, 胜率 {wr:>5.1f}%, P/L ${rpnl:>+7.2f}")


if __name__ == "__main__":
    main()
