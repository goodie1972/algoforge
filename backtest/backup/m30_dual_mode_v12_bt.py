"""
M30 双模式 v12 回测 — 真 ADX 切换均值回归 / 趋势跟随
=====================================================
背景:
  今天 (2026-06-19) M30_rsi_bb 在强下跌趋势中开 3 张多单全 hard_stop。
  根因: 5 因子评分系统在下跌中只能触发 BUY (BB-BOT + RSI<30 + LOW-VOL),
       SELL 永远触发不了 (BB upper/RSI>65 在下跌中不可达)。
  + LOW-VOL bug: ATR<2.5%×price 阈值过低, 永远 True, 同时给多/空各加 1 分。

v12 双模思路 (用户认可):
  ADX < 25         → 震荡模式: M30_rsi_bb 5 因子评分 (LOW-VOL 修复)
  ADX >= 25 + DI 主导 + EMA21 一致 → 趋势模式: 顺势开单

测试矩阵:
  D1  纯震荡 (M30_rsi_bb 5 因子 + LOW-VOL 修)        - 基线
  D2  纯趋势 (ADX>=25 + DI + EMA21)                 - 基线
  D3  双模 ADX<25/>=25 切换 (推荐)
  D4  D3 + 趋势 SL 放宽 (1.5 ATR, 趋势单止损要远)
  D5  D3 + LOW-VOL 完全移除 (4 因子)
  D6  D3 + 趋势模式只开反向 (跟随主趋势, 禁止逆势震荡单)

数据: M30 (2876 根, 至 2026-06-19) + GC_M30 (1895 根, 至 2026-06-13)
"""
import os
import sys
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backtest.mean_reversion_bt import (
    load_ohlcv, calc_ema, calc_sma, calc_atr_from_lists,
    calc_rsi, calc_bb, calc_adx_real,
)


def calc_rsi_series(closes, period=14):
    """计算最近两根的 RSI 用于判断方向"""
    if len(closes) < period + 2:
        return None, None
    rsi_curr = calc_rsi(closes, period)
    rsi_prev = calc_rsi(closes[:-1], period)
    return rsi_prev, rsi_curr


def get_m30_trend(closes, period=200):
    """M30 自身周期 SMA 判趋势"""
    if len(closes) < period:
        return 'flat'
    sma_curr = sum(closes[-period:]) / period
    sma_prev = sum(closes[-period - 1:-1]) / period if len(closes) >= period + 1 else sma_curr
    close = closes[-1]
    if close > sma_curr and sma_curr >= sma_prev:
        return 'UP'
    if close < sma_curr and sma_curr <= sma_prev:
        return 'DOWN'
    return 'flat'


