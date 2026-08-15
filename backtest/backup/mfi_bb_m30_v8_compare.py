"""
mfi_bb_m30 v8 - 多配置对比回测
=============================
对比以下变种:
  当前 v8: BB扩张保护 + 无ADX过滤 + 无硬止损
  A: 关闭BB保护
  B: 关闭BB保护 + ADX<30
  C: BB保护 + ADX<30
  D: BB保护 + ADX<25
  E: BB保护 + 硬止损 2x ATR
  F: BB保护 + ADX<30 + 硬止损 2x ATR
  G: BB保护 + ADX<30 + 硬止损 1.5x ATR
"""
import os, sys, math, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import logging
logging.basicConfig(level=logging.WARNING, stream=sys.stdout)

import numpy as np
import talib
from data.database import get_conn
from core.bridge import Candle

COMMISSION = 0.5
LOT = 0.01
CONTRACT = 100
MIN_BARS = 100
BB_PERIOD = 20
BB_STD = 2.0
MFI_PERIOD = 14
ADX_PERIOD = 14

conn = get_conn()
rows = conn.execute(
    "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
).fetchall()
conn.close()
M30 = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in rows]

arr_high = np.array([c.high for c in M30])
arr_low = np.array([c.low for c in M30])
arr_close = np.array([c.close for c in M30])
arr_vol = np.array([c.volume for c in M30])

bb_u, bb_m, bb_l = talib.BBANDS(arr_close, timeperiod=BB_PERIOD, nbdevup=BB_STD, nbdevdn=BB_STD)
mfi = talib.MFI(arr_high, arr_low, arr_close, arr_vol, timeperiod=MFI_PERIOD)
atr = talib.ATR(arr_high, arr_low, arr_close, timeperiod=14)
adx_arr = talib.ADX(arr_high, arr_low, arr_close, timeperiod=ADX_PERIOD)
pdi_arr = talib.PLUS_DI(arr_high, arr_low, arr_close, timeperiod=ADX_PERIOD)
ndi_arr = talib.MINUS_DI(arr_high, arr_low, arr_close, timeperiod=ADX_PERIOD)

bb_widths = bb_u - bb_l
widths_sma3 = talib.SMA(bb_widths, timeperiod=3)
bb_w_ratio = np.where(widths_sma3 > 0, bb_widths / widths_sma3, 1.0)
prev_w = np.concatenate([[bb_widths[0]], bb_widths[:-1]])
bb_w_dir = np.where(bb_widths > prev_w, 1, np.where(bb_widths < prev_w, -1, 0))
prev_mfi = np.concatenate([[mfi[0]], mfi[:-1]])
mfi_dir_arr = np.where(mfi > prev_mfi, 1, np.where(mfi < prev_mfi, -1, 0))

n_total = len(M30)


