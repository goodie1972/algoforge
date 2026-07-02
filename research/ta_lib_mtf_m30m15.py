"""
M30 + M15 双周期共振测试
=========================
核心问题：M30 信号在有 M15 同向信号确认时，是否比 M30 单独更可靠？

方法:
  1. 检测 GC_M30 上所有 TA-Lib 形态 + 过滤器组合
  2. 检查对应时间窗口内 GC_M15 是否有同向信号
  3. 分组: M30单独 vs M30+M15共振
  4. 统一 ATR 止损验证胜率/盈亏
  5. 对比 H1 已有结论

用法:
  python research/ta_lib_mtf_m30m15.py

输出:
  - 终端: 结果对比表
  - CSV: research/ta_lib_mtf_m30m15_results.csv
"""

import csv
import datetime
import os
import sys
from collections import defaultdict

import numpy as np
import talib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.database import get_conn

# =============================================================
# 配置
# =============================================================
P_TIMEFRAMES = ["GC_M30", "GC_M15"]
LOOKAHEAD = 3
BEST_FILTERS_BULL = ["rsi_mid_oversold", "trend_down"]
BEST_FILTERS_BEAR = ["rsi_mid_overbought", "trend_up"]
SL_MULT = 1.75  # 沿用 H1 最佳 SL

SECONDARY_WINDOW = 1800  # M30 一根 = 1800s, 检查前后各一根


