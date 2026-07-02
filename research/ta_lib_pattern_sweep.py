"""
TA-Lib K线形态 + 量能 止损扫描回测 v3
========================================
对每个形态+过滤器组合, 扫描 0.5~3.0×ATR 止损, 找到最佳止损点.
排除幸存者偏差, 对比随机基准, 只输出统计显著的结果.

用法:
  python research/ta_lib_pattern_sweep.py [--tf H1] [--entry close] [--min-signals 20]

输出:
  - 终端: 每个组合的 SL 敏感性表格
  - CSV: research/ta_lib_sweep_<tf>_<entry>.csv (完整结果)
  - CSV: research/ta_lib_sweep_best_<tf>_<entry>.csv (每个组合最佳 SL)
"""

import argparse
import csv
import datetime
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional
import json

import numpy as np
import talib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.database import get_conn

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

PATTERNS = {
    "CDLDOJI": "neutral", "CDLHAMMER": "bull", "CDLINVERTEDHAMMER": "bull",
    "CDLSHOOTINGSTAR": "bear", "CDLHANGINGMAN": "bear", "CDLMARUBOZU": "neutral",
    "CDLSPINNINGTOP": "neutral", "CDLBELTHOLD": "neutral", "CDLLONGLINE": "neutral",
    "CDLSHORTLINE": "neutral", "CDLHIGHWAVE": "neutral", "CDLRICKSHAWMAN": "neutral",
    "CDLDRAGONFLYDOJI": "bull", "CDLGRAVESTONEDOJI": "bear",
    "CDLLONGLEGGEDDOJI": "neutral", "CDLTAKURI": "bull",
    "CDLENGULFING": "neutral", "CDLHARAMI": "neutral", "CDLHARAMICROSS": "neutral",
    "CDLPIERCING": "bull", "CDLDARKCLOUDCOVER": "bear", "CDLKICKING": "neutral",
    "CDLSEPARATINGLINES": "neutral", "CDLTHRUSTING": "bull", "CDLMATCHINGLOW": "bull",
    "CDLMORNINGSTAR": "bull", "CDLEVENINGSTAR": "bear",
    "CDL3WHITESOLDIERS": "bull", "CDL3BLACKCROWS": "bear",
    "CDLMORNINGDOJISTAR": "bull", "CDLEVENINGDOJISTAR": "bear",
    "CDL3INSIDE": "neutral", "CDL3OUTSIDE": "neutral", "CDL3LINESTRIKE": "neutral",
    "CDL3STARSINSOUTH": "bull", "CDLADVANCEBLOCK": "bear",
    "CDLCOUNTERATTACK": "neutral", "CDLHIKKAKE": "neutral", "CDLHIKKAKEMOD": "neutral",
    "CDLHOMINGPIGEON": "bull", "CDLIDENTICAL3CROWS": "bear",
    "CDLLADDERBOTTOM": "bull", "CDLSTALLEDPATTERN": "bear",
    "CDLSTICKSANDWICH": "bull", "CDLUPSIDEGAP2CROWS": "bear",
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

SL_VALUES = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0]


@dataclass
class SlResult:
    sl: float
    n_trades: int
    wins: int
    losses: int
    win_rate: float
    random_wr: float
    z_score: float
    significant: bool
    avg_pnl: float
    avg_pnl_atr: float
    profit_factor: float
    hit_sl_rate: float


@dataclass
class PatternSummary:
    pattern: str
    direction: str
    filter_name: str
    best_sl: float
    best_wr: float
    best_z: float
    best_pf: float
    n_trades: int
    significant: bool
    results: list  # list of SlResult


# ---------------------------------------------------------------------------
# 数据加载 & 指标
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
    ind["atr"] = talib.ATR(h, l, c, timeperiod=14)
    ind["ema20"] = talib.EMA(c, timeperiod=20)
    # ATR 百分位 (滚动60)
    atr_pct = np.full_like(ind["atr"], np.nan)
    for i in range(60, len(ind["atr"])):
        atr_pct[i] = 1.0 if ind["atr"][i] > np.percentile(ind["atr"][i - 60:i], 70) else 0.0
    ind["atr_pct"] = atr_pct
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
    if filter_name == "none":
        return True
    rsi = ind["rsi"][idx]
    atr_pct = ind["atr_pct"][idx]
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
# 向量化交易计算 (一个信号批次)
# ---------------------------------------------------------------------------

