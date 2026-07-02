"""
TA-Lib K线形态 + 量能综合回测 v2
===================================
改进:
  1. 随机基准对照: 同位置、同频率随机信号, 消除趋势偏误
  2. 两种入场方式: close（形态闭市价）/ open（下一根开盘价）
  3. 统一 ATR 止损: entry +/- sl_atr × ATR, 命中即止损
  4. 统计显著性: 二项检验, 拒绝 H0: p = 随机基准
  5. 多维度评估: 胜率, 盈亏比, 期望值, 夏普比

用法:
  python research/ta_lib_pattern_backtest.py --tf H1 --entry close --sl-atr 1.5 --lookahead 3
  python research/ta_lib_pattern_backtest.py --tf H1 --entry open --sl-atr 1.5 --lookahead 3

输出:
  - 终端: 前 N 名 + 过滤器汇总 + 随机基准对比
  - CSV: research/ta_lib_results_<tf>_<entry>.csv
"""

import argparse
import csv
import datetime
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import talib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.database import get_conn

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

PATTERNS = {
    # 单根
    "CDLDOJI": "neutral", "CDLHAMMER": "bull", "CDLINVERTEDHAMMER": "bull",
    "CDLSHOOTINGSTAR": "bear", "CDLHANGINGMAN": "bear", "CDLMARUBOZU": "neutral",
    "CDLSPINNINGTOP": "neutral", "CDLBELTHOLD": "neutral", "CDLLONGLINE": "neutral",
    "CDLSHORTLINE": "neutral", "CDLHIGHWAVE": "neutral", "CDLRICKSHAWMAN": "neutral",
    "CDLDRAGONFLYDOJI": "bull", "CDLGRAVESTONEDOJI": "bear",
    "CDLLONGLEGGEDDOJI": "neutral", "CDLTAKURI": "bull",
    # 两根
    "CDLENGULFING": "neutral", "CDLHARAMI": "neutral", "CDLHARAMICROSS": "neutral",
    "CDLPIERCING": "bull", "CDLDARKCLOUDCOVER": "bear", "CDLKICKING": "neutral",
    "CDLSEPARATINGLINES": "neutral", "CDLTHRUSTING": "bull", "CDLMATCHINGLOW": "bull",
    # 三根
    "CDLMORNINGSTAR": "bull", "CDLEVENINGSTAR": "bear",
    "CDL3WHITESOLDIERS": "bull", "CDL3BLACKCROWS": "bear",
    "CDLMORNINGDOJISTAR": "bull", "CDLEVENINGDOJISTAR": "bear",
    "CDL3INSIDE": "neutral", "CDL3OUTSIDE": "neutral", "CDL3LINESTRIKE": "neutral",
    "CDL3STARSINSOUTH": "bull", "CDLADVANCEBLOCK": "bear",
    "CDLCOUNTERATTACK": "neutral", "CDLHIKKAKE": "neutral", "CDLHIKKAKEMOD": "neutral",
    "CDLHOMINGPIGEON": "bull", "CDLIDENTICAL3CROWS": "bear",
    "CDLLADDERBOTTOM": "bull", "CDLSTALLEDPATTERN": "bear",
    "CDLSTICKSANDWICH": "bull", "CDLUPSIDEGAP2CROWS": "bear",
    # 复杂
    "CDLABANDONEDBABY": "neutral", "CDLBREAKAWAY": "neutral",
    "CDLCONCEALBABYSWALL": "bull", "CDLGAPSIDESIDEWHITE": "bull",
    "CDLINNECK": "bear", "CDLONNECK": "bear", "CDLRISEFALL3METHODS": "neutral",
    "CDLTASUKIGAP": "bull", "CDLUNIQUE3RIVER": "bull", "CDLXSIDEGAP3METHODS": "neutral",
}

FILTERS = {
    "none": "无",
    "rsi_oversold": "RSI<30",
    "rsi_overbought": "RSI>70",
    "atr_high": "ATR>70%分位",
    "atr_low": "ATR<30%分位",
    "trend_up": "价>EMA20",
    "trend_down": "价<EMA20",
    "rsi_mid_oversold": "RSI30~50+多",
    "rsi_mid_overbought": "RSI50~70+空",
}


@dataclass
class TradeResult:
    win: bool
    pnl: float          # 绝对盈亏 ($)
    pnl_atr: float      # 盈亏 / ATR 倍数
    hit_sl: bool        # 是否被止损