def load_data(timeframe):
    conn = get_conn()
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume "
        "FROM ohlcv WHERE timeframe = ? ORDER BY timestamp",
        (timeframe,),
    ).fetchall()
    arr = np.array([(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows],
                   dtype=[("ts", "i8"), ("o", "f8"), ("h", "f8"),
                          ("l", "f8"), ("c", "f8"), ("v", "f8")])
    return arr


def compute_indicators(o, h, l, c):
    ind = {}
    ind["rsi"] = talib.RSI(c, timeperiod=14)
    ind["atr"] = talib.ATR(h, l, c, timeperiod=14)
    ind["ema20"] = talib.EMA(c, timeperiod=20)
    return ind


def detect_all_patterns(o, h, l, c):
    patterns = {}
    for pname in dir(talib):
        if pname.startswith("CDL"):
            fn = getattr(talib, pname)
            try:
                sig = fn(o, h, l, c)
            except TypeError:
                try:
                    sig = fn(h, l, c)
                except TypeError:
                    continue
            if np.any(sig != 0):
                patterns[pname] = sig
    return patterns


def check_filter(idx, ind, close_arr, filter_name, sig_dir):
    rsi = ind["rsi"][idx]
    ema20 = ind["ema20"][idx]
    if filter_name == "rsi_mid_oversold":
        return not np.isnan(rsi) and 30 <= rsi <= 50 and sig_dir == "bull"
    elif filter_name == "rsi_mid_overbought":
        return not np.isnan(rsi) and 50 <= rsi <= 70 and sig_dir == "bear"
    elif filter_name == "trend_up":
        return not np.isnan(ema20) and close_arr[idx] > ema20
    elif filter_name == "trend_down":
        return not np.isnan(ema20) and close_arr[idx] < ema20
    return False


def find_signals(data, bull_filters, bear_filters):
    """在数据上查找所有模式+过滤器组合的信号"""
    o, h, l, c = data["o"], data["h"], data["l"], data["c"]
    ind = compute_indicators(o, h, l, c)
    patterns = detect_all_patterns(o, h, l, c)

    signals = []
    n = len(data)

    for pname, sig_arr in patterns.items():
        for i in range(LOOKAHEAD + 2, n - LOOKAHEAD - 2):
            raw = sig_arr[i]
            if raw == 0:
                continue
            sig_dir = "bull" if raw > 0 else "bear"

            filters = bull_filters if sig_dir == "bull" else bear_filters
            matched = None
            for fname in filters:
                if check_filter(i, ind, c, fname, sig_dir):
                    matched = fname
                    break
            if not matched:
                continue

            atr_val = max(ind["atr"][i], 0.1)
            if sig_dir == "bull":
                sl_price = c[i] - SL_MULT * atr_val
            else:
                sl_price = c[i] + SL_MULT * atr_val

            signals.append({
                "ts": data["ts"][i],
                "idx": i,
                "pname": pname,
                "dir": sig_dir,
                "filter": matched,
                "entry": c[i],
                "sl": sl_price,
                "atr": atr_val,
                "rsi": round(ind["rsi"][i], 1) if not np.isnan(ind["rsi"][i]) else None,
            })

    return signals


def verify_trade(data, sig):
    """验证单笔交易，向前 LOOKAHEAD 根"""
    idx = sig["idx"]
    entry = sig["entry"]
    sl = sig["sl"]
    sig_dir = sig["dir"]
    n = len(data)

    end = min(idx + LOOKAHEAD + 1, n)
    if end - idx < 2:
        return None

    # 是否触 SL
    hit_sl = False
    for j in range(idx + 1, end):
        if sig_dir == "bull" and data[j]["l"] <= sl:
            hit_sl = True
            break
        elif sig_dir == "bear" and data[j]["h"] >= sl:
            hit_sl = True
            break

    if hit_sl:
        exit_price = sl
    elif sig_dir == "bull":
        exit_price = data[end - 1]["c"]
    else:
        exit_price = data[end - 1]["c"]

    pnl = (exit_price - entry) if sig_dir == "bull" else (entry - exit_price)
    return {"pnl": pnl, "win": pnl > 0, "hit_sl": hit_sl}


def has_confluence(sig_ts, sig_dir, secondary_signals, window_sec=1800):
    """检查 secondary TF 在时间窗口内是否有同向信号"""
    t_start = sig_ts - window_sec
    t_end = sig_ts + window_sec
    for s in secondary_signals:
        if s["dir"] == sig_dir and t_start <= s["ts"] <= t_end:
            return True
    return False


# =============================================================
# 主流程
# =============================================================
def main():
    print(f"\n{'='*60}")
    print(f"M30 + M15 双周期共振测试")
    print(f"SL={SL_MULT}×ATR | 前瞻={LOOKAHEAD}根")
    print(f"{'='*60}")

    # 加载数据
    data = {}
    for tf in P_TIMEFRAMES:
        data[tf] = load_data(tf)
        n = len(data[tf])
        t0 = datetime.datetime.fromtimestamp(data[tf]["ts"][0]).strftime("%Y-%m-%d")
        t1 = datetime.datetime.fromtimestamp(data[tf]["ts"][-1]).strftime("%Y-%m-%d")
        print(f"  {tf}: {n} 根 ({t0} ~ {t1})")

    # 检测信号
    m30_sigs = find_signals(data["GC_M30"], BEST_FILTERS_BULL, BEST_FILTERS_BEAR)
    m15_sigs = find_signals(data["GC_M15"], BEST_FILTERS_BULL, BEST_FILTERS_BEAR)
    print(f"\n  M30 信号: {len(m30_sigs)} 个")
    print(f"  M15 信号: {len(m15_sigs)} 个")

    # 去重: 同一K线同方向保留最强
    def dedup(sigs):
        sigs.sort(key=lambda s: 0 if s["dir"] == "bull" else 1)
        seen = set()
        out = []
        for s in sigs:
            k = (s["ts"], s["dir"])
            if k not in seen:
                seen.add(k)
                out.append(s)
        return sorted(out, key=lambda s: s["ts"])

    m30_sigs = dedup(m30_sigs)
    m15_sigs = dedup(m15_sigs)

    # 验证每笔 + 判断共振
    m30_solo = []
    m30_resonance = []
    for sig in m30_sigs:
        result = verify_trade(data["GC_M30"], sig)
        if result is None:
            continue
        sig.update(result)

        if has_confluence(sig["ts"], sig["dir"], m15_sigs, SECONDARY_WINDOW):
            m30_resonance.append(sig)
        else:
            m30_solo.append(sig)

    print(f"\n  M30 单独: {len(m30_solo)} 笔")
    print(f"  M30+M15 共振: {len(m30_resonance)} 笔")

    # =============================================================
    # 统计输出
    # =============================================================
    def print_stats(label, trades):
        if not trades:
            print(f"  {label:<20} 无数据")
            return
        n = len(trades)
        wins = sum(1 for t in trades if t["win"])
        wr = wins / n * 100
        total_pnl = sum(t["pnl"] for t in trades)
        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = sum(t["pnl"] for t in trades if t["pnl"] < 0)
        avg_pnl = total_pnl / n
        pf = gross_profit / abs(gross_loss) if gross_loss != 0 else (float("inf") if gross_profit > 0 else 0)
        hsl = sum(1 for t in trades if t.get("hit_sl")) / n * 100
        bulls = sum(1 for t in trades if t["dir"] == "bull")
        bears = sum(1 for t in trades if t["dir"] == "bear")
        print(f"  {label:<20} {n:>4}笔 {wins:>3}胜 {n-wins:>3}负 {wr:>5.1f}%  "
              f"${total_pnl:>+7.1f}  PF={pf:.2f}  avg=${avg_pnl:>+5.1f}  SL%={hsl:.0f}%  "
              f"({bulls}↑ {bears}↓)")

    print(f"\n{'='*80}")
    print(f"  M30 vs M30+M15 共振结果")
    print(f"{'='*80}")
    print_stats("M30 全部", m30_sigs)
    print_stats("M30 单独(无共振)", m30_solo)
    print_stats("M30+M15 共振", m30_resonance)

    # 按形态分组
    print(f"\n{'='*80}")
    print(f"  按形态 + 共振分组（仅显示笔数>=5的）")
    print(f"{'='*80}")
    by_pattern = defaultdict(list)
    for s in m30_sigs:
        by_pattern[s["pname"]].append(s)

    for pname in sorted(by_pattern.keys()):
        trades = by_pattern[pname]
        n_trades = len(trades)
        solo = [t for t in trades if t not in m30_resonance]
        reso = [t for t in trades if t in m30_resonance]
        if n_trades < 5:
            continue
        wr_all = sum(1 for t in trades if t["win"]) / n_trades * 100
        wr_reso = sum(1 for t in reso if t["win"]) / len(reso) * 100 if reso else 0
        reso_str = f" | 共振{len(reso)}笔 wr={wr_reso:.1f}%" if reso else ""
        print(f"  {pname:<22} 全部{n_trades:>3}笔 wr={wr_all:>5.1f}%{reso_str}")

    # 共振明细
    if m30_resonance:
        print(f"\n{'='*80}")
        print(f"  M30+M15 共振明细 (前15笔)")
        print(f"{'='*80}")
        for sig in sorted(m30_resonance, key=lambda s: s["ts"])[:15]:
            ts = datetime.datetime.fromtimestamp(sig["ts"]).strftime("%m-%d %H:%M")
            win = "WIN" if sig["win"] else "LOSS"
            print(f"    {ts} | {sig['pname']:<18} | {sig['dir'].upper():<4} | "
                  f"${sig['entry']:.2f} | {win:<4} | ${sig['pnl']:+.1f}")

    # 保存 CSV
    out_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(out_dir, "ta_lib_mtf_m30m15_results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["形态","时间","方向","过滤器","入场价","止损价","盈亏","是否止损","胜","共振M15"])
        for sig in sorted(m30_sigs, key=lambda s: s["ts"]):
            ts_str = datetime.datetime.fromtimestamp(sig["ts"]).strftime("%Y-%m-%d %H:%M")
            is_reso = "Y" if sig in m30_resonance else "N"
            w.writerow([
                sig["pname"], ts_str, sig["dir"].upper(), sig["filter"],
                round(sig["entry"],2), round(sig["sl"],2),
                round(sig["pnl"],2), "Y" if sig.get("hit_sl") else "N",
                "Y" if sig.get("win") else "N", is_reso,
            ])
    print(f"\n结果已保存: {csv_path}")

    # =============================================================
    # H1 对比汇总
    # =============================================================
    print(f"\n{'='*110}")
    print(f"  全部 MTF 结果汇总对比")
    print(f"{'='*110}")
    print(f"  {'分组':<22} {'数据源':<12} {'数据天数':<8} {'交易数':<7} {'胜率':<7} "
          f"{'总盈亏':<10} {'盈亏比':<7} {'平均/笔':<9}")
    print(f"  {'-'*110}")

    # H1 数据 (来自 ta_lib_findings.md)
    h1_ref = [
        ("H1 全部", "GC_H1", 729, 1318, 50.8, 1135, 1.19),
        ("H1+M30", "GC_H1+GC_M30", 59, 13, 61.5, 184, 4.36),
        ("H1+M15", "GC_H1+GC_M15", 59, 16, 93.8, 164, 12.60),
        ("全共振 H1+M30+M15", "GC_H1+GC_M30+GC_M15", 59, 16, 56.2, 123, 2.80),
    ]

    for label, source, days, n, wr, pnl, pf in h1_ref:
        print(f"  {label:<22} {source:<12} {days:<8} {n:<7} {wr:<6.1f}% ${pnl:<+7.1f} {pf:<7.2f}")

    # M30 本次结果
    def row_data(label, trades, days=59):
        if not trades:
            return (label, "GC_M30", days, 0, 0, 0, 0)
        n = len(trades)
        wins = sum(1 for t in trades if t["win"])
        wr = wins / n * 100
        pnl = sum(t["pnl"] for t in trades)
        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = sum(t["pnl"] for t in trades if t["pnl"] < 0)
        pf = gross_profit / abs(gross_loss) if gross_loss != 0 else (float("inf") if gross_profit > 0 else 0)
        return (label, "GC_M30", days, n, wr, pnl, pf)

    for r in [row_data("M30 全部", m30_sigs),
              row_data("M30 单独", m30_solo),
              row_data("M30+M15 共振", m30_resonance)]:
        print(f"  {r[0]:<22} {r[1]:<12} {r[2]:<8} {r[3]:<7} {r[4]:<6.1f}% ${r[5]:<+7.1f} {r[6]:<7.2f}")

    print(f"\n  注: H1 数据 729天, M30/M15 仅 59天, 横向对比注意样本量差异")


if __name__ == "__main__":
    main()