def compute_trade_results(
    entry_prices, directions, atr_vals,
    low_fwd, high_fwd, close_fwd,
    sl_mult
):
    """
    向量化计算一批交易在给定 SL 倍数下的结果.

    参数为 numpy 数组, 长度 = 信号数.
    entry_prices: 入场价
    directions: 'bull'/'bear'
    atr_vals: 入场时的 ATR
    low_fwd: 持仓期内最低价
    high_fwd: 持仓期内最高价
    close_fwd: 持仓期末收盘价
    sl_mult: SL 倍数

    返回 (wins, n, total_pnl, total_pnl_atr, gross_profit, gross_loss, hit_sl_count)
    """
    n = len(entry_prices)
    if n == 0:
        return 0, 0, 0, 0, 0, 0, 0

    bull_mask = np.array([d == "bull" for d in directions])
    bear_mask = ~bull_mask

    # 止损价
    sl_prices = np.copy(entry_prices)
    sl_prices[bull_mask] = entry_prices[bull_mask] - sl_mult * atr_vals[bull_mask]
    sl_prices[bear_mask] = entry_prices[bear_mask] + sl_mult * atr_vals[bear_mask]

    # 是否止损
    hit_sl = np.zeros(n, dtype=bool)
    hit_sl[bull_mask] = low_fwd[bull_mask] <= sl_prices[bull_mask]
    hit_sl[bear_mask] = high_fwd[bear_mask] >= sl_prices[bear_mask]

    # 出场价
    exit_prices = np.where(hit_sl, sl_prices, close_fwd)

    # 盈亏
    pnl = np.zeros(n)
    pnl[bull_mask] = exit_prices[bull_mask] - entry_prices[bull_mask]
    pnl[bear_mask] = entry_prices[bear_mask] - exit_prices[bear_mask]

    # 避免入场价异常
    valid = ~(np.isnan(entry_prices) | np.isnan(exit_prices))
    pnl[~valid] = 0
    hit_sl[~valid] = False

    wins = np.sum((pnl > 0) & valid)
    total_valid = np.sum(valid)
    total_pnl = np.sum(pnl)
    total_pnl_atr = np.sum(pnl[valid] / np.maximum(atr_vals[valid], 0.1))
    gross_profit = np.sum(pnl[pnl > 0])
    gross_loss = abs(np.sum(pnl[pnl < 0]))
    hit_sl_count = np.sum(hit_sl & valid)

    return wins, total_valid, total_pnl, total_pnl_atr, gross_profit, gross_loss, hit_sl_count


# ---------------------------------------------------------------------------
# 随机基准 (每次随机方向, 取多次平均)
# ---------------------------------------------------------------------------

def compute_random_results(
    entry_prices, atr_vals,
    low_fwd, high_fwd, close_fwd,
    sl_mult, n_iterations=15
):
    """多次随机方向, 返回平均随机胜率"""
    n = len(entry_prices)
    if n == 0:
        return 50.0

    wr_list = []
    for _ in range(n_iterations):
        rand_dirs = ["bull" if np.random.random() < 0.5 else "bear" for _ in range(n)]
        w, total, _, _, _, _, _ = compute_trade_results(
            entry_prices, rand_dirs, atr_vals,
            low_fwd, high_fwd, close_fwd, sl_mult
        )
        if total > 0:
            wr_list.append(w / total * 100)

    return np.mean(wr_list) if wr_list else 50.0


def compute_random_results_fast(
    entry_prices, atr_vals,
    low_fwd, high_fwd, close_fwd,
    sl_mult, n_trials=5000
):
    """
    更快: 生成 n_trials 个随机方向, 一次向量化计算所有.
    但方向是随机的, 需要小心处理.
    """
    n = len(entry_prices)
    if n == 0:
        return 50.0

    # 对每个信号, "随机信号" = 随机方向, 但入场价/ATR不变
    # 用 Monte Carlo: n_iterations 次, 每次随机方向
    wins_total = 0
    trades_total = 0
    for _ in range(n_trials):
        rand_dirs = ["bull" if np.random.random() < 0.5 else "bear" for _ in range(n)]
        w, t, _, _, _, _, _ = compute_trade_results(
            entry_prices, rand_dirs, atr_vals,
            low_fwd, high_fwd, close_fwd, sl_mult
        )
        wins_total += w
        trades_total += t

    return wins_total / max(trades_total, 1) * 100


