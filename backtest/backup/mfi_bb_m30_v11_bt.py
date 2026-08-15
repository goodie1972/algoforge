"""
mfi_bb_m30 v8 / v10 / v11 三版本对比回测
=========================================
v8:   BB扩张 3选2 保护 + 无 ADX 过滤 + 无硬止损
v10:  ADX>25 同向拦截 + ATR 硬止损(同向2× / 反向1×)
v11:  ADX>25 同向拦截 + BB扩张同向保护 + 硬止损统一 2×ATR(不分方向)

v11 相对 v10 的关键改动:
  1. 加回 BB扩张保护（v8 那条）: bwr>1.05 + 方向扩张 + 价格/MFI 同侧 → 禁做同向
  2. 硬止损统一 2×ATR, 不再分同向/反向
  3. 保留 ADX>25 同向拦截

输出: v8/v10/v11 关键指标 + 月度对比 + 硬止损分析 + BB扩张拦截统计
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
ATR_PERIOD = 14
BB_EXPAND_THRESHOLD = 0.05
ADX_THRESHOLD = 25


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
atr = talib.ATR(arr_high, arr_low, arr_close, timeperiod=ATR_PERIOD)
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


def fmt_month(t):
    return datetime.fromtimestamp(int(t)).strftime("%Y-%m")


def stats(trades):
    """计算一组交易的统计指标"""
    n = len(trades)
    if n == 0:
        return {
            "n": 0, "pnl": 0.0, "wr": 0.0, "pf": 0.0,
            "aw": 0.0, "al": 0.0, "longs": 0, "shorts": 0,
            "long_pnl": 0.0, "short_pnl": 0.0,
            "max_loss": 0.0, "max_win": 0.0, "avg_bars": 0.0,
            "win_n": 0, "loss_n": 0,
        }
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    pnl = sum(t["pnl"] for t in trades)
    wr = len(wins) / n * 100
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
        "max_loss": round(min(t["pnl"] for t in trades), 2),
        "max_win": round(max(t["pnl"] for t in trades), 2),
        "avg_bars": round(sum(t["bars"] for t in trades) / n, 1),
        "win_n": len(wins),
        "loss_n": len(losses),
    }


# ════════════════════════════════════════════════════════════════
# v8: BB扩张 3选2 保护 + 无 ADX 过滤 + 无硬止损
# ════════════════════════════════════════════════════════════════
def run_v8():
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
                    "exit_month": fmt_month(ts),
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
        ts = int(M30[-1].time)
        pnl = (cl - ep) * CONTRACT * LOT - COMMISSION if pos_dir == "BUY" else (ep - cl) * CONTRACT * LOT - COMMISSION
        trades.append({
            "dir": pos_dir, "ep": round(ep, 2), "ex": round(cl, 2),
            "pnl": round(pnl, 2), "bars": n_total - 1 - ei,
            "adx_in": trail.get("ax", 0), "reason": "END",
            "entry_t": fmt_ts(M30[ei].time), "exit_t": fmt_ts(ts),
            "exit_month": fmt_month(ts),
        })

    return trades, mdd


# ════════════════════════════════════════════════════════════════
# v10: ADX>25 同向拦截 + ATR 硬止损(同向2× / 反向1×)
# ════════════════════════════════════════════════════════════════
def run_v10():
    trades = []
    running = 0.0
    peak = 0.0
    mdd = 0.0
    pos_dir = None
    ep = 0.0
    ei = 0
    trail = {}
    hard_sl_log = []

    for i in range(MIN_BARS, n_total):
        cl = M30[i].close
        ts = int(M30[i].time)
        bbu = bb_u[i]; bbm = bb_m[i]; bbl = bb_l[i]
        mfi_i = mfi_arr[i]
        mfdir = mfi_dir_arr[i]
        adx_i = adx_arr[i]
        atr_i = atr[i]
        if not all(np.isfinite(x) for x in [bbu, bbm, bbl, mfi_i, adx_i, atr_i]):
            continue

        # 出场
        if pos_dir is not None:
            is_buy = pos_dir == "BUY"
            td = trail
            ex = False; reason = None
            if is_buy and cl <= td["sl_price"]:
                ex, reason = True, "硬止损"
            elif (not is_buy) and cl >= td["sl_price"]:
                ex, reason = True, "硬止损"
            if not ex:
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
                rec = {
                    "dir": pos_dir, "ep": round(ep, 2), "ex": round(cl, 2),
                    "pnl": round(pnl, 2), "bars": i - ei,
                    "adx_in": td.get("ax", 0), "reason": reason,
                    "entry_t": fmt_ts(M30[ei].time), "exit_t": fmt_ts(ts),
                    "exit_month": fmt_month(ts),
                    "sl_dist": round(td.get("sl_dist", 0), 2),
                }
                trades.append(rec)
                if reason == "硬止损":
                    hard_sl_log.append(rec)
                running += pnl
                if running > peak: peak = running
                if peak - running > mdd: mdd = peak - running
                pos_dir = None
                trail = {}

        # 入场 (v10: ADX>25 同向硬过滤)
        if pos_dir is None:
            block_l = block_s = False
            if adx_i > 25:
                if cl < bbm and mfdir == -1:
                    block_l = True
                elif cl > bbm and mfdir == 1:
                    block_s = True

            if cl < bbl and not block_l:
                aligned = (mfdir == 1 and cl > bbm)
                sl_dist = 2.0 * atr_i if aligned else 1.0 * atr_i
                sl_price = cl - sl_dist
                pos_dir = "BUY"; ep = cl; ei = i
                trail = {
                    "bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1),
                    "sl_price": sl_price, "sl_dist": sl_dist,
                }
            elif cl > bbu and not block_s:
                aligned = (mfdir == -1 and cl < bbm)
                sl_dist = 2.0 * atr_i if aligned else 1.0 * atr_i
                sl_price = cl + sl_dist
                pos_dir = "SELL"; ep = cl; ei = i
                trail = {
                    "bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1),
                    "sl_price": sl_price, "sl_dist": sl_dist,
                }

    if pos_dir:
        cl = M30[-1].close
        ts = int(M30[-1].time)
        pnl = (cl - ep) * CONTRACT * LOT - COMMISSION if pos_dir == "BUY" else (ep - cl) * CONTRACT * LOT - COMMISSION
        trades.append({
            "dir": pos_dir, "ep": round(ep, 2), "ex": round(cl, 2),
            "pnl": round(pnl, 2), "bars": n_total - 1 - ei,
            "adx_in": trail.get("ax", 0), "reason": "END",
            "entry_t": fmt_ts(M30[ei].time), "exit_t": fmt_ts(ts),
            "exit_month": fmt_month(ts),
            "sl_dist": round(trail.get("sl_dist", 0), 2),
        })

    return trades, mdd, hard_sl_log


# ════════════════════════════════════════════════════════════════
# v11: ADX>25 同向拦截 + BB扩张同向保护 + 硬止损统一 2×ATR
# ════════════════════════════════════════════════════════════════
def run_v11():
    """
    v11 与策略类 _check_bb_breakout 完全一致:
      1) ADX>25 + MFI 与 BB 中轴同向 → 禁做反向
      2) BB扩张保护 (bwr>1.05 + bwd 方向 + 价格/MFI 同侧) → 禁做同向
      3) 硬止损统一 2×ATR, 不分方向
    """
    trades = []
    running = 0.0
    peak = 0.0
    mdd = 0.0
    pos_dir = None
    ep = 0.0
    ei = 0
    trail = {}
    hard_sl_log = []
    block_stats = {"adx_buy": 0, "adx_sell": 0, "bb_buy": 0, "bb_sell": 0}

    for i in range(MIN_BARS, n_total):
        cl = M30[i].close
        ts = int(M30[i].time)
        bbu = bb_u[i]; bbm = bb_m[i]; bbl = bb_l[i]
        mfi_i = mfi_arr[i]
        mfdir = mfi_dir_arr[i]
        adx_i = adx_arr[i]
        atr_i = atr[i]
        bwr = bb_w_ratio[i]
        bwd = bb_w_dir[i]
        if not all(np.isfinite(x) for x in [bbu, bbm, bbl, mfi_i, adx_i, atr_i, bwr]):
            continue

        # 出场 (与 v10 一致)
        if pos_dir is not None:
            is_buy = pos_dir == "BUY"
            td = trail
            ex = False; reason = None
            if is_buy and cl <= td["sl_price"]:
                ex, reason = True, "硬止损"
            elif (not is_buy) and cl >= td["sl_price"]:
                ex, reason = True, "硬止损"
            if not ex:
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
                rec = {
                    "dir": pos_dir, "ep": round(ep, 2), "ex": round(cl, 2),
                    "pnl": round(pnl, 2), "bars": i - ei,
                    "adx_in": td.get("ax", 0), "reason": reason,
                    "entry_t": fmt_ts(M30[ei].time), "exit_t": fmt_ts(ts),
                    "exit_month": fmt_month(ts),
                    "sl_dist": round(td.get("sl_dist", 0), 2),
                }
                trades.append(rec)
                if reason == "硬止损":
                    hard_sl_log.append(rec)
                running += pnl
                if running > peak: peak = running
                if peak - running > mdd: mdd = peak - running
                pos_dir = None
                trail = {}

        # 入场 (v11: ADX>25 + BB扩张 双重保护, 硬止损统一 2×ATR)
        if pos_dir is None:
            block_l = block_s = False

            # ① ADX>25 同向拦截
            if adx_i > ADX_THRESHOLD:
                if cl < bbm and mfdir == -1:
                    block_l = True
                    block_stats["adx_buy"] += 1
                elif cl > bbm and mfdir == 1:
                    block_s = True
                    block_stats["adx_sell"] += 1

            # ② BB 扩张同向保护
            #    bwr>1.05 + 方向扩张 + 价格同侧 + MFI 同侧 → 禁做同向
            if bwr > 1 + BB_EXPAND_THRESHOLD:
                if bwd == 1 and cl > bbm and mfdir in (1, 0):
                    block_s = True
                    block_stats["bb_sell"] += 1
                elif bwd == -1 and cl < bbm and mfdir in (-1, 0):
                    block_l = True
                    block_stats["bb_buy"] += 1

            if cl < bbl and not block_l:
                # v11: 硬止损统一 2×ATR (不分方向)
                sl_dist = 2.0 * atr_i
                sl_price = cl - sl_dist
                pos_dir = "BUY"; ep = cl; ei = i
                trail = {
                    "bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1),
                    "sl_price": sl_price, "sl_dist": sl_dist,
                }
            elif cl > bbu and not block_s:
                sl_dist = 2.0 * atr_i
                sl_price = cl + sl_dist
                pos_dir = "SELL"; ep = cl; ei = i
                trail = {
                    "bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1),
                    "sl_price": sl_price, "sl_dist": sl_dist,
                }

    if pos_dir:
        cl = M30[-1].close
        ts = int(M30[-1].time)
        pnl = (cl - ep) * CONTRACT * LOT - COMMISSION if pos_dir == "BUY" else (ep - cl) * CONTRACT * LOT - COMMISSION
        trades.append({
            "dir": pos_dir, "ep": round(ep, 2), "ex": round(cl, 2),
            "pnl": round(pnl, 2), "bars": n_total - 1 - ei,
            "adx_in": trail.get("ax", 0), "reason": "END",
            "entry_t": fmt_ts(M30[ei].time), "exit_t": fmt_ts(ts),
            "exit_month": fmt_month(ts),
            "sl_dist": round(trail.get("sl_dist", 0), 2),
        })

    return trades, mdd, hard_sl_log, block_stats


# ════════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════════
_print("=" * 140)
_print("  mfi_bb_m30_upgraded  v8 / v10 / v11 三版本对比回测")
_print("=" * 140)
_print(f"  M30 数据: {n_total:,} 根  "
      f"({fmt_ts(M30[0].time)} ~ {fmt_ts(M30[-1].time)})")
_print(f"  LOT=0.01  CONTRACT=100  COMMISSION=$0.50  ATR 周期={ATR_PERIOD}")
_print(f"  v11 关键改动: 加回BB扩张同向保护 + 硬止损统一 2×ATR + 保留ADX>25同向拦截")
_print("=" * 140)

t0 = time.time()
trades_v8, mdd_v8 = run_v8()
trades_v10, mdd_v10, hard_sl_v10 = run_v10()
trades_v11, mdd_v11, hard_sl_v11, block_stats = run_v11()
elapsed = time.time() - t0

s_v8 = stats(trades_v8)
s_v10 = stats(trades_v10)
s_v11 = stats(trades_v11)

# ── 核心指标对比 ──
_print("\n" + "=" * 140)
_print("  [核心指标对比]")
_print("=" * 140)
header = f"  {'指标':<18} {'v8':>14} {'v10':>14} {'v11':>14} {'v11-v8':>14} {'v11-v10':>14}"
_print(header)
_print("  " + "-" * 100)
def _pl_pct(pnl, base):
    if base == 0:
        return "—"
    return f"{pnl/base*100:+.1f}%"


rows = [
    ("总交易",     f"{s_v8['n']}",  f"{s_v10['n']}",  f"{s_v11['n']}",  f"{s_v11['n']-s_v8['n']:+d}",  f"{s_v11['n']-s_v10['n']:+d}"),
    ("BUY笔数",    f"{s_v8['longs']}",  f"{s_v10['longs']}",  f"{s_v11['longs']}",  f"{s_v11['longs']-s_v8['longs']:+d}",  f"{s_v11['longs']-s_v10['longs']:+d}"),
    ("SELL笔数",   f"{s_v8['shorts']}", f"{s_v10['shorts']}", f"{s_v11['shorts']}", f"{s_v11['shorts']-s_v8['shorts']:+d}", f"{s_v11['shorts']-s_v10['shorts']:+d}"),
    ("胜率",       f"{s_v8['wr']:.1f}%",  f"{s_v10['wr']:.1f}%",  f"{s_v11['wr']:.1f}%",  f"{s_v11['wr']-s_v8['wr']:+.1f}%",  f"{s_v11['wr']-s_v10['wr']:+.1f}%"),
    ("总盈亏",     f"${s_v8['pnl']:>+10.2f}", f"${s_v10['pnl']:>+10.2f}", f"${s_v11['pnl']:>+10.2f}", f"${s_v11['pnl']-s_v8['pnl']:>+8.2f}", f"${s_v11['pnl']-s_v10['pnl']:>+8.2f}"),
    ("BUY盈亏",    f"${s_v8['long_pnl']:>+8.2f}",  f"${s_v10['long_pnl']:>+8.2f}",  f"${s_v11['long_pnl']:>+8.2f}",  f"${s_v11['long_pnl']-s_v8['long_pnl']:>+6.2f}",  f"${s_v11['long_pnl']-s_v10['long_pnl']:>+6.2f}"),
    ("SELL盈亏",   f"${s_v8['short_pnl']:>+8.2f}", f"${s_v10['short_pnl']:>+8.2f}", f"${s_v11['short_pnl']:>+8.2f}", f"${s_v11['short_pnl']-s_v8['short_pnl']:>+6.2f}", f"${s_v11['short_pnl']-s_v10['short_pnl']:>+6.2f}"),
    ("平均盈利",   f"${s_v8['aw']:>+6.2f}",  f"${s_v10['aw']:>+6.2f}",  f"${s_v11['aw']:>+6.2f}",  f"{s_v11['aw']-s_v8['aw']:+.2f}",  f"{s_v11['aw']-s_v10['aw']:+.2f}"),
    ("平均亏损",   f"${s_v8['al']:>+6.2f}",  f"${s_v10['al']:>+6.2f}",  f"${s_v11['al']:>+6.2f}",  f"{s_v11['al']-s_v8['al']:+.2f}",  f"{s_v11['al']-s_v10['al']:+.2f}"),
    ("盈亏比",     f"{s_v8['aw']/abs(s_v8['al']) if s_v8['al'] else 0:.2f}",
                    f"{s_v10['aw']/abs(s_v10['al']) if s_v10['al'] else 0:.2f}",
                    f"{s_v11['aw']/abs(s_v11['al']) if s_v11['al'] else 0:.2f}", "—", "—"),
    ("利润因子",   f"{s_v8['pf']:.2f}",  f"{s_v10['pf']:.2f}",  f"{s_v11['pf']:.2f}",  f"{s_v11['pf']-s_v8['pf']:+.2f}",  f"{s_v11['pf']-s_v10['pf']:+.2f}"),
    ("最大回撤",   f"${mdd_v8:.2f}",     f"${mdd_v10:.2f}",     f"${mdd_v11:.2f}",     f"${mdd_v11-mdd_v8:+.2f}",     f"${mdd_v11-mdd_v10:+.2f}"),
    ("最大单笔亏", f"${s_v8['max_loss']:>+6.2f}",  f"${s_v10['max_loss']:>+6.2f}",  f"${s_v11['max_loss']:>+6.2f}",  f"{s_v11['max_loss']-s_v8['max_loss']:+.2f}",  f"{s_v11['max_loss']-s_v10['max_loss']:+.2f}"),
    ("最大单笔盈", f"${s_v8['max_win']:>+6.2f}",   f"${s_v10['max_win']:>+6.2f}",   f"${s_v11['max_win']:>+6.2f}",   f"{s_v11['max_win']-s_v8['max_win']:+.2f}",   f"{s_v11['max_win']-s_v10['max_win']:+.2f}"),
    ("均持仓bars", f"{s_v8['avg_bars']}",  f"{s_v10['avg_bars']}",  f"{s_v11['avg_bars']}",  f"{s_v11['avg_bars']-s_v8['avg_bars']:+.1f}",  f"{s_v11['avg_bars']-s_v10['avg_bars']:+.1f}"),
]
for r in rows:
    _print(f"  {r[0]:<16} {r[1]:>14} {r[2]:>14} {r[3]:>14} {r[4]:>14} {r[5]:>14}")

# ── v11 BB扩张/ADX 拦截统计 ──
_print("\n" + "=" * 140)
_print("  [v11 入场拦截统计: BB扩张 vs ADX]")
_print("=" * 140)
_print(f"  ADX 拦截 BUY:  {block_stats['adx_buy']:>4} 笔  (ADX>{ADX_THRESHOLD} + 价格<中轴 + MFI↓)")
_print(f"  ADX 拦截 SELL: {block_stats['adx_sell']:>4} 笔  (ADX>{ADX_THRESHOLD} + 价格>中轴 + MFI↑)")
_print(f"  BB扩 拦截 BUY:  {block_stats['bb_buy']:>4} 笔  (bwr>1.05 + 下开 + 价格<中轴 + MFI↓)")
_print(f"  BB扩 拦截 SELL: {block_stats['bb_sell']:>4} 笔  (bwr>1.05 + 上开 + 价格>中轴 + MFI↑)")
total_adx = block_stats['adx_buy'] + block_stats['adx_sell']
total_bb = block_stats['bb_buy'] + block_stats['bb_sell']
_print(f"  ADX 共拦截: {total_adx} 笔")
_print(f"  BB扩 共拦截: {total_bb} 笔")
_print(f"  合计拦截: {total_adx + total_bb} 笔 (vs v10 仅ADX拦截, vs v8 仅BB扩张 3选2 拦截)")

# 模拟 v8 / v10 / v11 在同一组触发信号下各自的表现
_print("\n  对照 v10 / v8 入场拦截分析:")
v8_block_buy = 0
v8_block_sell = 0
v10_block_buy = 0
v10_block_sell = 0
v11_block_buy = 0
v11_block_sell = 0
for i in range(MIN_BARS, n_total):
    cl = M30[i].close
    bbu = bb_u[i]; bbm = bb_m[i]; bbl = bb_l[i]
    mfdir = mfi_dir_arr[i]
    adx_i = adx_arr[i]
    bwr = bb_w_ratio[i]
    bwd = bb_w_dir[i]
    if not all(np.isfinite(x) for x in [bbu, bbm, bbl, adx_i, mfdir, bwr]):
        continue
    # BUY 触发
    if cl < bbl:
        # v8: BB扩张 3选2 拦截
        s = 0
        if bwr > 1 + BB_EXPAND_THRESHOLD: s += 1
        if bwd == 1: s += 1
        if cl > bbm and mfdir in (1, 0): s += 1
        if cl < bbm and mfdir in (-1, 0): s += 1
        if s >= 2 and cl < bbm and mfdir in (-1, 0):
            v8_block_buy += 1
        # v10: ADX>25 拦截
        if adx_i > 25 and cl < bbm and mfdir == -1:
            v10_block_buy += 1
        # v11: ADX>25 OR BB扩张 拦截
        v11_adx = adx_i > 25 and cl < bbm and mfdir == -1
        v11_bb = bwr > 1 + BB_EXPAND_THRESHOLD and bwd == -1 and cl < bbm and mfdir in (-1, 0)
        if v11_adx or v11_bb:
            v11_block_buy += 1
    # SELL 触发
    elif cl > bbu:
        s = 0
        if bwr > 1 + BB_EXPAND_THRESHOLD: s += 1
        if bwd == 1: s += 1
        if cl > bbm and mfdir in (1, 0): s += 1
        if cl < bbm and mfdir in (-1, 0): s += 1
        if s >= 2 and cl > bbm and mfdir in (1, 0):
            v8_block_sell += 1
        if adx_i > 25 and cl > bbm and mfdir == 1:
            v10_block_sell += 1
        v11_adx = adx_i > 25 and cl > bbm and mfdir == 1
        v11_bb = bwr > 1 + BB_EXPAND_THRESHOLD and bwd == 1 and cl > bbm and mfdir in (1, 0)
        if v11_adx or v11_bb:
            v11_block_sell += 1

_print(f"  v8  (BB扩张 3选2): 拦截 BUY {v8_block_buy} 笔, SELL {v8_block_sell} 笔")
_print(f"  v10 (ADX>25):       拦截 BUY {v10_block_buy} 笔, SELL {v10_block_sell} 笔")
_print(f"  v11 (ADX OR BB):    拦截 BUY {v11_block_buy} 笔, SELL {v11_block_sell} 笔")

# ── v11 硬止损分析 ──
_print("\n" + "=" * 140)
_print("  [v11 硬止损分析 (统一 2×ATR)]")
_print("=" * 140)
_print(f"  硬止损总触发: {len(hard_sl_v11)} 笔 (占总 v11 笔数 {len(trades_v11)} 的 {len(hard_sl_v11)/len(trades_v11)*100 if trades_v11 else 0:.1f}%)")
if hard_sl_v11:
    hs_buy = [t for t in hard_sl_v11 if t["dir"] == "BUY"]
    hs_sell = [t for t in hard_sl_v11 if t["dir"] == "SELL"]
    hs_pnl = sum(t["pnl"] for t in hard_sl_v11)
    _print(f"  BUY 硬止损: {len(hs_buy)} 笔, 盈亏 ${sum(t['pnl'] for t in hs_buy):+.2f}")
    _print(f"  SELL 硬止损: {len(hs_sell)} 笔, 盈亏 ${sum(t['pnl'] for t in hs_sell):+.2f}")
    _print(f"  硬止损总盈亏: ${hs_pnl:+.2f}")
    _print(f"  硬止损平均亏: ${sum(t['pnl'] for t in hard_sl_v11)/len(hard_sl_v11):+.2f}")
    no_hs = [t for t in trades_v11 if t["reason"] != "硬止损"]
    _print(f"  非硬止损笔({len(no_hs)} 笔) 盈亏: ${sum(t['pnl'] for t in no_hs):+.2f}")
_print(f"  v10 硬止损: {len(hard_sl_v10)} 笔, 盈亏 ${sum(t['pnl'] for t in hard_sl_v10):+.2f}")
_print(f"  v11 vs v10 硬止损: 减少 {len(hard_sl_v10)-len(hard_sl_v11)} 笔, "
      f"盈亏差 ${sum(t['pnl'] for t in hard_sl_v11) - sum(t['pnl'] for t in hard_sl_v10):+.2f}")

# ── 月度对比 ──
_print("\n" + "=" * 140)
_print("  [月度盈亏对比]")
_print("=" * 140)
_print(f"  {'月份':<10} {'v8笔数':>7} {'v8胜率':>8} {'v8盈亏':>11}  "
      f"{'v10笔数':>7} {'v10胜率':>8} {'v10盈亏':>11}  "
      f"{'v11笔数':>7} {'v11胜率':>8} {'v11盈亏':>11}  {'v11-v10':>11}")
_print("  " + "-" * 130)


def monthly(trades):
    m = {}
    for t in trades:
        mm = t["exit_month"]
        m.setdefault(mm, []).append(t)
    return m


mv8 = monthly(trades_v8); mv10 = monthly(trades_v10); mv11 = monthly(trades_v11)
all_months = sorted(set(mv8.keys()) | set(mv10.keys()) | set(mv11.keys()))
for mm in all_months:
    l8 = mv8.get(mm, [])
    l10 = mv10.get(mm, [])
    l11 = mv11.get(mm, [])
    n8 = len(l8); p8 = sum(t["pnl"] for t in l8)
    wr8 = sum(1 for t in l8 if t["pnl"] > 0) / n8 * 100 if n8 else 0
    n10 = len(l10); p10 = sum(t["pnl"] for t in l10)
    wr10 = sum(1 for t in l10 if t["pnl"] > 0) / n10 * 100 if n10 else 0
    n11 = len(l11); p11 = sum(t["pnl"] for t in l11)
    wr11 = sum(1 for t in l11 if t["pnl"] > 0) / n11 * 100 if n11 else 0
    _print(f"  {mm:<10} {n8:>7} {wr8:>7.1f}% ${p8:>+9.2f}  "
          f"{n10:>7} {wr10:>7.1f}% ${p10:>+9.2f}  "
          f"{n11:>7} {wr11:>7.1f}% ${p11:>+9.2f}  ${p11-p10:>+9.2f}")

# ── v11 出场原因分项 ──
_print("\n" + "=" * 140)
_print("  [v11 出场原因分项]")
_print("=" * 140)
_print(f"  {'原因':<10} {'笔数':>7} {'胜率':>8} {'盈亏':>12} {'平均盈亏':>10} {'BUY数':>7} {'SELL数':>7}")
_print("  " + "-" * 80)
def by_reason(trades):
    m = {}
    for t in trades:
        m.setdefault(t["reason"], []).append(t)
    return m
rv11 = by_reason(trades_v11)
for r in sorted(rv11.keys()):
    l = rv11[r]
    n = len(l); p = sum(t["pnl"] for t in l)
    wr = sum(1 for t in l if t["pnl"] > 0) / n * 100 if n else 0
    avg = p / n if n else 0
    nb = sum(1 for t in l if t["dir"] == "BUY")
    ns = sum(1 for t in l if t["dir"] == "SELL")
    _print(f"  {r:<10} {n:>7} {wr:>7.1f}% ${p:>+10.2f} ${avg:>+8.2f} {nb:>7} {ns:>7}")

# ── 结论 ──
_print("\n" + "=" * 140)
_print("  [最终结论]")
_print("=" * 140)
_print(f"  v8   总盈亏: ${s_v8['pnl']:+.2f}  ({s_v8['n']} 笔, 胜率 {s_v8['wr']:.1f}%, MDD ${mdd_v8:.2f})")
_print(f"  v10  总盈亏: ${s_v10['pnl']:+.2f}  ({s_v10['n']} 笔, 胜率 {s_v10['wr']:.1f}%, MDD ${mdd_v10:.2f})")
_print(f"  v11  总盈亏: ${s_v11['pnl']:+.2f}  ({s_v11['n']} 笔, 胜率 {s_v11['wr']:.1f}%, MDD ${mdd_v11:.2f})")
_print("")
_print(f"  v11 vs v8:  笔数 {s_v11['n']-s_v8['n']:+d}, 盈亏 ${s_v11['pnl']-s_v8['pnl']:+.2f}, "
      f"MDD ${mdd_v11-mdd_v8:+.2f}")
_print(f"  v11 vs v10: 笔数 {s_v11['n']-s_v10['n']:+d}, 盈亏 ${s_v11['pnl']-s_v10['pnl']:+.2f}, "
      f"MDD ${mdd_v11-mdd_v10:+.2f}")
print()
# 判定
best = min([("v8", s_v8['pnl']), ("v10", s_v10['pnl']), ("v11", s_v11['pnl'])], key=lambda x: x[1])
worst = max([("v8", s_v8['pnl']), ("v10", s_v10['pnl']), ("v11", s_v11['pnl'])], key=lambda x: x[1])
if s_v11['pnl'] > s_v8['pnl'] and s_v11['pnl'] > s_v10['pnl']:
    _print(f"  [OK] v11 是三版中表现最好的, 优于 v8 ${s_v11['pnl']-s_v8['pnl']:+.2f}, 优于 v10 ${s_v11['pnl']-s_v10['pnl']:+.2f}")
elif s_v11['pnl'] < s_v8['pnl'] and s_v11['pnl'] < s_v10['pnl']:
    _print(f"  [FAIL] v11 是三版中最差, 差于 v8 ${s_v11['pnl']-s_v8['pnl']:+.2f}, 差于 v10 ${s_v11['pnl']-s_v10['pnl']:+.2f}")
else:
    _print(f"  [MIXED] v11 不是单纯最优, 详细见上表")
_print(f"  最佳: {best[0]} (${best[1]:+.2f}), 最差: {worst[0]} (${worst[1]:+.2f})")
_print(f"  耗时: {elapsed:.1f}s")
print("=" * 140)
