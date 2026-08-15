"""
mfi_bb_m30 v8 / v9 / v10 三版本对比回测
=========================================
v8:  BB扩张 3选2 保护 + 无 ADX 过滤 + 无硬止损
v9:  删除 BB扩张保护, 改 ADX>30 同向趋势硬过滤 + 无硬止损
v10: ADX 阈值 30→25 + ATR 硬止损
     - MFI/BB 中轴同向（信号被 MFI 确认）→ 2×ATR 止损
     - 反向 → 1×ATR 止损

输出: v8/v9/v10 关键指标 + 月度对比 + 硬止损触发分析
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
    """v8: BB扩张 3选2 保护 + 无 ADX 过滤 + 无硬止损"""
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

        # 出场 (与 v9/v10 顺势/中轴/半宽一致)
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


def run_v9():
    """v9: 删除 BB扩张保护, 改 ADX>30 同向趋势硬过滤 + 无硬止损"""
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
        mfdir = mfi_dir_arr[i]
        adx_i = adx_arr[i]
        if not all(np.isfinite(x) for x in [bbu, bbm, bbl, mfi_i, adx_i]):
            continue

        # 出场 (同 v8)
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

        # 入场 (v9: ADX>30 同向硬过滤)
        if pos_dir is None:
            block_l = block_s = False
            if adx_i > 30:
                if cl < bbm and mfdir == -1:
                    block_l = True
                elif cl > bbm and mfdir == 1:
                    block_s = True

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


def run_v10():
    """v10: ADX 阈值 30→25 + ATR 硬止损
    - 入场: 收盘穿轨 + ADX>25 同向趋势硬过滤
    - 硬止损: MFI 方向与 BB 中轴同向(信号被 MFI 确认) → 2×ATR, 否则 1×ATR
      严格按策略代码 line 161/165:
        BUY  aligned = (mfi_dir=="up" and entry > bb_mid)
        SELL aligned = (mfi_dir=="down" and entry < bb_mid)
    """
    trades = []
    running = 0.0
    peak = 0.0
    mdd = 0.0
    pos_dir = None
    ep = 0.0
    ei = 0
    trail = {}
    hard_sl_log = []  # 记录硬止损触发的笔

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

        # 出场 (v10): 硬止损 → 顺势 → 中轴 → 半宽
        if pos_dir is not None:
            is_buy = pos_dir == "BUY"
            td = trail
            ex = False; reason = None
            # ① 硬止损 (优先)
            if is_buy and cl <= td["sl_price"]:
                ex, reason = True, "硬止损"
            elif (not is_buy) and cl >= td["sl_price"]:
                ex, reason = True, "硬止损"
            # ② 顺势穿轨回抽 + MFI 50
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
            # ③ 中轴 (未穿轨)
            if not ex and not td["crossed"]:
                if is_buy and cl >= bbm:
                    ex, reason = True, "中轴"
                elif (not is_buy) and cl <= bbm:
                    ex, reason = True, "中轴"
            # ④ 半宽
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
                # BUY 入场: 计算硬止损
                aligned = (mfdir == 1 and cl > bbm)
                sl_dist = 2.0 * atr_i if aligned else 1.0 * atr_i
                sl_price = cl - sl_dist
                pos_dir = "BUY"; ep = cl; ei = i
                trail = {
                    "bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1),
                    "sl_price": sl_price, "sl_dist": sl_dist,
                }
            elif cl > bbu and not block_s:
                # SELL 入场: 计算硬止损
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


# ── 跑三版回测 ──
_print("=" * 140)
_print("  mfi_bb_m30_upgraded  v8 / v9 / v10 三版本对比回测")
_print("=" * 140)
_print(f"  M30 数据: {n_total:,} 根  "
      f"({fmt_ts(M30[0].time)} ~ {fmt_ts(M30[-1].time)})")
_print(f"  LOT=0.01  CONTRACT=100  COMMISSION=$0.50  ATR 周期={ATR_PERIOD}")
_print("=" * 140)

t0 = time.time()
trades_v8, mdd_v8 = run_v8()
trades_v9, mdd_v9 = run_v9()
trades_v10, mdd_v10, hard_sl_log = run_v10()
elapsed = time.time() - t0

s_v8 = stats(trades_v8)
s_v9 = stats(trades_v9)
s_v10 = stats(trades_v10)

# ── 核心指标对比 ──
_print("\n" + "=" * 140)
_print("  [核心指标对比]")
_print("=" * 140)
header = f"  {'指标':<20} {'v8':>14} {'v9':>14} {'v10':>14} {'差值(v10-v8)':>16} {'差值(v10-v9)':>16}"
_print(header)
_print("  " + "-" * 100)
rows = [
    ("总交易",     f"{s_v8['n']}",  f"{s_v9['n']}",  f"{s_v10['n']}",  f"{s_v10['n']-s_v8['n']:+d}",  f"{s_v10['n']-s_v9['n']:+d}"),
    ("BUY笔数",    f"{s_v8['longs']}",  f"{s_v9['longs']}",  f"{s_v10['longs']}",  f"{s_v10['longs']-s_v8['longs']:+d}",  f"{s_v10['longs']-s_v9['longs']:+d}"),
    ("SELL笔数",   f"{s_v8['shorts']}", f"{s_v9['shorts']}", f"{s_v10['shorts']}", f"{s_v10['shorts']-s_v8['shorts']:+d}", f"{s_v10['shorts']-s_v9['shorts']:+d}"),
    ("胜率",       f"{s_v8['wr']:.1f}%",  f"{s_v9['wr']:.1f}%",  f"{s_v10['wr']:.1f}%",  f"{s_v10['wr']-s_v8['wr']:+.1f}%",  f"{s_v10['wr']-s_v9['wr']:+.1f}%"),
    ("总盈亏",     f"${s_v8['pnl']:>+10.2f}", f"${s_v9['pnl']:>+10.2f}", f"${s_v10['pnl']:>+10.2f}", f"${s_v10['pnl']-s_v8['pnl']:>+8.2f}", f"${s_v10['pnl']-s_v9['pnl']:>+8.2f}"),
    ("BUY盈亏",    f"${s_v8['long_pnl']:>+8.2f}",  f"${s_v9['long_pnl']:>+8.2f}",  f"${s_v10['long_pnl']:>+8.2f}",  f"${s_v10['long_pnl']-s_v8['long_pnl']:>+6.2f}",  f"${s_v10['long_pnl']-s_v9['long_pnl']:>+6.2f}"),
    ("SELL盈亏",   f"${s_v8['short_pnl']:>+8.2f}", f"${s_v9['short_pnl']:>+8.2f}", f"${s_v10['short_pnl']:>+8.2f}", f"${s_v10['short_pnl']-s_v8['short_pnl']:>+6.2f}", f"${s_v10['short_pnl']-s_v9['short_pnl']:>+6.2f}"),
    ("平均盈利",   f"${s_v8['aw']:>+6.2f}",  f"${s_v9['aw']:>+6.2f}",  f"${s_v10['aw']:>+6.2f}",  f"${s_v10['aw']-s_v8['aw']:+.2f}",  f"${s_v10['aw']-s_v9['aw']:+.2f}"),
    ("平均亏损",   f"${s_v8['al']:>+6.2f}",  f"${s_v9['al']:>+6.2f}",  f"${s_v10['al']:>+6.2f}",  f"${s_v10['al']-s_v8['al']:+.2f}",  f"${s_v10['al']-s_v9['al']:+.2f}"),
    ("盈亏比",     f"{s_v8['aw']/abs(s_v8['al']) if s_v8['al'] else 0:.2f}",
                    f"{s_v9['aw']/abs(s_v9['al']) if s_v9['al'] else 0:.2f}",
                    f"{s_v10['aw']/abs(s_v10['al']) if s_v10['al'] else 0:.2f}", "—", "—"),
    ("利润因子",   f"{s_v8['pf']:.2f}",  f"{s_v9['pf']:.2f}",  f"{s_v10['pf']:.2f}",  f"{s_v10['pf']-s_v8['pf']:+.2f}",  f"{s_v10['pf']-s_v9['pf']:+.2f}"),
    ("最大回撤",   f"${mdd_v8:.2f}",     f"${mdd_v9:.2f}",     f"${mdd_v10:.2f}",     f"${mdd_v10-mdd_v8:+.2f}",     f"${mdd_v10-mdd_v9:+.2f}"),
    ("最大单笔亏", f"${s_v8['max_loss']:>+6.2f}",  f"${s_v9['max_loss']:>+6.2f}",  f"${s_v10['max_loss']:>+6.2f}",  f"${s_v10['max_loss']-s_v8['max_loss']:+.2f}",  f"${s_v10['max_loss']-s_v9['max_loss']:+.2f}"),
    ("最大单笔盈", f"${s_v8['max_win']:>+6.2f}",   f"${s_v9['max_win']:>+6.2f}",   f"${s_v10['max_win']:>+6.2f}",   f"${s_v10['max_win']-s_v8['max_win']:+.2f}",   f"${s_v10['max_win']-s_v9['max_win']:+.2f}"),
    ("均持仓bars", f"{s_v8['avg_bars']}",  f"{s_v9['avg_bars']}",  f"{s_v10['avg_bars']}",  f"{s_v10['avg_bars']-s_v8['avg_bars']:+.1f}",  f"{s_v10['avg_bars']-s_v9['avg_bars']:+.1f}"),
]
for r in rows:
    _print(f"  {r[0]:<18} {r[1]:>14} {r[2]:>14} {r[3]:>14} {r[4]:>16} {r[5]:>16}")

# ── v10 硬止损分析 ──
_print("\n" + "=" * 140)
_print("  [v10 硬止损触发分析]")
_print("=" * 140)
_print(f"  硬止损总触发: {len(hard_sl_log)} 笔 (占总 v10 笔数 {len(trades_v10)} 的 {len(hard_sl_log)/len(trades_v10)*100 if trades_v10 else 0:.1f}%)")
if hard_sl_log:
    hs_buy = [t for t in hard_sl_log if t["dir"] == "BUY"]
    hs_sell = [t for t in hard_sl_log if t["dir"] == "SELL"]
    hs_pnl = sum(t["pnl"] for t in hard_sl_log)
    _print(f"  BUY 硬止损: {len(hs_buy)} 笔, 盈亏 ${sum(t['pnl'] for t in hs_buy):+.2f}")
    _print(f"  SELL 硬止损: {len(hs_sell)} 笔, 盈亏 ${sum(t['pnl'] for t in hs_sell):+.2f}")
    _print(f"  硬止损总盈亏: ${hs_pnl:+.2f}")
    _print(f"  平均止损距离: ${sum(t['sl_dist'] for t in trades_v10)/len(trades_v10):.2f} (入场时 ATR={ATR_PERIOD})")
    # 平均单笔硬止损盈亏 vs 全部 v10 笔
    _print(f"  硬止损平均亏: ${sum(t['pnl'] for t in hard_sl_log)/len(hard_sl_log):+.2f}")
    no_hs = [t for t in trades_v10 if t["reason"] != "硬止损"]
    no_hs_pnl = sum(t["pnl"] for t in no_hs)
    no_hs_max_loss = min((t["pnl"] for t in no_hs), default=0)
    _print(f"  非硬止损笔({len(no_hs)} 笔) 盈亏: ${no_hs_pnl:+.2f}, 最大单笔亏: ${no_hs_max_loss:+.2f}")

# ── 月度对比 ──
_print("\n" + "=" * 140)
_print("  [月度盈亏对比]")
_print("=" * 140)
_print(f"  {'月份':<10} {'v8笔数':>7} {'v8胜率':>8} {'v8盈亏':>11}  "
      f"{'v9笔数':>7} {'v9胜率':>8} {'v9盈亏':>11}  "
      f"{'v10笔数':>8} {'v10胜率':>8} {'v10盈亏':>11}  {'v10-v9':>11}")
_print("  " + "-" * 130)

def monthly(trades):
    m = {}
    for t in trades:
        mm = t["exit_month"]
        m.setdefault(mm, []).append(t)
    return m

mv8 = monthly(trades_v8); mv9 = monthly(trades_v9); mv10 = monthly(trades_v10)
all_months = sorted(set(mv8.keys()) | set(mv9.keys()) | set(mv10.keys()))
for mm in all_months:
    l8 = mv8.get(mm, [])
    l9 = mv9.get(mm, [])
    l10 = mv10.get(mm, [])
    n8 = len(l8); p8 = sum(t["pnl"] for t in l8)
    wr8 = sum(1 for t in l8 if t["pnl"] > 0) / n8 * 100 if n8 else 0
    n9 = len(l9); p9 = sum(t["pnl"] for t in l9)
    wr9 = sum(1 for t in l9 if t["pnl"] > 0) / n9 * 100 if n9 else 0
    n10 = len(l10); p10 = sum(t["pnl"] for t in l10)
    wr10 = sum(1 for t in l10 if t["pnl"] > 0) / n10 * 100 if n10 else 0
    _print(f"  {mm:<10} {n8:>7} {wr8:>7.1f}% ${p8:>+9.2f}  "
          f"{n9:>7} {wr9:>7.1f}% ${p9:>+9.2f}  "
          f"{n10:>8} {wr10:>7.1f}% ${p10:>+9.2f}  ${p10-p9:>+9.2f}")

# ── 出场原因分项 ──
_print("\n" + "=" * 140)
_print("  [v10 出场原因分项]")
_print("=" * 140)
_print(f"  {'原因':<10} {'笔数':>7} {'胜率':>8} {'盈亏':>12} {'平均盈亏':>10} {'BUY数':>7} {'SELL数':>7}")
_print("  " + "-" * 80)
def by_reason(trades):
    m = {}
    for t in trades:
        m.setdefault(t["reason"], []).append(t)
    return m
rv10 = by_reason(trades_v10)
for r in sorted(rv10.keys()):
    l = rv10[r]
    n = len(l); p = sum(t["pnl"] for t in l)
    wr = sum(1 for t in l if t["pnl"] > 0) / n * 100 if n else 0
    avg = p / n if n else 0
    nb = sum(1 for t in l if t["dir"] == "BUY")
    ns = sum(1 for t in l if t["dir"] == "SELL")
    _print(f"  {r:<10} {n:>7} {wr:>7.1f}% ${p:>+10.2f} ${avg:>+8.2f} {nb:>7} {ns:>7}")

# ── v10 vs v9 拦截差异分析 ──
_print("\n" + "=" * 140)
_print("  [v10 vs v9 入场差异: ADX 阈值 30→25 的额外拦截效果]")
_print("=" * 140)

# 重新模拟 v9 的拦截点
v9_block_count = {"buy": 0, "sell": 0}
v10_extra_block_count = {"buy": 0, "sell": 0}
for i in range(MIN_BARS, n_total):
    cl = M30[i].close
    bbu = bb_u[i]; bbm = bb_m[i]; bbl = bb_l[i]
    mfdir = mfi_dir_arr[i]
    adx_i = adx_arr[i]
    if not all(np.isfinite(x) for x in [bbu, bbm, bbl, adx_i, mfdir]):
        continue
    if cl < bbl:
        # v9 拦截: ADX>30 + cl<mid + mfi↓
        if adx_i > 30 and cl < bbm and mfdir == -1:
            v9_block_count["buy"] += 1
        # v10 多拦截的: 25 < ADX <= 30
        elif 25 < adx_i <= 30 and cl < bbm and mfdir == -1:
            v10_extra_block_count["buy"] += 1
    elif cl > bbu:
        if adx_i > 30 and cl > bbm and mfdir == 1:
            v9_block_count["sell"] += 1
        elif 25 < adx_i <= 30 and cl > bbm and mfdir == 1:
            v10_extra_block_count["sell"] += 1
_print(f"  v9 拦截 (ADX>30): BUY {v9_block_count['buy']} 笔, SELL {v9_block_count['sell']} 笔")
_print(f"  v10 比 v9 多拦截 (25<ADX<=30): BUY {v10_extra_block_count['buy']} 笔, SELL {v10_extra_block_count['sell']} 笔")
_print(f"  v10 共拦截: BUY {v9_block_count['buy']+v10_extra_block_count['buy']} 笔, SELL {v9_block_count['sell']+v10_extra_block_count['sell']} 笔")

# ── 总结 ──
_print("\n" + "=" * 140)
_print("  [结论]")
_print("=" * 140)
_print(f"  v8  总盈亏: ${s_v8['pnl']:+.2f}  ({s_v8['n']} 笔, 胜率 {s_v8['wr']:.1f}%)")
_print(f"  v9  总盈亏: ${s_v9['pnl']:+.2f}  ({s_v9['n']} 笔, 胜率 {s_v9['wr']:.1f}%)")
_print(f"  v10 总盈亏: ${s_v10['pnl']:+.2f}  ({s_v10['n']} 笔, 胜率 {s_v10['wr']:.1f}%)")
_print(f"  v10 vs v8: 笔数 {s_v10['n']-s_v8['n']:+d}, 盈亏 ${s_v10['pnl']-s_v8['pnl']:+.2f}")
_print(f"  v10 vs v9: 笔数 {s_v10['n']-s_v9['n']:+d}, 盈亏 ${s_v10['pnl']-s_v9['pnl']:+.2f}")
_print(f"  v10 最大单笔亏: ${s_v10['max_loss']:+.2f} (v8: ${s_v8['max_loss']:+.2f}, v9: ${s_v9['max_loss']:+.2f})")
_print(f"  v10 最大回撤: ${mdd_v10:.2f} (v8: ${mdd_v8:.2f}, v9: ${mdd_v9:.2f})")
_print(f"  耗时: {elapsed:.1f}s")
print("=" * 140)
