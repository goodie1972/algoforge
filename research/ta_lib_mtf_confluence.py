"""
三周期共振验证 (MTF Confluence Test)
======================================
核心问题: 当 H1 / M30 / M15 多个周期同时出现信号时,
比单周期信号更可靠吗?

方法:
  1. 对每个 H1 蜡烛, 检测是否有"高质量信号"
  2. 同时检查对应时间窗口的 M30 和 M15 是否也有信号
  3. 分组: 1TF (仅H1) vs 2TF (H1+一个低周期) vs 3TF (全共振)
  4. 用统一 SL 计算各组的胜率/盈亏比
  5. 对比随机基准

"高质量信号"定义 (从 H1 扫描结果中选出的 3 个最稳组合):
  组合1: CDLSHORTLINE + RSI50~70 (bear)
  组合2: CDLHARAMI + RSI50~70 (bear)
  组合3: CDLSPINNINGTOP + RSI50~70 (bear)

用法:
  python research/ta_lib_mtf_confluence.py

输出:
  - 终端: MTF 分组结果表
  - CSV: research/ta_lib_mtf_results.csv
"""

import argparse
import csv
import datetime
import math
import os
import sys
from collections import defaultdict

import numpy as np
import talib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.database import get_conn

# ---------------------------------------------------------------------------
# 配置 - 从 H1 扫描选出的 3 个最稳组合
# ---------------------------------------------------------------------------

TARGET_PATTERNS = ["CDLSHORTLINE", "CDLHARAMI", "CDLSPINNINGTOP"]
TARGET_FILTER = "rsi_mid_overbought"  # RSI 50~70 + bearish
TARGET_DIR = "bear"
BEST_SL = 1.75  # 从 H1 扫描 CDLSHORTLINE 的最佳 SL

TIMEFRAMES = ["GC_H1", "GC_M30", "GC_M15"]
LOOKAHEAD = 3
MIN_SIGNALS = 5


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

def load_tf_data(timeframe):
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
    atr_pct = np.full_like(ind["atr"], np.nan)
    for i in range(60, len(ind["atr"])):
        atr_pct[i] = 1.0 if ind["atr"][i] > np.percentile(ind["atr"][i - 60:i], 70) else 0.0
    ind["atr_pct"] = atr_pct
    return ind


def detect_pattern(o, h, l, c, pname):
    fn = getattr(talib, pname)
    try:
        return fn(o, h, l, c)
    except TypeError:
        try:
            return fn(h, l, c)
        except TypeError:
            return np.zeros(len(c))


# ---------------------------------------------------------------------------
# 信号检测 (单个 TF)
# ---------------------------------------------------------------------------

def find_signals(data, pname):
    """在给定 TF 数据上查找目标信号, 返回信号时间戳和方向"""
    o, h, l, c = data["o"], data["h"], data["l"], data["c"]
    ind = compute_indicators(o, h, l, c)
    sig_arr = detect_pattern(o, h, l, c, pname)

    signals = []
    for i in range(LOOKAHEAD + 2, len(data) - LOOKAHEAD - 2):
        raw = sig_arr[i]
        if raw == 0:
            continue
        sig_dir = "bull" if raw > 0 else "bear"
        if sig_dir != TARGET_DIR:
            continue

        # 应用 RSI 50~70 过滤器
        rsi = ind["rsi"][i]
        if np.isnan(rsi) or not (50 <= rsi <= 70):
            continue

        ts = data[i]["ts"]
        # 入场价
        entry = c[i]
        atr_val = max(ind["atr"][i], 0.1)
        sl_price = entry + BEST_SL * atr_val  # bear: SL above entry

        signals.append({
            "ts": ts,
            "idx": i,
            "pname": pname,
            "entry": entry,
            "sl": sl_price,
            "atr": atr_val,
        })

    return signals, ind


# ---------------------------------------------------------------------------
# Forward 验证
# ---------------------------------------------------------------------------

def verify_trade(data, sig, ind, lookahead):
    """
    验证单笔交易.
    做空: entry -> 持仓 lookahead 根或 hit SL.
    """
    idx = sig["idx"]
    entry = sig["entry"]
    sl = sig["sl"]
    n = len(data)

    end = min(idx + lookahead + 1, n)
    if end - idx < 2:
        return None

    # 检查是否 hit SL
    hit_sl = False
    hit_idx = -1
    for j in range(idx + 1, end):
        if data[j]["h"] >= sl:
            hit_sl = True
            hit_idx = j
            break

    exit_price = sl if hit_sl else data[end - 1]["c"]
    pnl = entry - exit_price  # bear: entry - exit
    win = pnl > 0

    return {
        "win": win,
        "pnl": pnl,
        "pnl_atr": pnl / max(ind["atr"][hit_idx if hit_sl else end - 1], 0.1),
        "hit_sl": hit_sl,
    }