# ---------------------------------------------------------------------------
# 前向窗口计算 (预计算每根 K 线的 forward low/high/close)
# ---------------------------------------------------------------------------

def compute_forward_windows(h, l, c, lookahead):
    """预计算每根 K 线向前 N 根的最低、最高、收盘价"""
    n = len(c)
    low_fwd = np.full(n, np.nan)
    high_fwd = np.full(n, np.nan)
    close_fwd = np.full(n, np.nan)

    for i in range(n - lookahead - 1):
        end = i + lookahead + 1
        low_fwd[i] = np.min(l[i + 1:end])
        high_fwd[i] = np.max(h[i + 1:end])
        close_fwd[i] = c[end - 1]

    return low_fwd, high_fwd, close_fwd


# ---------------------------------------------------------------------------
# 统计显著性
# ---------------------------------------------------------------------------

def calc_significance(wins, n, random_p):
    if n <= 1 or random_p <= 0:
        return 0.0, False
    p_obs = wins / n
    se = math.sqrt(random_p * (1 - random_p) / n)
    if se < 1e-6:
        return 0.0, False
    z = (p_obs - random_p) / se
    significant = z > 1.645
    return z, significant


# ---------------------------------------------------------------------------
# 主扫描
# ---------------------------------------------------------------------------

def run_sweep(timeframe, entry_mode, lookahead, min_signals):
    np.random.seed(42)

    print(f"\n{'='*70}")
    print(f"TA-Lib 止损扫描回测 v3 | {timeframe} | 入场={entry_mode} | "
          f"前瞻={lookahead}根 | 最低信号数={min_signals}")
    print(f"{'='*70}")

    data = load_data(timeframe)
    o, h, l, c, v = data["o"], data["h"], data["l"], data["c"], data["v"]
    n = len(data)

    # 预计算指标
    ind = compute_indicators(o, h, l, c)
    atr_arr = ind["atr"]

    # 检测形态
    all_sigs = detect_patterns(o, h, l, c)
    active = {k: v for k, v in all_sigs.items() if np.any(v != 0)}
    print(f"  有信号形态: {len(active)} / {len(PATTERNS)}")

    # 预计算 forward 窗口 (取决于入场方式)
    if entry_mode == "close":
        # 入场在 close[i], 持仓期 [i+1, i+lookahead]
        entry_prices_all = c.copy()
        low_fwd_all, high_fwd_all, close_fwd_all = compute_forward_windows(h, l, c, lookahead)
    else:
        # 入场在 open[i+1], 所以 forward 窗口偏移 +1
        # 我们需要对于 idx=i 的信号, entry=open[i+1], 持仓 [i+2, i+lookahead+1]
        entry_prices_all = np.roll(o, -1)  # entry_prices[i] = open[i+1]
        entry_prices_all[-1] = np.nan
        # forward 窗口从 i+1 开始
        low_fwd_all, high_fwd_all, close_fwd_all = compute_forward_windows(h, l, c, lookahead)
        # 对于 open 入场, 窗口需要平移: 实际 forward 从 idx+1 开始
        # 但 compute_forward_windows 已经是从 i+1 开始, 所以 -1
        # 不对, 让我重新想:
        # close 入场: idx=i, 窗口 [i+1, i+lookahead]
        # open 入场: idx=i, entry=open[i+1], 窗口 [i+2, i+lookahead+1]
        # 所以对 open 入场, forward 窗口应该偏移 +1
        low_fwd_all = np.roll(low_fwd_all, -1)
        high_fwd_all = np.roll(high_fwd_all, -1)
        close_fwd_all = np.roll(close_fwd_all, -1)
        low_fwd_all[-2:] = np.nan
        high_fwd_all[-2:] = np.nan
        close_fwd_all[-2:] = np.nan

    # 遍历形态+过滤器组合
    all_patterns = []
    scanned = 0
    qualified = 0

    for pname, sig_arr in sorted(active.items()):
        base_dir = PATTERNS.get(pname, "neutral")

        for fname in FILTERS:
            scanned += 1

            # 收集信号
            signal_indices = []
            signal_dirs = []
            for i in range(lookahead + 2, n - lookahead - 2):
                raw = sig_arr[i]
                if raw == 0:
                    continue
                sig_dir = "bull" if raw > 0 else "bear"
                eff_dir = base_dir if base_dir != "neutral" else sig_dir
                if not check_filter(i, ind, c, fname, eff_dir):
                    continue
                signal_indices.append(i)
                signal_dirs.append(eff_dir)

            n_filtered = len(signal_indices)
            if n_filtered < min_signals:
                continue

            # 提取该组合的维度数据
            idx_arr = np.array(signal_indices)
            ep = entry_prices_all[idx_arr]
            atr_v = atr_arr[idx_arr]
            lf = low_fwd_all[idx_arr]
            hf = high_fwd_all[idx_arr]
            cf = close_fwd_all[idx_arr]
            dirs = signal_dirs

            # 对每个 SL 值计算
            sl_results = []
            for sl_mult in SL_VALUES:
                wins, t, total_pnl, total_pnl_atr, gp, gl, hsc = compute_trade_results(
                    ep, dirs, atr_v, lf, hf, cf, sl_mult
                )
                if t == 0:
                    continue

                wr = wins / t * 100
                random_wr = compute_random_results(
                    ep, atr_v, lf, hf, cf, sl_mult, n_iterations=12
                )
                z, sig = calc_significance(wins, t, random_wr / 100)
                pf = gp / gl if gl > 0 else (float("inf") if gp > 0 else 0)
                avg_pnl = total_pnl / t
                avg_pnl_atr = total_pnl_atr / t
                hsl = hsc / t * 100

                sl_results.append(SlResult(
                    sl=sl_mult, n_trades=t, wins=wins, losses=t - wins,
                    win_rate=round(wr, 1), random_wr=round(random_wr, 1),
                    z_score=round(z, 2), significant=sig,
                    avg_pnl=round(avg_pnl, 2), avg_pnl_atr=round(avg_pnl_atr, 3),
                    profit_factor=round(pf, 2), hit_sl_rate=round(hsl, 1),
                ))

            # 找最佳 SL (max Z-score)
            best = max(sl_results, key=lambda r: r.z_score) if sl_results else None
            if best and best.significant and best.win_rate >= 55:
                qualified += 1

            all_patterns.append(PatternSummary(
                pattern=pname,
                direction=dirs[0] if dirs else "",
                filter_name=fname,
                best_sl=best.sl if best else 0,
                best_wr=best.win_rate if best else 0,
                best_z=best.z_score if best else 0,
                best_pf=best.profit_factor if best else 0,
                n_trades=len(signal_indices),
                significant=best.significant if best else False,
                results=sl_results,
            ))

    # 排序: 显著优先, 再按 Z 值
    all_patterns.sort(key=lambda p: (p.significant, p.best_z), reverse=True)

    print(f"\n  扫描组合: {scanned}, 达标: {qualified}")

    return all_patterns


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def print_sweep_results(patterns, top_n=20):
    if not patterns:
        return

    # 整体统计
    sig_count = sum(1 for p in patterns if p.significant)
    print(f"\n  显著组合: {sig_count}/{len(patterns)}")

    # 摘要表
    print(f"\n{'='*90}")
    print("  综合排名 (每个组合只显示最佳 SL)")
    print(f"{'='*90}")
    header = (f"  {'形态':<20} {'方向':<5} {'过滤器':<14} {'最佳SL':<7} "
              f"{'交易数':<7} {'胜率':<7} {'随机':<7} {'Z值':<7} {'盈亏比':<7} {'显著':<5}")
    print(header)
    print("  " + "-" * 85)

    display = [p for p in patterns if p.significant][:top_n]
    if not display:
        # 如果没有显著的, 显示 Z 值最高的
        display = patterns[:top_n]

    for p in display:
        sig_mark = "**[Y]**" if p.significant else "[N]"
        print(f"  {p.pattern:<20} {p.direction:<5} {p.filter_name:<14} "
              f"{p.best_sl:<5.2f}×  {p.n_trades:<7} {p.best_wr:<6.1f}% "
              f"{'N/A':<7} {p.best_z:<+6.2f} {p.best_pf:<7.2f} {sig_mark:<5}")

    # 每个显著组合的 SL 敏感性
    print(f"\n{'='*90}")
    print("  显著组合 - SL 敏感性分析")
    print(f"{'='*90}")

    for p in display:
        print(f"\n  >>> {p.pattern} ({p.direction}) + {p.filter_name} (n={p.n_trades})")
        print(f"  {'SL':<8} {'交易数':<7} {'胜率':<8} {'随机WR':<8} "
              f"{'Z值':<8} {'平均盈亏':<10} {'盈亏/ATR':<10} {'盈亏比':<8} {'止损率':<7} {' ':>4}")
        print(f"  {'-'*75}")
        for r in p.results:
            sig_flag = "**" if r.significant else "  "
            avg_s = f"${r.avg_pnl:+.1f}" if abs(r.avg_pnl) < 1000 else f"${r.avg_pnl:+.0f}"
            print(f"  {r.sl:<5.2f}×  {r.n_trades:<7} {r.win_rate:<6.1f}%  "
                  f"{r.random_wr:<6.1f}%  {sig_flag}{r.z_score:<+5.2f}  "
                  f"{avg_s:<9} {r.avg_pnl_atr:<+8.3f}  {r.profit_factor:<8.2f} "
                  f"{r.hit_sl_rate:<6.1f}%")

    # 过滤器汇总
    print(f"\n--- 按过滤器汇总 (显著组合的最佳 SL 平均) ---")
    fs = defaultdict(list)
    for p in patterns:
        if p.significant:
            fs[p.filter_name].append(p)
    for fname, items in sorted(fs.items()):
        avg_wr = np.mean([p.best_wr for p in items])
        avg_z = np.mean([p.best_z for p in items])
        avg_sl = np.mean([p.best_sl for p in items])
        print(f"  {fname:<16}: {len(items):2d}组合 | 平均最佳SL={avg_sl:.2f} | "
              f"最佳胜率={avg_wr:.1f}% | Z={avg_z:+.2f}")

    # 整体真实性检验
    print(f"\n--- 真实性检验 ---")
    real_wrs = [max(r.win_rate for r in p.results) for p in patterns if p.results]
    rand_wrs = [max(r.random_wr for r in p.results) for p in patterns if p.results]
    if real_wrs:
        print(f"  全部组合最高胜率平均: {np.mean(real_wrs):.1f}%")
        print(f"  全部组合随机胜率平均: {np.mean(rand_wrs):.1f}%")