@dataclass
class PatternResult:
    pattern: str = ""
    direction: str = ""
    filter_name: str = ""
    n_signals: int = 0       # 原始信号数
    n_filtered: int = 0      # 过滤器保留后的信号数
    n_trades: int = 0        # 实际进入统计的交易数
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    random_wr: float = 0.0   # 随机基准胜率
    z_score: float = 0.0     # 相对随机基准的 Z 值
    significant: bool = False
    avg_pnl: float = 0.0
    avg_pnl_atr: float = 0.0
    profit_factor: float = 0.0
    hit_sl_rate: float = 0.0
    avg_move_usd: float = 0.0


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

def load_data(timeframe: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume "
        "FROM ohlcv WHERE timeframe = ? ORDER BY timestamp",
        (timeframe,),
    ).fetchall()
    if not rows:
        print(f"[错误] timeframe {timeframe} 无数据")
        sys.exit(1)
    arr = np.array([(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows],
                   dtype=[("ts", "i8"), ("o", "f8"), ("h", "f8"),
                          ("l", "f8"), ("c", "f8"), ("v", "f8")])
    print(f"  {timeframe}: {len(arr)} 根 K 线 "
          f"({datetime.datetime.fromtimestamp(arr[0]['ts']).strftime('%Y-%m-%d')} ~ "
          f"{datetime.datetime.fromtimestamp(arr[-1]['ts']).strftime('%Y-%m-%d')})")
    return arr


def compute_indicators(o, h, l, c):
    ind = {}
    ind["rsi"] = talib.RSI(c, timeperiod=14)
    atr = talib.ATR(h, l, c, timeperiod=14)
    ind["atr"] = atr

    # ATR 百分位 (滚动60)
    atr_pct = np.full_like(atr, np.nan)
    for i in range(60, len(atr)):
        atr_pct[i] = 1.0 if atr[i] > np.percentile(atr[i - 60:i], 70) else 0.0
    ind["atr_pct"] = atr_pct

    # ATR 扩张比 (当前/前20均值)
    atr_exp = np.full_like(atr, np.nan)
    for i in range(20, len(atr)):
        atr_exp[i] = atr[i] / max(np.mean(atr[i - 20:i]), 0.01)
    ind["atr_exp"] = atr_exp

    ind["ema20"] = talib.EMA(c, timeperiod=20)
    return ind


def detect_patterns(o, h, l, c):
    results = {}
    for pname in PATTERNS:
        fn = getattr(talib, pname)
        try:
            sig = fn(o, h, l, c)
        except TypeError:
            try:
                sig = fn(h, l, c)
            except TypeError:
                continue
        results[pname] = sig
    return results


# ---------------------------------------------------------------------------
# 过滤器
# ---------------------------------------------------------------------------

def check_filter(idx, ind, close_arr, filter_name, sig_dir):
    """sig_dir: 信号方向 'bull'/'bear', 用于 RSI+方向组合过滤器"""
    if filter_name == "none":
        return True
    rsi = ind["rsi"][idx]
    atr = ind["atr"][idx]
    atr_pct = ind["atr_pct"][idx]
    atr_exp = ind["atr_exp"][idx]
    ema20 = ind["ema20"][idx]

    if filter_name == "rsi_oversold":
        return not np.isnan(rsi) and rsi < 30
    elif filter_name == "rsi_overbought":
        return not np.isnan(rsi) and rsi > 70
    elif filter_name == "atr_high":
        return not np.isnan(atr_pct) and atr_pct > 0
    elif filter_name == "atr_low":
        return not np.isnan(atr_pct) and atr_pct == 0
    elif filter_name == "trend_up":
        return not np.isnan(ema20) and close_arr[idx] > ema20
    elif filter_name == "trend_down":
        return not np.isnan(ema20) and close_arr[idx] < ema20
    elif filter_name == "rsi_mid_oversold":
        return not np.isnan(rsi) and 30 <= rsi <= 50 and sig_dir == "bull"
    elif filter_name == "rsi_mid_overbought":
        return not np.isnan(rsi) and 50 <= rsi <= 70 and sig_dir == "bear"
    return False


# ---------------------------------------------------------------------------
# 单笔交易逻辑
# ---------------------------------------------------------------------------

def simulate_trade(data, atr_arr, idx, direction, entry_mode, sl_atr, lookahead):
    """
    模拟一笔交易。
    direction: 'bull' (做多) / 'bear' (做空)
    entry_mode: 'close' / 'open'
    sl_atr: 止损倍数 (1.5 表示 1.5 × ATR)
    lookahead: 持仓 K 线数
    atr_arr: 预计算的 ATR 数组

    返回 TradeResult。
    """
    n = len(data)
    if idx + lookahead + 1 >= n:
        return None

    # 入场价
    if entry_mode == "close":
        entry = data[idx]["c"]
        sl_base_idx = idx
    else:
        entry = data[idx + 1]["o"]
        sl_base_idx = idx + 1

    atr_val = max(atr_arr[sl_base_idx], 0.1)

    # 止损价
    if direction == "bull":
        sl = entry - sl_atr * atr_val
    else:
        sl = entry + sl_atr * atr_val

    # 检查持仓期内是否命中止损
    start = idx + 1 if entry_mode == "close" else idx + 2
    end = min(start + lookahead, n)

    hit_sl = False
    hit_idx = -1
    for j in range(start, end):
        if direction == "bull":
            if data[j]["l"] <= sl:
                hit_sl = True
                hit_idx = j
                break
        else:
            if data[j]["h"] >= sl:
                hit_sl = True
                hit_idx = j
                break

    # 平仓价
    if hit_sl:
        exit_price = sl
        exit_atr_idx = hit_idx
    else:
        exit_price = data[end - 1]["c"]
        exit_atr_idx = end - 1

    # 盈亏
    atr_exit = max(atr_arr[exit_atr_idx], 0.1)
    if direction == "bull":
        pnl = exit_price - entry
    else:
        pnl = entry - exit_price

    if np.isnan(entry) or np.isnan(exit_price):
        return None

    win = pnl > 0

    return TradeResult(
        win=win,
        pnl=pnl,
        pnl_atr=pnl / atr_exit if atr_exit > 0 else 0,
        hit_sl=hit_sl,
    )


# ---------------------------------------------------------------------------
# 随机基准 (per-signal permutation)
# ---------------------------------------------------------------------------

def random_baseline(data, atr_arr, signal_indices, directions, entry_mode, sl_atr, lookahead):
    """
    对每个真实信号, 生成一个随机信号 (保持位置, 随机方向).
    返回与信号数量相等的 TradeResult 列表.
    """
    results = []
    for idx, orig_dir in zip(signal_indices, directions):
        rand_dir = "bull" if np.random.random() < 0.5 else "bear"
        tr = simulate_trade(data, atr_arr, idx, rand_dir, entry_mode, sl_atr, lookahead)
        if tr is not None:
            results.append(tr)
    return results


# ---------------------------------------------------------------------------
# 统计显著性 (二项检验, H0: p <= random_wr)
# ---------------------------------------------------------------------------

def binomial_significance(wins, n, random_p):
    """计算相对随机基准的显著性 Z 值和 p 值"""
    if n <= 1 or random_p <= 0:
        return 0.0, False
    p_obs = wins / n
    # Z = (p_obs - p_null) / sqrt(p_null * (1-p_null) / n)
    se = math.sqrt(random_p * (1 - random_p) / n)
    if se < 1e-6:
        return 0.0, False
    z = (p_obs - random_p) / se
    # 单侧检验: 显著 (p<0.05) 当 z > 1.645
    significant = z > 1.645
    return z, significant


# ---------------------------------------------------------------------------
# 数据准备: 预计算指标 (避免在循环中重复计算)
# ---------------------------------------------------------------------------

_INDICATORS_CACHE = {}


def get_indicators(data):
    """缓存指标数据, 避免重复计算"""
    key = id(data)
    if key not in _INDICATORS_CACHE:
        _INDICATORS_CACHE[key] = compute_indicators(data["o"], data["h"], data["l"], data["c"])
    return _INDICATORS_CACHE[key]


# ---------------------------------------------------------------------------
# 主回测
# ---------------------------------------------------------------------------

def run_backtest(timeframe, entry_mode, sl_atr, lookahead, min_signals, random_seed=42,
                 n_random_iterations=10):
    """运行回测, 返回 PatternResult 列表."""
    np.random.seed(random_seed)

    print(f"\n{'='*65}")
    print(f"TA-Lib K线形态回测 v2 | {timeframe} | 入场={entry_mode} | "
          f"SL={sl_atr}×ATR | 前瞻={lookahead}根")
    print(f"{'='*65}")

    data = load_data(timeframe)
    o, h, l, c = data["o"], data["h"], data["l"], data["c"]
    n = len(data)

    # 检测形态
    all_sigs = detect_patterns(o, h, l, c)
    active = {k: v for k, v in all_sigs.items() if np.any(v != 0)}
    print(f"  有信号形态: {len(active)} / {len(PATTERNS)}")

    # 预计算指标
    ind = compute_indicators(o, h, l, c)
    atr_arr = ind["atr"]
    _INDICATORS_CACHE[id(data)] = ind

    results = []
    total_configs = 0

    for pname, sig_arr in sorted(active.items()):
        base_dir = PATTERNS.get(pname, "neutral")

        for fname in FILTERS:
            total_configs += 1

            # 收集信号
            signal_indices = []
            signal_dirs = []
            for i in range(lookahead + 1, n - lookahead - 1):
                raw = sig_arr[i]
                if raw == 0:
                    continue
                sig_dir = "bull" if raw > 0 else "bear"
                eff_dir = base_dir if base_dir != "neutral" else sig_dir

                # 应用过滤器
                if not check_filter(i, ind, c, fname, eff_dir):
                    continue

                signal_indices.append(i)
                signal_dirs.append(eff_dir)

            n_filtered = len(signal_indices)
            if n_filtered < min_signals:
                continue

            # 执行交易
            trades = []
            for idx, d in zip(signal_indices, signal_dirs):
                tr = simulate_trade(data, atr_arr, idx, d, entry_mode, sl_atr, lookahead)
                if tr is not None:
                    trades.append(tr)

            if not trades:
                continue

            # 统计
            wins = sum(1 for t in trades if t.win)
            n_trades = len(trades)
            win_rate = wins / n_trades * 100
            avg_pnl = np.mean([t.pnl for t in trades])
            avg_pnl_atr = np.mean([t.pnl_atr for t in trades])
            hit_sl_rate = sum(1 for t in trades if t.hit_sl) / n_trades * 100

            gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
            gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

            # 随机基准 (n_random_iterations 次, 取平均)
            random_wrs = []
            for _ in range(n_random_iterations):
                rt = random_baseline(data, atr_arr, signal_indices, signal_dirs,
                                     entry_mode, sl_atr, lookahead)
                if rt:
                    random_wrs.append(sum(1 for t in rt if t.win) / len(rt) * 100)
            random_wr = np.mean(random_wrs) if random_wrs else 50.0

            # 统计显著性
            z_score, significant = binomial_significance(wins, n_trades, random_wr / 100)

            # 平均波动 (形态 K 线到持仓结束的价格变动绝对值)
            moves = []
            for idx in signal_indices:
                end = min(idx + lookahead + 1, n)
                if end - idx > 1:
                    moves.append(abs(c[end - 1] - c[idx]))
            avg_move = np.mean(moves) if moves else 0

            results.append(PatternResult(
                pattern=pname,
                direction=signal_dirs[0] if signal_dirs else "",
                filter_name=fname,
                n_signals=int(np.sum(sig_arr != 0)),
                n_filtered=n_filtered,
                n_trades=n_trades,
                wins=wins,
                losses=n_trades - wins,
                win_rate=round(win_rate, 1),
                random_wr=round(random_wr, 1),
                z_score=round(z_score, 2),
                significant=significant,
                avg_pnl=round(avg_pnl, 2),
                avg_pnl_atr=round(avg_pnl_atr, 3),
                profit_factor=round(profit_factor, 2),
                hit_sl_rate=round(hit_sl_rate, 1),
                avg_move_usd=round(avg_move, 2),
            ))

    # 排序: 先显著, 再按 Z 值降序
    results.sort(key=lambda r: (r.significant, r.z_score), reverse=True)

    return results


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def print_results(results, top_n=30):
    if not results:
        print("\n(无有效结果)")
        return

    sig_count = sum(1 for r in results if r.significant)
    print(f"\n  显著 (p<0.05): {sig_count}/{len(results)}")

    # 主表
    header = (f"{'形态':<22} {'方向':<6} {'过滤器':<14} {'交易数':<7} {'胜率':<7} "
              f"{'随机WR':<8} {'Z值':<7} {'平均盈亏':<9} {'盈亏/ATR':<9} {'盈亏比':<7}")
    sep = "-" * len(header)
    print(f"\n{sep}")
    print(f"{'=== 前 ' + str(min(top_n, len(results))) + ' 名 (按显著+Z值排序) ===':^{len(header)}}")
    print(sep)
    print(header)
    print(sep)

    display = results[:top_n]
    for r in display:
        sig_mark = "**" if r.significant else "  "
        avg_s = f"${r.avg_pnl:+.1f}" if abs(r.avg_pnl) < 1000 else f"${r.avg_pnl:+.0f}"
        print(f"{r.pattern:<22} {r.direction:<6} {r.filter_name:<14} {r.n_trades:<7} "
              f"{r.win_rate:<6.1f}% {r.random_wr:<6.1f}%  {sig_mark}{r.z_score:<+5.2f} "
              f"{avg_s:<9} {r.avg_pnl_atr:<+8.3f} {r.profit_factor:<7.2f}")
    print(sep)

    # 达标统计
    qualified = sum(1 for r in results if r.significant and r.win_rate >= 60)
    print(f"\n  达标 (显著+胜率>=60%): {qualified}/{len(results)}")

    # 按过滤器汇总
    print(f"\n--- 按过滤器汇总 (显著组合的平均值) ---")
    fs = defaultdict(list)
    for r in results:
        if r.significant:
            fs[r.filter_name].append(r)
    for fname, items in sorted(fs.items()):
        avg_wr = np.mean([r.win_rate for r in items])
        avg_z = np.mean([r.z_score for r in items])
        avg_pf = np.mean([r.profit_factor for r in items if r.profit_factor != float("inf")])
        label = FILTERS.get(fname, fname)
        print(f"  {fname:<14} ({label}): {len(items):2d}组合, "
              f"平均胜率={avg_wr:.1f}%, Z={avg_z:+.2f}, 盈亏比={avg_pf:.2f}")

    # 各形态最佳
    print(f"\n--- 各形态最佳 (显著+最高Z值) ---")
    best_per_pat = {}
    for r in results:
        if r.significant:
            if r.pattern not in best_per_pat or r.z_score > best_per_pat[r.pattern][0]:
                best_per_pat[r.pattern] = (r.z_score, r.win_rate, r.filter_name,
                                            r.n_trades, r.avg_pnl_atr)

    sorted_best = sorted(best_per_pat.items(), key=lambda x: x[1][0], reverse=True)
    for pname, (z, wr, fn, n, avg_a) in sorted_best[:15]:
        print(f"  {pname:<22} Z={z:+5.2f} 胜率={wr:.1f}% [{fn}] n={n} 盈亏/ATR={avg_a:+.3f}")

    # 随机基准 vs 真实 对比摘要
    print(f"\n--- 真实性检验 (真实胜率 vs 随机基准) ---")
    real_wrs = [r.win_rate for r in results]
    rand_wrs = [r.random_wr for r in results]
    print(f"  真实平均胜率: {np.mean(real_wrs):.1f}%")
    print(f"  随机平均胜率: {np.mean(rand_wrs):.1f}%")
    delta = np.mean([r.win_rate - r.random_wr for r in results])
    print(f"  平均差值: {delta:+.1f}%")
    outperforming = sum(1 for r in results if r.win_rate > r.random_wr)
    print(f"  优于随机: {outperforming}/{len(results)} ({outperforming/len(results)*100:.0f}%)")


def save_results(results, filepath):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "形态", "方向", "过滤器", "原始信号", "过滤后", "交易数",
            "胜", "负", "胜率%", "随机胜率%", "Z值", "显著",
            "平均盈亏", "盈亏/ATR", "盈亏比", "止损率%", "平均波动$"
        ])
        for r in results:
            w.writerow([
                r.pattern, r.direction, r.filter_name, r.n_signals, r.n_filtered,
                r.n_trades, r.wins, r.losses, r.win_rate, r.random_wr,
                r.z_score, "Y" if r.significant else "N",
                round(r.avg_pnl, 2), round(r.avg_pnl_atr, 3),
                r.profit_factor, r.hit_sl_rate, r.avg_move_usd,
            ])
    print(f"\n结果已保存: {filepath}")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="TA-Lib K线形态回测 v2")
    parser.add_argument("--tf", default="H1", choices=["H1", "M30", "M15"])
    parser.add_argument("--entry", default="close", choices=["close", "open"])
    parser.add_argument("--sl-atr", type=float, default=1.5, help="止损 ATR 倍数")
    parser.add_argument("--lookahead", type=int, default=3, help="持仓 K 线数")
    parser.add_argument("--min-signals", type=int, default=15, help="最低信号数")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    results = run_backtest(
        timeframe=args.tf,
        entry_mode=args.entry,
        sl_atr=args.sl_atr,
        lookahead=args.lookahead,
        min_signals=args.min_signals,
    )

    print_results(results, top_n=args.top)

    if args.save:
        out_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(out_dir,
                                f"ta_lib_results_{args.tf}_{args.entry}_sl{args.sl_atr}.csv")
        save_results(results, csv_path)


if __name__ == "__main__":
    main()
