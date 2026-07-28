"""
mfi_bb_m30 v8 vs v9 对比回测
============================
v8: BB扩张 3选2 保护 + 无 ADX 过滤
v9: 删除 BB扩张保护, 改 ADX>30 同向趋势硬过滤
    - 强下跌 (ADX>30 + close<bb_mid + MFI 向下) -> 禁做多
    - 强上涨 (ADX>30 + close>bb_mid + MFI 向上) -> 禁做空

输出: v8 vs v9 关键指标对比 + ADX>30 拦截效果分析
"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import logging
logging.basicConfig(level=logging.WARNING, stream=sys.stdout)

import numpy as np
import talib
from data.database import get_conn
from core.bridge import Candle
from datetime import datetime

COMMISSION = 0.5
LOT = 0.01
CONTRACT = 100
MIN_BARS = 100
BB_PERIOD = 20
BB_STD = 2.0
MFI_PERIOD = 14
ADX_PERIOD = 14
BB_EXPAND_THRESHOLD = 0.05

# 强制 UTF-8 输出
def _print(*a, **k):
    s = " ".join(str(x) for x in a)
    print(s, **k)

# ── 读取 M30 数据 ──
conn = get_conn()
rows = conn.execute(
    "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
).fetchall()
conn.close()
M30 = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in rows]

arr_high = np.array([c.high for c in M30], dtype=np.float64)
arr_low = np.array([c.low for c in M30], dtype=np.float64)
arr_close = np.array([c.close for c in M30], dtype=np.float64)
arr_vol = np.array([c.volume for c in M30], dtype=np.float64)

bb_u, bb_m, bb_l = talib.BBANDS(arr_close, timeperiod=BB_PERIOD, nbdevup=BB_STD, nbdevdn=BB_STD)
mfi_arr = talib.MFI(arr_high, arr_low, arr_close, arr_vol, timeperiod=MFI_PERIOD)
atr = talib.ATR(arr_high, arr_low, arr_close, timeperiod=14)
adx_arr = talib.ADX(arr_high, arr_low, arr_close, timeperiod=ADX_PERIOD)
pdi_arr = talib.PLUS_DI(arr_high, arr_low, arr_close, timeperiod=ADX_PERIOD)
ndi_arr = talib.MINUS_DI(arr_high, arr_low, arr_close, timeperiod=ADX_PERIOD)

bb_widths = bb_u - bb_l
widths_sma3 = talib.SMA(bb_widths, timeperiod=3)
bb_w_ratio = np.where(widths_sma3 > 0, bb_widths / widths_sma3, 1.0)
prev_w = np.concatenate([[bb_widths[0]], bb_widths[:-1]])
bb_w_dir = np.where(bb_widths > prev_w, 1, np.where(bb_widths < prev_w, -1, 0))
prev_mfi = np.concatenate([[mfi_arr[0]], mfi_arr[:-1]])
mfi_dir_arr = np.where(mfi_arr > prev_mfi, 1, np.where(mfi_arr < prev_mfi, -1, 0))

n_total = len(M30)


def fmt_ts(t):
    return datetime.fromtimestamp(int(t)).strftime("%m-%d %H:%M")


def stats(trades):
    """计算一组交易的统计指标"""
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    pnl = sum(t["pnl"] for t in trades)
    wr = len(wins) / n * 100 if n else 0
    aw = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    al = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = gp / gl if gl else 999
    longs = [t for t in trades if t["dir"] == "BUY"]
    shorts = [t for t in trades if t["dir"] == "SELL"]
    return {
        "n": n,
        "pnl": round(pnl, 2),
        "wr": wr,
        "pf": round(pf, 2),
        "aw": round(aw, 2),
        "al": round(al, 2),
        "longs": len(longs),
        "shorts": len(shorts),
        "long_pnl": round(sum(t["pnl"] for t in longs), 2),
        "short_pnl": round(sum(t["pnl"] for t in shorts), 2),
        "max_loss": round(min(t["pnl"] for t in trades), 2) if trades else 0,
        "max_win": round(max(t["pnl"] for t in trades), 2) if trades else 0,
        "avg_bars": round(sum(t["bars"] for t in trades) / n, 1) if n else 0,
        "win_n": len(wins),
        "loss_n": len(losses),
    }


def run_v8():
    """v8: BB扩张 3选2 保护 + 无 ADX 过滤"""
    trades = []
    running = 0.0
    peak = 0.0
    mdd = 0.0
    pos_dir = None
    ep = 0.0
    ei = 0
    trail = {}

    for i in range(MIN_BARS, n_total):
        cl = M30[i].close
        ts = int(M30[i].time)
        bbu = bb_u[i]; bbm = bb_m[i]; bbl = bb_l[i]
        mfi_i = mfi_arr[i]
        bwr = bb_w_ratio[i]; bwd = bb_w_dir[i]
        mfdir = mfi_dir_arr[i]
        adx_i = adx_arr[i]
        if not all(np.isfinite(x) for x in [bbu, bbm, bbl, mfi_i, bwr, adx_i]):
            continue

        # 出场
        if pos_dir is not None:
            is_buy = pos_dir == "BUY"
            td = trail
            ex = False; reason = None
            if is_buy:
                if not td["crossed"] and cl > bbu:
                    td["crossed"] = True
                if td["crossed"] and cl <= bbu + 0.01 and mfi_i > 50:
                    ex, reason = True, "顺势"
            else:
                if not td["crossed"] and cl < bbl:
                    td["crossed"] = True
                if td["crossed"] and cl >= bbl - 0.01 and mfi_i < 50:
                    ex, reason = True, "顺势"
            if not ex and not td["crossed"]:
                if is_buy and cl >= bbm:
                    ex, reason = True, "中轴"
                elif (not is_buy) and cl <= bbm:
                    ex, reason = True, "中轴"
            if not ex:
                hw = td["bw"] / 2
                if is_buy and cl >= ep + hw:
                    ex, reason = True, "半宽"
                elif (not is_buy) and cl <= ep - hw:
                    ex, reason = True, "半宽"
            if ex:
                pnl = (cl - ep) * CONTRACT * LOT - COMMISSION if is_buy else (ep - cl) * CONTRACT * LOT - COMMISSION
                trades.append({
                    "dir": pos_dir, "ep": round(ep, 2), "ex": round(cl, 2),
                    "pnl": round(pnl, 2), "bars": i - ei,
                    "adx_in": td.get("ax", 0), "reason": reason,
                    "entry_t": fmt_ts(M30[ei].time), "exit_t": fmt_ts(ts),
                })
                running += pnl
                if running > peak: peak = running
                if peak - running > mdd: mdd = peak - running
                pos_dir = None
                trail = {}

        # 入场 (v8: BB扩张 3选2 保护)
        if pos_dir is None:
            block_l = block_s = False
            s = 0
            if bwr > 1 + BB_EXPAND_THRESHOLD: s += 1
            if bwd == 1: s += 1
            if cl > bbm and mfdir in (1, 0): s += 1
            if cl < bbm and mfdir in (-1, 0): s += 1
            if s >= 2:
                if cl > bbm and mfdir in (1, 0): block_s = True
                if cl < bbm and mfdir in (-1, 0): block_l = True
            if cl < bbl and not block_l:
                pos_dir = "BUY"; ep = cl; ei = i
                trail = {"bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1)}
            elif cl > bbu and not block_s:
                pos_dir = "SELL"; ep = cl; ei = i
                trail = {"bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1)}

    if pos_dir:
        cl = M30[-1].close
        pnl = (cl - ep) * CONTRACT * LOT - COMMISSION if pos_dir == "BUY" else (ep - cl) * CONTRACT * LOT - COMMISSION
        trades.append({
            "dir": pos_dir, "ep": round(ep, 2), "ex": round(cl, 2),
            "pnl": round(pnl, 2), "bars": n_total - 1 - ei,
            "adx_in": trail.get("ax", 0), "reason": "END",
            "entry_t": fmt_ts(M30[ei].time), "exit_t": fmt_ts(M30[-1].time),
        })

    return trades, mdd


def run_v9():
    """v9: 删除 BB扩张保护, 改 ADX>30 同向趋势硬过滤"""
    trades = []
    running = 0.0
    peak = 0.0
    mdd = 0.0
    pos_dir = None
    ep = 0.0
    ei = 0
    trail = {}
    block_log = []  # 记录被拦截的笔

    for i in range(MIN_BARS, n_total):
        cl = M30[i].close
        ts = int(M30[i].time)
        bbu = bb_u[i]; bbm = bb_m[i]; bbl = bb_l[i]
        mfi_i = mfi_arr[i]
        mfdir = mfi_dir_arr[i]
        adx_i = adx_arr[i]
        if not all(np.isfinite(x) for x in [bbu, bbm, bbl, mfi_i, adx_i]):
            continue

        # 出场 (与 v8 相同)
        if pos_dir is not None:
            is_buy = pos_dir == "BUY"
            td = trail
            ex = False; reason = None
            if is_buy:
                if not td["crossed"] and cl > bbu:
                    td["crossed"] = True
                if td["crossed"] and cl <= bbu + 0.01 and mfi_i > 50:
                    ex, reason = True, "顺势"
            else:
                if not td["crossed"] and cl < bbl:
                    td["crossed"] = True
                if td["crossed"] and cl >= bbl - 0.01 and mfi_i < 50:
                    ex, reason = True, "顺势"
            if not ex and not td["crossed"]:
                if is_buy and cl >= bbm:
                    ex, reason = True, "中轴"
                elif (not is_buy) and cl <= bbm:
                    ex, reason = True, "中轴"
            if not ex:
                hw = td["bw"] / 2
                if is_buy and cl >= ep + hw:
                    ex, reason = True, "半宽"
                elif (not is_buy) and cl <= ep - hw:
                    ex, reason = True, "半宽"
            if ex:
                pnl = (cl - ep) * CONTRACT * LOT - COMMISSION if is_buy else (ep - cl) * CONTRACT * LOT - COMMISSION
                trades.append({
                    "dir": pos_dir, "ep": round(ep, 2), "ex": round(cl, 2),
                    "pnl": round(pnl, 2), "bars": i - ei,
                    "adx_in": td.get("ax", 0), "reason": reason,
                    "entry_t": fmt_ts(M30[ei].time), "exit_t": fmt_ts(ts),
                })
                running += pnl
                if running > peak: peak = running
                if peak - running > mdd: mdd = peak - running
                pos_dir = None
                trail = {}

        # 入场 (v9: ADX>30 同向硬过滤)
        if pos_dir is None:
            block_l = block_s = False
            block_reason = None
            if adx_i > 30:
                # 强下跌: ADX>30 + 价格<中轴 + MFI向下 -> 禁做多
                if cl < bbm and mfdir == -1:
                    block_l = True
                    block_reason = f"强下跌(ADX={adx_i:.0f} >30 + MFI↓ + P<中轴)"
                # 强上涨: ADX>30 + 价格>中轴 + MFI向上 -> 禁做空
                elif cl > bbm and mfdir == 1:
                    block_s = True
                    block_reason = f"强上涨(ADX={adx_i:.0f} >30 + MFI↑ + P>中轴)"

            raw_buy = cl < bbl
            raw_sell = cl > bbu
            if raw_buy and block_l:
                block_log.append({
                    "i": i, "dir": "BUY", "cl": round(cl, 2), "bbl": round(bbl, 2),
                    "adx": round(adx_i, 1), "mfi_dir": int(mfdir),
                    "reason": block_reason, "ts": fmt_ts(ts),
                })
            if raw_sell and block_s:
                block_log.append({
                    "i": i, "dir": "SELL", "cl": round(cl, 2), "bbu": round(bbu, 2),
                    "adx": round(adx_i, 1), "mfi_dir": int(mfdir),
                    "reason": block_reason, "ts": fmt_ts(ts),
                })

            if raw_buy and not block_l:
                pos_dir = "BUY"; ep = cl; ei = i
                trail = {"bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1)}
            elif raw_sell and not block_s:
                pos_dir = "SELL"; ep = cl; ei = i
                trail = {"bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1)}

    if pos_dir:
        cl = M30[-1].close
        pnl = (cl - ep) * CONTRACT * LOT - COMMISSION if pos_dir == "BUY" else (ep - cl) * CONTRACT * LOT - COMMISSION
        trades.append({
            "dir": pos_dir, "ep": round(ep, 2), "ex": round(cl, 2),
            "pnl": round(pnl, 2), "bars": n_total - 1 - ei,
            "adx_in": trail.get("ax", 0), "reason": "END",
            "entry_t": fmt_ts(M30[ei].time), "exit_t": fmt_ts(M30[-1].time),
        })

    return trades, mdd, block_log


# ── 跑两版回测 ──
_print("=" * 130)
_print("  mfi_bb_m30_upgraded  v8 vs v9 对比回测")
_print("=" * 130)
_print(f"  M30 数据: {n_total:,} 根  "
      f"({fmt_ts(M30[0].time)} ~ {fmt_ts(M30[-1].time)})")
_print(f"  LOT=0.01  CONTRACT=100  COMMISSION=$0.50")
_print("=" * 130)

t0 = time.time()
trades_v8, mdd_v8 = run_v8()
trades_v9, mdd_v9, block_log = run_v9()
elapsed = time.time() - t0

s_v8 = stats(trades_v8)
s_v9 = stats(trades_v9)

_print(f"\n  [v8 详细]  72 笔目标 - 实跑 {s_v8['n']} 笔, 耗时 {elapsed:.1f}s")

# ── 核心指标对比 ──
_print("\n" + "=" * 130)
_print("  [核心指标对比]")
_print("=" * 130)
header = f"  {'指标':<20} {'v8':>14} {'v9':>14} {'差值(v9-v8)':>16}"
_print(header)
_print("  " + "-" * 80)
rows = [
    ("总交易",     f"{s_v8['n']}",         f"{s_v9['n']}",         f"{s_v9['n']-s_v8['n']:+d}"),
    ("BUY笔数",    f"{s_v8['longs']}",     f"{s_v9['longs']}",     f"{s_v9['longs']-s_v8['longs']:+d}"),
    ("SELL笔数",   f"{s_v8['shorts']}",    f"{s_v9['shorts']}",    f"{s_v9['shorts']-s_v8['shorts']:+d}"),
    ("胜率",       f"{s_v8['wr']:.1f}%",   f"{s_v9['wr']:.1f}%",   f"{s_v9['wr']-s_v8['wr']:+.1f}%"),
    ("总盈亏",     f"${s_v8['pnl']:>+10.2f}", f"${s_v9['pnl']:>+10.2f}", f"${s_v9['pnl']-s_v8['pnl']:>+8.2f}"),
    ("BUY盈亏",    f"${s_v8['long_pnl']:>+8.2f}",  f"${s_v9['long_pnl']:>+8.2f}",  f"${s_v9['long_pnl']-s_v8['long_pnl']:>+6.2f}"),
    ("SELL盈亏",   f"${s_v8['short_pnl']:>+8.2f}", f"${s_v9['short_pnl']:>+8.2f}", f"${s_v9['short_pnl']-s_v8['short_pnl']:>+6.2f}"),
    ("平均盈利",   f"${s_v8['aw']:>+6.2f}", f"${s_v9['aw']:>+6.2f}", f"${s_v9['aw']-s_v8['aw']:+.2f}"),
    ("平均亏损",   f"${s_v8['al']:>+6.2f}", f"${s_v9['al']:>+6.2f}", f"${s_v9['al']-s_v8['al']:+.2f}"),
    ("盈亏比",     f"{s_v8['aw']/abs(s_v8['al']) if s_v8['al'] else 0:.2f}",
                    f"{s_v9['aw']/abs(s_v9['al']) if s_v9['al'] else 0:.2f}", "—"),
    ("利润因子",   f"{s_v8['pf']:.2f}",   f"{s_v9['pf']:.2f}",   f"{s_v9['pf']-s_v8['pf']:+.2f}"),
    ("最大回撤",   f"${mdd_v8:.2f}",      f"${mdd_v9:.2f}",      f"${mdd_v9-mdd_v8:+.2f}"),
    ("最大单笔亏", f"${s_v8['max_loss']:>+6.2f}", f"${s_v9['max_loss']:>+6.2f}", f"${s_v9['max_loss']-s_v8['max_loss']:+.2f}"),
    ("最大单笔盈", f"${s_v8['max_win']:>+6.2f}",  f"${s_v9['max_win']:>+6.2f}",  f"${s_v9['max_win']-s_v8['max_win']:+.2f}"),
    ("均持仓bars", f"{s_v8['avg_bars']}", f"{s_v9['avg_bars']}", f"{s_v9['avg_bars']-s_v8['avg_bars']:+.1f}"),
]
for r in rows:
    _print(f"  {r[0]:<18} {r[1]:>14} {r[2]:>14} {r[3]:>16}")

# ── 月度对比 ──
_print("\n" + "=" * 130)
_print("  [月度盈亏对比]")
_print("=" * 130)
_print(f"  {'月份':<8} {'v8笔数':>8} {'v8胜率':>8} {'v8盈亏':>12} {'v9笔数':>8} {'v9胜率':>8} {'v9盈亏':>12} {'差值':>12}")
_print("  " + "-" * 90)

def monthly(trades):
    m = {}
    for t in trades:
        key = t["exit_t"][:5]  # "MM-DD", 取月
        # 用 exit_t 的前2位 -> 月份
        mm = t["exit_t"][:2]
        m.setdefault(mm, []).append(t)
    return m

mv8 = monthly(trades_v8); mv9 = monthly(trades_v9)
all_months = sorted(set(mv8.keys()) | set(mv9.keys()))
for mm in all_months:
    l8 = mv8.get(mm, [])
    l9 = mv9.get(mm, [])
    n8 = len(l8); p8 = sum(t["pnl"] for t in l8)
    wr8 = sum(1 for t in l8 if t["pnl"] > 0) / n8 * 100 if n8 else 0
    n9 = len(l9); p9 = sum(t["pnl"] for t in l9)
    wr9 = sum(1 for t in l9 if t["pnl"] > 0) / n9 * 100 if n9 else 0
    _print(f"  {mm}月     {n8:>8} {wr8:>7.1f}% ${p8:>+10.2f} {n9:>8} {wr9:>7.1f}% ${p9:>+10.2f} ${p9-p8:>+10.2f}")

# ── 出场原因分项 ──
_print("\n" + "=" * 130)
_print("  [出场原因分项对比]")
_print("=" * 130)
_print(f"  {'原因':<10} {'v8笔数':>8} {'v8胜率':>8} {'v8盈亏':>12} {'v9笔数':>8} {'v9胜率':>8} {'v9盈亏':>12} {'差值':>12}")
_print("  " + "-" * 90)
def by_reason(trades):
    m = {}
    for t in trades:
        m.setdefault(t["reason"], []).append(t)
    return m
rv8 = by_reason(trades_v8); rv9 = by_reason(trades_v9)
all_reasons = sorted(set(rv8.keys()) | set(rv9.keys()))
for r in all_reasons:
    l8 = rv8.get(r, [])
    l9 = rv9.get(r, [])
    n8 = len(l8); p8 = sum(t["pnl"] for t in l8)
    wr8 = sum(1 for t in l8 if t["pnl"] > 0) / n8 * 100 if n8 else 0
    n9 = len(l9); p9 = sum(t["pnl"] for t in l9)
    wr9 = sum(1 for t in l9 if t["pnl"] > 0) / n9 * 100 if n9 else 0
    _print(f"  {r:<10} {n8:>8} {wr8:>7.1f}% ${p8:>+10.2f} {n9:>8} {wr9:>7.1f}% ${p9:>+10.2f} ${p9-p8:>+10.2f}")

# ── ADX>30 拦截效果分析 ──
_print("\n" + "=" * 130)
_print("  [ADX>30 拦截效果分析]")
_print("=" * 130)

# 在 v8 视角: 这些"被拦截"的笔如果v8入场会怎样?
# 用 v8 同样的出场逻辑, 从 i 到 v8 第一次出现平仓或回测结束
v8_block_idx = {b["i"] for b in block_log}
v8_block_in_v8 = [t for t in trades_v8 if any(1 for b in block_log if 0 for _ in [1]) and 0]  # 占位

# 更准确: 找到 v8 实际入场且在 v9 拦截列表里的笔
# 这些笔的入场 idx 我们没有存, 改用另一个方法: 模拟 v8 在 v9 拦截点的入场结果
# 但 v8 用的就是 v8 自己的入场逻辑, 所以 trades_v8 中有些笔是 v9 会拦截的
# 简单做法: 从 v9 block_log 取出所有 (i, dir) 组合, 在 v8 trades 中匹配 ep 和 dir

# 重新跑一遍 v8, 标记哪些入场的 idx 在 v9 拦截列表里
# 直接复用 run_v8, 但收集入场 idx
v8_entries = []

def run_v8_with_idx():
    """v8 但记录每个入场点的 i"""
    pos_dir = None
    ep = 0.0
    ei = 0
    trail = {}
    res = []
    for i in range(MIN_BARS, n_total):
        cl = M30[i].close
        ts = int(M30[i].time)
        bbu = bb_u[i]; bbm = bb_m[i]; bbl = bb_l[i]
        mfi_i = mfi_arr[i]
        bwr = bb_w_ratio[i]; bwd = bb_w_dir[i]
        mfdir = mfi_dir_arr[i]
        adx_i = adx_arr[i]
        if not all(np.isfinite(x) for x in [bbu, bbm, bbl, mfi_i, bwr, adx_i]):
            continue
        if pos_dir is not None:
            is_buy = pos_dir == "BUY"
            td = trail
            ex = False; reason = None
            if is_buy:
                if not td["crossed"] and cl > bbu: td["crossed"] = True
                if td["crossed"] and cl <= bbu + 0.01 and mfi_i > 50: ex, reason = True, "顺势"
            else:
                if not td["crossed"] and cl < bbl: td["crossed"] = True
                if td["crossed"] and cl >= bbl - 0.01 and mfi_i < 50: ex, reason = True, "顺势"
            if not ex and not td["crossed"]:
                if is_buy and cl >= bbm: ex, reason = True, "中轴"
                elif (not is_buy) and cl <= bbm: ex, reason = True, "中轴"
            if not ex:
                hw = td["bw"] / 2
                if is_buy and cl >= ep + hw: ex, reason = True, "半宽"
                elif (not is_buy) and cl <= ep - hw: ex, reason = True, "半宽"
            if ex:
                pnl = (cl - ep) * CONTRACT * LOT - COMMISSION if is_buy else (ep - cl) * CONTRACT * LOT - COMMISSION
                res.append({"i": ei, "dir": pos_dir, "ep": ep, "ex": cl, "pnl": pnl, "reason": reason, "bars": i - ei})
                pos_dir = None
                trail = {}
        if pos_dir is None:
            block_l = block_s = False
            s = 0
            if bwr > 1 + BB_EXPAND_THRESHOLD: s += 1
            if bwd == 1: s += 1
            if cl > bbm and mfdir in (1, 0): s += 1
            if cl < bbm and mfdir in (-1, 0): s += 1
            if s >= 2:
                if cl > bbm and mfdir in (1, 0): block_s = True
                if cl < bbm and mfdir in (-1, 0): block_l = True
            if cl < bbl and not block_l:
                pos_dir = "BUY"; ep = cl; ei = i
                trail = {"bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1)}
            elif cl > bbu and not block_s:
                pos_dir = "SELL"; ep = cl; ei = i
                trail = {"bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1)}
    if pos_dir:
        cl = M30[-1].close
        pnl = (cl - ep) * CONTRACT * LOT - COMMISSION if pos_dir == "BUY" else (ep - cl) * CONTRACT * LOT - COMMISSION
        res.append({"i": ei, "dir": pos_dir, "ep": ep, "ex": cl, "pnl": pnl, "reason": "END", "bars": n_total - 1 - ei})
    return res

v8_with_idx = run_v8_with_idx()

# block_log 是 v9 拦截的, 但 v8 可能在某些 i 上也是 block (因 BB扩张) 导致没入场
# 所以"如果v8也入场"= v8_with_idx 中那些 i 在 block_log 里的
block_idx_set = {b["i"] for b in block_log}
v8_hypothetical = [t for t in v8_with_idx if t["i"] in block_idx_set]
v8_normal = [t for t in v8_with_idx if t["i"] not in block_idx_set]

_print(f"  v9 共拦截 ADX>30 同向趋势入场: {len(block_log)} 笔")
_print(f"  其中 v8 实际入场: {len(v8_hypothetical)} 笔 (v8 视角假设这 {len(v8_hypothetical)} 笔继续用 v8 逻辑做)")

# v9 拦截后, v8 实际发生的事 = v8 入场
# v9 拦截但 v8 实际未入场的 (因BB扩张保护) = v8_with_idx 没匹配的
# 但 v8_hypothetical 已是 v8 实际入场的笔, v8 实际 PnL = sum(v8_with_idx.pnl)
# v9 假设未拦截版本 = v8_hypothetical 这些笔的 pnl
# v9 净效果 = 少赚 (或不亏) 这部分

# 另一种对比: v9 净 PnL 怎么算?
# v9 实际: 全部 v9 trades (含 v9 新入场的笔 + 没拦截 v8 入场的笔)
# 但 v9 入场是 v8 入场去掉被拦截的, 所以 v9 trades = v8_with_idx - v8_hypothetical
# v9 pnl = v8_pnl - v8_hypothetical_pnl

hyp_pnl = sum(t["pnl"] for t in v8_hypothetical)
hyp_wins = [t for t in v8_hypothetical if t["pnl"] > 0]
hyp_losses = [t for t in v8_hypothetical if t["pnl"] <= 0]
hyp_wr = len(hyp_wins) / len(v8_hypothetical) * 100 if v8_hypothetical else 0
hyp_aw = sum(t["pnl"] for t in hyp_wins) / len(hyp_wins) if hyp_wins else 0
hyp_al = sum(t["pnl"] for t in hyp_losses) / len(hyp_losses) if hyp_losses else 0
hyp_long = [t for t in v8_hypothetical if t["dir"] == "BUY"]
hyp_short = [t for t in v8_hypothetical if t["dir"] == "SELL"]

_print(f"\n  v9 拦截的 {len(v8_hypothetical)} 笔 (v8 实际入场), v8 视角下:")
_print(f"    拦截笔 BUY: {len(hyp_long)}  SELL: {len(hyp_short)}")
_print(f"    胜率:      {hyp_wr:.1f}%  ({len(hyp_wins)}胜 / {len(hyp_losses)}负)")
_print(f"    总盈亏:   ${hyp_pnl:+.2f}")
_print(f"    平均盈:   ${hyp_aw:+.2f}  均亏: ${hyp_al:+.2f}")
_print(f"    BUY 盈亏: ${sum(t['pnl'] for t in hyp_long):+.2f}  SELL 盈亏: ${sum(t['pnl'] for t in hyp_short):+.2f}")
_print(f"  v9 拦截净效果: v8 总 PnL ${s_v8['pnl']} - v9 总 PnL ${s_v9['pnl']} = ${s_v8['pnl']-s_v9['pnl']:+.2f} "
      f"(等于 -hyp_pnl = ${-hyp_pnl:+.2f})")

# ── 拦截笔明细 ──
_print("\n" + "=" * 130)
_print(f"  [v9 拦截明细] (共 {len(block_log)} 笔, 标 * = v8 实际入场的)")
_print("=" * 130)
_print(f"  {'#':>3} {'方向':<5} {'时间':<12} {'价格':>8} {'轨道':>8} {'ADX':>6} {'MFI方向':>8} {'原因':<40} {'v8结果':>10}")
_print("  " + "-" * 130)
for idx, b in enumerate(block_log, 1):
    band = b["bbl"] if b["dir"] == "BUY" else b["bbu"]
    mfd = "↑" if b["mfi_dir"] == 1 else ("↓" if b["mfi_dir"] == -1 else "—")
    # 找 v8 实际入场结果
    found = next((t for t in v8_with_idx if t["i"] == b["i"]), None)
    if found:
        marker = " *"
        v8_res = f"${found['pnl']:+.2f}"
    else:
        marker = ""
        v8_res = "(BB扩张也挡)"
    _print(f"  {idx:>3} {b['dir']:<5} {b['ts']:<12} {b['cl']:>8.2f} {band:>8.2f} "
          f"{b['adx']:>6.1f} {mfd:>8} {b['reason'][:40]:<40} {v8_res:>10}{marker}")

# ── 拦截笔的 v8 实际盈亏分布 ──
if v8_hypothetical:
    _print(f"\n  [拦截笔 v8 实际盈亏分布]")
    buckets = {"盈利": 0, "亏损": 0}
    hyp_buy_w = [t for t in v8_hypothetical if t["dir"] == "BUY" and t["pnl"] > 0]
    hyp_buy_l = [t for t in v8_hypothetical if t["dir"] == "BUY" and t["pnl"] <= 0]
    hyp_se_w = [t for t in v8_hypothetical if t["dir"] == "SELL" and t["pnl"] > 0]
    hyp_se_l = [t for t in v8_hypothetical if t["dir"] == "SELL" and t["pnl"] <= 0]
    _print(f"    BUY  盈: {len(hyp_buy_w)} 笔  ${sum(t['pnl'] for t in hyp_buy_w):+.2f}")
    _print(f"    BUY  亏: {len(hyp_buy_l)} 笔  ${sum(t['pnl'] for t in hyp_buy_l):+.2f}")
    _print(f"    SELL 盈: {len(hyp_se_w)} 笔  ${sum(t['pnl'] for t in hyp_se_w):+.2f}")
    _print(f"    SELL 亏: {len(hyp_se_l)} 笔  ${sum(t['pnl'] for t in hyp_se_l):+.2f}")
    _print(f"    BUY  净:  ${sum(t['pnl'] for t in hyp_long):+.2f}")
    _print(f"    SELL 净: ${sum(t['pnl'] for t in hyp_short):+.2f}")

# ── 总结 ──
_print("\n" + "=" * 130)
_print("  [结论]")
_print("=" * 130)
improvement = s_v8["pnl"] - s_v9["pnl"]  # v9 比 v8 少亏的钱 (正数 = 改善)
_pct = abs(improvement / s_v8["pnl"]) * 100 if s_v8["pnl"] != 0 else 0
_print(f"  v8 总盈亏: ${s_v8['pnl']:+.2f}")
_print(f"  v9 总盈亏: ${s_v9['pnl']:+.2f}")
_print(f"  改善幅度:  ${improvement:+.2f}  ({_pct:.1f}%)")
_print(f"  v9 拦截:  {len(block_log)} 笔 (v8 实际入场 {len(v8_hypothetical)} 笔)")
_print(f"  v8 在拦截笔上的盈亏: ${hyp_pnl:+.2f}  (v9 净省下这些)")
_print(f"  v8 -> v9: 笔数 {s_v8['n']} -> {s_v9['n']} ({s_v9['n']-s_v8['n']:+d})")
_print(f"  胜率: {s_v8['wr']:.1f}% -> {s_v9['wr']:.1f}%")
_print(f"  PF:   {s_v8['pf']:.2f} -> {s_v9['pf']:.2f}")
_print(f"  DD:   ${mdd_v8:.2f} -> ${mdd_v9:.2f}")
print("=" * 130)