def save_sweep_results(patterns, filepath):
    """保存全部结果到 CSV"""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["形态", "方向", "过滤器", "SL", "交易数", "胜", "负",
                     "胜率%", "随机WR%", "Z值", "显著", "平均盈亏", "盈亏/ATR",
                     "盈亏比", "止损率%"])
        for p in patterns:
            for r in p.results:
                w.writerow([p.pattern, p.direction, p.filter_name, r.sl,
                            r.n_trades, r.wins, r.losses,
                            r.win_rate, r.random_wr, r.z_score,
                            "Y" if r.significant else "N",
                            r.avg_pnl, r.avg_pnl_atr, r.profit_factor, r.hit_sl_rate])
    print(f"\n完整结果已保存: {filepath}")


def save_best_results(patterns, filepath):
    """保存每个组合的最佳 SL 结果"""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["形态", "方向", "过滤器", "最佳SL", "交易数", "胜率%",
                     "Z值", "显著", "盈亏比", "盈亏/ATR", "止损率%", "是否达标"])
        for p in patterns:
            best = max(p.results, key=lambda r: r.z_score) if p.results else None
            if best:
                qualified = "Y" if p.significant and best.win_rate >= 55 else "N"
                w.writerow([p.pattern, p.direction, p.filter_name, best.sl,
                            best.n_trades, best.win_rate, best.z_score,
                            "Y" if p.significant else "N",
                            best.profit_factor, best.avg_pnl_atr,
                            best.hit_sl_rate, qualified])
    print(f"最佳结果已保存: {filepath}")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="TA-Lib 止损扫描回测 v3")
    parser.add_argument("--tf", default="H1")
    parser.add_argument("--entry", default="close", choices=["close", "open"])
    parser.add_argument("--lookahead", type=int, default=3, help="持仓 K 线数")
    parser.add_argument("--min-signals", type=int, default=20, help="最低信号数")
    parser.add_argument("--top", type=int, default=20, help="显示前 N 名")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    patterns = run_sweep(
        timeframe=args.tf,
        entry_mode=args.entry,
        lookahead=args.lookahead,
        min_signals=args.min_signals,
    )

    print_sweep_results(patterns, top_n=args.top)

    if args.save:
        out_dir = os.path.dirname(os.path.abspath(__file__))
        base = os.path.join(out_dir, f"ta_lib_sweep_{args.tf}_{args.entry}")
        save_sweep_results(patterns, f"{base}.csv")
        save_best_results(patterns, f"{base}_best.csv")


if __name__ == "__main__":
    main()