def run_backtest(candles, mode="dual",
                 adx_trend_threshold=25,
                 adx_range_threshold=25,
                 di_threshold=5,
                 ema_period=21,
                 sl_atr_range=1.0,
                 sl_atr_trend=1.0,
                 score_threshold=3,
                 low_vol_mode="fixed",  # "fixed"=只加单边, "remove"=移除, "buggy"=v6 老逻辑
                 trend_only_with_main=False,
                 lot_size=0.01,
                 commission=0.5):
    """
    mode: "range_only" | "trend_only" | "dual"
    low_vol_mode: "fixed"=按方向加分, "remove"=不加, "buggy"=同时加多空(老 bug)
    """
    trades = []
    position = None
    entry_info = {}

    n = len(candles)
    rsi_period = 14
    rsi_oversold = 30
    rsi_overbought = 70
    atr_period = 14
    bb_period = 20
    bb_std = 2.0

    for i in range(251, n):
        c = candles[i]
        sub = candles[:i + 1]
        closes = [x['close'] for x in sub]
        highs = [x['high'] for x in sub]
        lows = [x['low'] for x in sub]
        close = closes[-1]

        ema21 = calc_ema(closes, ema_period)
        if ema21 is None:
            continue
        atr_val = calc_atr_from_lists(highs, lows, closes, atr_period)
        if atr_val is None or atr_val <= 0:
            continue
        adx_data = calc_adx_real(highs, lows, closes, 14)
        if adx_data is None:
            continue
        adx = adx_data['adx']
        pdi = adx_data['pdi']
        ndi = adx_data['ndi']
        bb = calc_bb(closes, bb_period, bb_std)
        if bb is None:
            continue
        rsi_val = calc_rsi(closes, rsi_period)
        rsi_prev = calc_rsi(closes[:-1], rsi_period)
        if rsi_val is None or rsi_prev is None:
            continue
        m30_trend = get_m30_trend(closes, 100)  # M30 用更短周期 100 根 (v6 是 200)

        # ── 入场 ──
        if position is None:
            signal = None
            entry_reason = ""

            # ── 趋势模式 (ADX 强) ──
            if mode in ("trend_only", "dual") and adx >= adx_trend_threshold:
                if (pdi - ndi) > di_threshold and close > ema21:
                    signal = "LONG"
                    entry_reason = f"trend_long(adx={adx:.0f},+di-{ndi:.0f}={pdi-ndi:.0f})"
                elif (ndi - pdi) > di_threshold and close < ema21:
                    signal = "SHORT"
                    entry_reason = f"trend_short(adx={adx:.0f},-di-{pdi:.0f}={ndi-pdi:.0f})"

            # ── 震荡模式 (ADX 弱, 用 5 因子评分) ──
            elif mode in ("range_only", "dual") and adx < adx_range_threshold:
                long_score = 0
                short_score = 0

                # ① M30 趋势
                if m30_trend == 'UP':
                    long_score += 1
                elif m30_trend == 'DOWN':
                    short_score += 1

                # ② BB 触碰
                if close <= bb['lower']:
                    long_score += 1
                if close >= bb['upper']:
                    short_score += 1

                # ③ RSI 极端
                if rsi_val < rsi_oversold:
                    long_score += 1
                if rsi_val > rsi_overbought:
                    short_score += 1

                # ④ RSI 方向
                if rsi_prev < rsi_val:
                    long_score += 1
                elif rsi_prev > rsi_val:
                    short_score += 1

                # ⑤ LOW-VOL (修复双向加分 bug)
                vol_recent = sum(closes[-10:]) / 10
                low_vol = atr_val < vol_recent * 0.025
                if low_vol:
                    if low_vol_mode == "buggy":
                        long_score += 1
                        short_score += 1
                    elif low_vol_mode == "fixed":
                        # 趋势方向加分: M30 UP → long+1; DOWN → short+1; flat → 不加
                        if m30_trend == 'UP':
                            long_score += 1
                        elif m30_trend == 'DOWN':
                            short_score += 1
                    # remove: 不加

                if long_score >= score_threshold and long_score > short_score:
                    signal = "LONG"
                    entry_reason = f"range_long(adx={adx:.0f},score={long_score})"
                elif short_score >= score_threshold and short_score > long_score:
                    # 深超卖禁空 (复用 v6 逻辑)
                    if rsi_val >= 20:
                        signal = "SHORT"
                        entry_reason = f"range_short(adx={adx:.0f},score={short_score})"

            # 趋势单 + 反趋势震荡单的过滤
            if trend_only_with_main and signal and adx < adx_trend_threshold:
                if m30_trend == 'UP' and signal == 'SHORT':
                    signal = None
                if m30_trend == 'DOWN' and signal == 'LONG':
                    signal = None

            if signal:
                in_trend = adx >= adx_trend_threshold
                position = signal
                entry_info = {
                    "time": c['ts_str'], "price": close, "idx": i,
                    "ema21": ema21, "atr": atr_val,
                    "regime": "trend" if in_trend else "range",
                    "adx": adx, "pdi": pdi, "ndi": ndi,
                    "rsi": rsi_val,
                    "reason": entry_reason,
                    "sl_atr": sl_atr_trend if in_trend else sl_atr_range,
                }

        # ── 出场 ──
        else:
            pnl_pts = (close - entry_info['price']) if position == "LONG" else (entry_info['price'] - close)
            exit_reason = None
            exit_p = close

            # 1. 硬止损 (区分趋势/震荡)
            sl_dist = entry_info['atr'] * entry_info['sl_atr']
            if pnl_pts < -sl_dist:
                exit_reason = "hard_stop"
                if position == "LONG":
                    exit_p = entry_info['price'] - sl_dist
                else:
                    exit_p = entry_info['price'] + sl_dist

            # 2. 趋势止盈: ADX 衰减或 DI 反转
            if exit_reason is None and entry_info['regime'] == "trend":
                if position == "LONG":
                    if adx < 20 or (ndi > pdi):
                        exit_reason = "trend_exit_long"
                else:
                    if adx < 20 or (pdi > ndi):
                        exit_reason = "trend_exit_short"
                # 趋势止盈: 2*ATR
                if exit_reason is None and pnl_pts > entry_info['atr'] * 2.5:
                    exit_reason = "trend_tp"

            # 3. 震荡止盈: 回到 BB 中轨 / RSI 反向
            if exit_reason is None and entry_info['regime'] == "range":
                bb_mid = bb['sma']
                if position == "LONG":
                    # 长达 BB 中轨上方或 RSI > 60
                    if close >= bb_mid or rsi_val >= 55:
                        exit_reason = "range_tp_long"
                else:
                    if close <= bb_mid or rsi_val <= 45:
                        exit_reason = "range_tp_short"

            # 4. 时间止损 (持仓 > 30 根 K 线)
            if exit_reason is None and (i - entry_info['idx']) > 30:
                exit_reason = "timeout"

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
                    "reason": entry_info['reason'],
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
            "reason": entry_info['reason'],
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
    avg_pnl = total_pnl / len(closed)

    cum, peak, max_dd = 0, 0, 0
    for t in closed:
        cum += t['pnl']
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    gross_profit = sum(t['pnl'] for t in wins)
    gross_loss = abs(sum(t['pnl'] for t in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else 0

    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) * 100,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
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
    print("  M30 双模式 v12 回测 — ADX 切换均值回归 / 趋势跟随")
    print("=" * 100)
    print()

    m30 = load_ohlcv("M30")
    gc_m30 = load_ohlcv("GC_M30")

    print(f"  M30: {len(m30)} 根 ({m30[0]['ts_str']} -> {m30[-1]['ts_str']})")
    print(f"  GC_M30: {len(gc_m30)} 根 ({gc_m30[0]['ts_str']} -> {gc_m30[-1]['ts_str']})")
    print()

    configs = [
        ("D1 纯震荡 (LOW-VOL 修)",  {"mode": "range_only", "low_vol_mode": "fixed"}),
        ("D1' 纯震荡 (LOW-VOL 移除)", {"mode": "range_only", "low_vol_mode": "remove"}),
        ("D1\" 纯震荡 (老 buggy)",   {"mode": "range_only", "low_vol_mode": "buggy"}),
        ("D2 纯趋势",              {"mode": "trend_only"}),
        ("D3 双模 (推荐)",          {"mode": "dual", "low_vol_mode": "fixed"}),
        ("D4 双模 + 趋势 SL=1.5",   {"mode": "dual", "low_vol_mode": "fixed", "sl_atr_trend": 1.5}),
        ("D5 双模 + LOW-VOL 移除",  {"mode": "dual", "low_vol_mode": "remove"}),
        ("D6 双模 + 主趋势过滤",     {"mode": "dual", "low_vol_mode": "fixed", "trend_only_with_main": True}),
    ]

    all_m30 = []
    all_gc = []
    all_trades = {}

    print("  ── M30 (生产) ──")
    for name, kw in configs:
        trades = run_backtest(m30, **kw)
        stats = compute_stats(trades)
        stats["name"] = name
        stats["tf"] = "M30"
        all_m30.append(stats)
        all_trades[f"M30_{name}"] = trades
        mark = " ✅" if stats['total_pnl'] > 0 else " ❌"
        print(f"  {name:<28} {stats['trades']:>4} 笔, 胜率 {stats['win_rate']:>5.1f}%, "
              f"P/L ${stats['total_pnl']:>+8.2f}, PF {stats['profit_factor']:.2f}, "
              f"L={stats['long_count']}/S={stats['short_count']}, "
              f"趋势={stats['trend_count']}/震荡={stats['range_count']}{mark}")

    print()
    print("  ── GC_M30 (跨品种验证) ──")
    for name, kw in configs:
        trades = run_backtest(gc_m30, **kw)
        stats = compute_stats(trades)
        stats["name"] = name
        stats["tf"] = "GC_M30"
        all_gc.append(stats)
        all_trades[f"GC_{name}"] = trades
        mark = " ✅" if stats['total_pnl'] > 0 else " ❌"
        print(f"  GC_{name:<28} {stats['trades']:>4} 笔, 胜率 {stats['win_rate']:>5.1f}%, "
              f"P/L ${stats['total_pnl']:>+8.2f}, PF {stats['profit_factor']:.2f}, "
              f"L={stats['long_count']}/S={stats['short_count']}, "
              f"趋势={stats['trend_count']}/震荡={stats['range_count']}{mark}")

    # 双品种盈利筛选
    print()
    print("=" * 100)
    print("  汇总: 双品种都盈利的配置")
    print("=" * 100)
    m30_profit = {r['name'] for r in all_m30 if r['total_pnl'] > 0}
    gc_profit = {r['name'] for r in all_gc if r['total_pnl'] > 0}
    both = m30_profit & gc_profit
    if both:
        print(f"  🏆 双品种盈利 ({len(both)}/{len(configs)}):")
        for name in sorted(both):
            m = next(r for r in all_m30 if r['name'] == name)
            g = next(r for r in all_gc if r['name'] == name)
            print(f"    {name}")
            print(f"      M30:    P/L ${m['total_pnl']:+.2f} | {m['trades']} 笔 | 胜率 {m['win_rate']:.1f}% | PF {m['profit_factor']:.2f} | DD ${m['max_drawdown']:.2f}")
            print(f"      GC_M30: P/L ${g['total_pnl']:+.2f} | {g['trades']} 笔 | 胜率 {g['win_rate']:.1f}% | PF {g['profit_factor']:.2f} | DD ${g['max_drawdown']:.2f}")
    else:
        print(f"  ⚠️ 没有双品种都盈利的配置")
        print(f"    M30 盈利: {m30_profit or '无'}")
        print(f"    GC 盈利: {gc_profit or '无'}")

    # 出场原因 (盈利配置)
    print()
    print("=" * 100)
    print("  出场原因明细 (盈利配置)")
    print("=" * 100)
    for label, trades in all_trades.items():
        closed = [t for t in trades if t['exit_reason'] != 'end_of_data']
        if not closed:
            continue
        pnl_total = sum(t['pnl'] for t in closed)
        if pnl_total <= 0:
            continue
        by_reason = defaultdict(list)
        for t in closed:
            by_reason[t['exit_reason']].append(t)
        print(f"\n  ✅ {label} (总 P/L ${pnl_total:+.2f}):")
        for reason, ts in sorted(by_reason.items(), key=lambda x: -len(x[1])):
            wins = sum(1 for t in ts if t['pnl'] > 0)
            wr = wins / len(ts) * 100
            rpnl = sum(t['pnl'] for t in ts)
            print(f"    {reason:<22} {len(ts):>4} 笔, 胜率 {wr:>5.1f}%, P/L ${rpnl:>+7.2f}, 均 ${rpnl/len(ts):+.2f}")


if __name__ == "__main__":
    main()