# ---------------------------------------------------------------------------
# MTF 对齐
# ---------------------------------------------------------------------------

def align_mtf_signals(h1_signals, m30_ts_set, m15_ts_set, h1_data):
    """
    对每个 H1 信号, 判断 M30/M15 是否也有信号.
    M30 信号在 H1 蜡烛的 [ts, ts+3600) 范围内计数为"有".
    M15 信号同理.
    """
    results = []
    for sig in h1_signals:
        ts_h1 = sig["ts"]
        h1_end = ts_h1 + 3600  # H1 窗口

        # M30: 任何在 [ts_h1, ts_h1+3600) 内的 M30 信号
        m30_match = any(ts_h1 <= mts < h1_end for mts in m30_ts_set)
        m15_match = any(ts_h1 <= mts < h1_end for mts in m15_ts_set)

        tf_count = 1 + (1 if m30_match else 0) + (1 if m15_match else 0)
        if tf_count == 2:
            tf_label = f"{TIMEFRAMES[0]}+{TIMEFRAMES[1]}" if m30_match and not m15_match else f"{TIMEFRAMES[0]}+{TIMEFRAMES[2]}"
        elif tf_count == 3:
            tf_label = f"{TIMEFRAMES[0]}+{TIMEFRAMES[1]}+{TIMEFRAMES[2]}"
        else:
            tf_label = TIMEFRAMES[0]
        results.append({**sig, "tf_count": tf_count, "tf_label": tf_label, "m30": m30_match, "m15": m15_match})

    return results


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    print(f"\n{'='*65}")
    print(f"三周期共振验证 | 目标: {TARGET_PATTERNS} + {TARGET_FILTER}")
    print(f"SL={BEST_SL}×ATR | 前瞻={LOOKAHEAD}根")
    print(f"{'='*65}")

    # 加载三个 TF 数据
    tf_data = {}
    for tf in TIMEFRAMES:
        tf_data[tf] = load_tf_data(tf)
        print(f"  {tf}: {len(tf_data[tf])} 根 K 线")

    # 对每个 TF, 合并所有目标形态的信号
    all_mtf_signals = {}  # "H1" -> [signals]
    m30_all_tss = set()
    m15_all_tss = set()

    for pname in TARGET_PATTERNS:
        # H1 信号 (主信号)
        h1_sigs, h1_ind = find_signals(tf_data[TIMEFRAMES[0]], pname)

        # M30 信号时间戳
        m30_sigs, _ = find_signals(tf_data[TIMEFRAMES[1]], pname)
        for s in m30_sigs:
            m30_all_tss.add(s["ts"])

        # M15 信号时间戳
        m15_sigs, _ = find_signals(tf_data[TIMEFRAMES[2]], pname)
        for s in m15_sigs:
            m15_all_tss.add(s["ts"])

        # 对齐 + 验证
        aligned = align_mtf_signals(h1_sigs, m30_all_tss, m15_all_tss, tf_data[TIMEFRAMES[0]])

        # 验证每笔交易
        for sig in aligned:
            result = verify_trade(tf_data[TIMEFRAMES[0]], sig, h1_ind, LOOKAHEAD)
            if result:
                sig.update(result)

        all_mtf_signals[pname] = aligned

    # -------------------------------------------------------------------
    # 汇总统计
    # -------------------------------------------------------------------

    # 按 TF 数量分组
    groups = {1: [], 2: [], 3: []}
    all_trades = []
    for pname, sigs in all_mtf_signals.items():
        for s in sigs:
            if "win" in s:
                groups[s["tf_count"]].append(s)
                all_trades.append(s)

    print(f"\n  总信号数: {len(all_trades)}")

    # 随机基准 (shuffle 方向)
    np.random.seed(42)
    random_groups = {1: [], 2: [], 3: []}
    for s in all_trades:
        rand_dir = "bull" if np.random.random() < 0.5 else "bear"
        if rand_dir == "bear":
            random_groups[s["tf_count"]].append(True)
        else:
            random_groups[s["tf_count"]].append(False)

    print(f"\n{'='*110}")
    print(f"  MTF 共振结果")
    print(f"{'='*110}")
    print(f"  {'分组':<22} {'交易数':<7} {'胜':<5} {'负':<5} {'胜率':<7} "
          f"{'总盈亏':<10} {'总盈利':<10} {'总亏损':<10} {'盈亏比':<7} {'平均/笔':<9} {'止损率':<7}")
    print(f"  {'-'*110}")

    # 按标签分组 (拆开 2TF 为 H1+M30 和 H1+M15)
    label_groups = defaultdict(list)
    for s in all_trades:
        label_groups[s.get("tf_label", str(s["tf_count"]))].append(s)

    label_order = [TIMEFRAMES[0],
                   f"{TIMEFRAMES[0]}+{TIMEFRAMES[1]}",
                   f"{TIMEFRAMES[0]}+{TIMEFRAMES[2]}",
                   f"{TIMEFRAMES[0]}+{TIMEFRAMES[1]}+{TIMEFRAMES[2]}"]

    for label in label_order:
        trades = label_groups.get(label, [])
        if not trades:
            continue

        wins = sum(1 for t in trades if t["win"])
        n = len(trades)
        wr = wins / n * 100

        # 金额统计
        total_pnl = sum(t["pnl"] for t in trades)
        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = sum(t["pnl"] for t in trades if t["pnl"] < 0)  # 负数
        avg_pnl = total_pnl / n if n > 0 else 0
        pf = gross_profit / abs(gross_loss) if gross_loss != 0 else (float("inf") if gross_profit > 0 else 0)
        hsl = sum(1 for t in trades if t["hit_sl"]) / n * 100 if n > 0 else 0

        print(f"  {label:<22} {n:<7} {wins:<5} {n-wins:<5} {wr:<6.1f}% "
              f"${total_pnl:<+8.1f} ${gross_profit:<+8.1f} ${gross_loss:<+8.1f} "
              f"{pf:<7.2f} ${avg_pnl:<+7.1f}  {hsl:<6.1f}%")

    # 按形态分组
    print(f"\n{'='*80}")
    print(f"  按形态 + TF 数量分组")
    print(f"{'='*80}")

    for pname in TARGET_PATTERNS:
        sigs = all_mtf_signals[pname]
        print(f"\n  --- {pname} ---")
        for tf_count in [1, 2, 3]:
            trades = [s for s in sigs if s.get("tf_count") == tf_count and "win" in s]
            if not trades:
                continue
            wins = sum(1 for t in trades if t["win"])
            n = len(trades)
            wr = wins / n * 100
            avg_pnl = np.mean([t["pnl"] for t in trades])
            total_pnl = sum(t["pnl"] for t in trades)
            pf = (sum(t["pnl"] for t in trades if t["pnl"] > 0) /
                  max(abs(sum(t["pnl"] for t in trades if t["pnl"] < 0)), 0.01))
            print(f"    {tf_count}TF: n={n:3d} 胜率={wr:5.1f}%  总盈亏=${total_pnl:+8.1f}  平均/笔=${avg_pnl:+5.1f}  PF={pf:.2f}")

    # 共振明细 (3TF 信号)
    print(f"\n{'='*80}")
    print(f"  全共振详情 (H1+M30+M15)")
    print(f"{'='*80}")

    three_tf = [s for s in all_trades if s["tf_count"] == 3]
    if three_tf:
        print(f"  共 {len(three_tf)} 笔全共振信号:")
        for sig in three_tf[:10]:  # 只显示前 10
            ts = datetime.datetime.fromtimestamp(sig["ts"]).strftime("%m-%d %H:%M")
            print(f"    {ts} | {sig['pname']:<16} | 入场=${sig['entry']:.2f} | "
                  f"SL=${sig['sl']:.2f} | {'WIN' if sig.get('win') else 'LOSS':>4} | "
                  f"盈亏=${sig.get('pnl', 0):+.1f}")
        if len(three_tf) > 10:
            print(f"    ... 还有 {len(three_tf) - 10} 笔")
    else:
        print("  (无全共振信号)")

    # 保存
    out_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(out_dir, "ta_lib_mtf_results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["形态", "时间", "TF数量", "有M30", "有M15", "入场价",
                     "止损价", "盈亏", "盈亏ATR", "止损命中", "胜"])
        for s in all_trades:
            ts_str = datetime.datetime.fromtimestamp(s["ts"]).strftime("%Y-%m-%d %H:%M")
            w.writerow([s["pname"], ts_str, s["tf_count"], s["m30"], s["m15"],
                        round(s["entry"], 2), round(s["sl"], 2),
                        round(s.get("pnl", 0), 2), round(s.get("pnl_atr", 0), 3),
                        "Y" if s.get("hit_sl") else "N",
                        "Y" if s.get("win") else "N"])
    print(f"\n结果已保存: {csv_path}")


if __name__ == "__main__":
    main()