def run(use_bb_guard, adx_max, use_hard_sl, hard_sl_atr):
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
        bbu = bb_u[i]
        bbm = bb_m[i]
        bbl = bb_l[i]
        mfi_i = mfi[i]
        bwr = bb_w_ratio[i]
        bwd = bb_w_dir[i]
        mfdir = mfi_dir_arr[i]
        adx_i = adx_arr[i]
        atr_i = atr[i]
        if not all(np.isfinite(x) for x in [bbu, bbm, bbl, mfi_i, bwr, adx_i, atr_i]):
            continue

        # 出场
        if pos_dir is not None:
            is_buy = pos_dir == "BUY"
            td = trail
            ex = False
            reason = None
            if use_hard_sl:
                if is_buy and (ep - cl) > atr_i * hard_sl_atr:
                    ex, reason = True, "硬止损"
                elif (not is_buy) and (cl - ep) > atr_i * hard_sl_atr:
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
                trades.append({
                    "dir": pos_dir, "ep": ep, "ex": cl, "pnl": pnl,
                    "bars": i - ei, "adx_in": td.get("ax", 0), "reason": reason,
                })
                running += pnl
                if running > peak:
                    peak = running
                if peak - running > mdd:
                    mdd = peak - running
                pos_dir = None
                trail = {}

        # 入场
        if pos_dir is None:
            block_l = block_s = False
            if use_bb_guard:
                s = 0
                if bwr > 1.05:
                    s += 1
                if bwd == 1:
                    s += 1
                if cl > bbm and mfdir in (1, 0):
                    s += 1
                if cl < bbm and mfdir in (-1, 0):
                    s += 1
                if s >= 2:
                    if cl > bbm and mfdir in (1, 0):
                        block_s = True
                    if cl < bbm and mfdir in (-1, 0):
                        block_l = True
            adx_ok = (adx_i <= adx_max)
            if cl < bbl and not block_l and adx_ok:
                pos_dir = "BUY"
                ep = cl
                ei = i
                trail = {"bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1)}
            elif cl > bbu and not block_s and adx_ok:
                pos_dir = "SELL"
                ep = cl
                ei = i
                trail = {"bw": bbu - bbl, "crossed": False, "ax": round(adx_i, 1)}

    if pos_dir:
        cl = M30[-1].close
        pnl = (cl - ep) * CONTRACT * LOT - COMMISSION if pos_dir == "BUY" else (ep - cl) * CONTRACT * LOT - COMMISSION
        trades.append({
            "dir": pos_dir, "ep": ep, "ex": cl, "pnl": pnl,
            "bars": n_total - 1 - ei, "adx_in": trail.get("ax", 0), "reason": "END",
        })

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    n_tr = len(trades)
    wr = len(wins) / n_tr * 100 if n_tr else 0
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = gp / gl if gl else 999
    return {
        "n": n_tr,
        "pnl": round(running, 2),
        "wr": wr,
        "pf": round(pf, 2),
        "mdd": round(mdd, 2),
        "longs": sum(1 for t in trades if t["dir"] == "BUY"),
        "shorts": sum(1 for t in trades if t["dir"] == "SELL"),
        "long_pnl": round(sum(t["pnl"] for t in trades if t["dir"] == "BUY"), 2),
        "short_pnl": round(sum(t["pnl"] for t in trades if t["dir"] == "SELL"), 2),
        "aw": round(gp / len(wins), 2) if wins else 0,
        "al": round(-gl / len(losses), 2) if losses else 0,
        "max_loss": round(min(t["pnl"] for t in trades), 2) if trades else 0,
        "avg_bars": round(sum(t["bars"] for t in trades) / n_tr, 1) if n_tr else 0,
    }


print("=" * 130)
print("  mfi_bb_m30_upgraded v8 - 多配置对比回测")
print("=" * 130)
print(f"  M30 数据: {n_total} 根")
print(f"  LOT=0.01  COMMISSION=$0.50  CONTRACT=100")
print("=" * 130)

cfgs = [
    ("当前 v8 (有BB保护, 无ADX过滤, 无硬止损)", True,  999, False, 0),
    ("A: 关闭BB扩张保护",                          False, 999, False, 0),
    ("B: 关闭BB保护 + ADX<30 过滤",                False, 30,  False, 0),
    ("C: BB保护 + ADX<30 过滤",                    True,  30,  False, 0),
    ("D: BB保护 + ADX<25 过滤",                    True,  25,  False, 0),
    ("E: BB保护 + 硬止损 2x ATR",                  True,  999, True,  2.0),
    ("F: BB保护 + ADX<30 + 硬止损 2x ATR",         True,  30,  True,  2.0),
    ("G: BB保护 + ADX<30 + 硬止损 1.5x ATR",       True,  30,  True,  1.5),
]
header = (
    f"{'配置':<46} {'交易':>5} {'胜率':>6} {'P/L':>9} {'PF':>6} {'DD':>8} "
    f"{'BUY':>4} {'SELL':>4} {'多P/L':>8} {'空P/L':>8} {'均盈':>7} {'均亏':>7} {'最大亏':>8} {'均bars':>6}"
)
print(header)
print("-" * 130)
for label, bb, adx_max, sl, sl_atr in cfgs:
    r = run(use_bb_guard=bb, adx_max=adx_max, use_hard_sl=sl, hard_sl_atr=sl_atr)
    flag = "V" if r["pnl"] > 0 else "X"
    print(
        f"{label:<46} {r['n']:>5} {r['wr']:>5.1f}% ${r['pnl']:>+7.2f} {r['pf']:>5.2f} "
        f"${r['mdd']:>6.2f} {r['longs']:>4} {r['shorts']:>4} ${r['long_pnl']:>+6.2f} "
        f"${r['short_pnl']:>+6.2f} ${r['aw']:>+5.2f} ${r['al']:>+5.2f} ${r['max_loss']:>+6.2f} {r['avg_bars']:>6} {flag}"
    )
print("=" * 130)
