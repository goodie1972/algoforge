"""
mfi_bb_m30_upgraded (v8) 数据库回测
====================================
复现策略 v8 升级版逻辑：
  入场: close<bb_lower (BUY) / close>bb_upper (SELL)
        BB扩张保护: bwr>1.05 + 方向扩张 + MFI方向一致 2/3 → 禁同向
  出场:
    ① 顺势平: 穿轨后回抽 + MFI穿50
    ② 逆势平1: 回到BB中轴
    ③ 逆势平2: 走了开仓时BB宽度的一半

额外分析: ADX>25 下跌趋势期单独统计
"""
import os, sys, math, time
from datetime import datetime

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
BB_EXPAND_THRESHOLD = 0.05  # bb_width_ratio > 1+0.05 触发保护

# ── 读取 M30 数据 ──
conn = get_conn()
rows = conn.execute(
    "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
).fetchall()
conn.close()
M30 = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in rows]
print(f"加载 M30 K线: {len(M30)} 根  "
      f"({datetime.fromtimestamp(int(M30[0].time)):%Y-%m-%d} ~ "
      f"{datetime.fromtimestamp(int(M30[-1].time)):%Y-%m-%d})")

# ── 预计算指标 ──
arr_open = np.array([c.open for c in M30], dtype=np.float64)
arr_high = np.array([c.high for c in M30], dtype=np.float64)
arr_low = np.array([c.low for c in M30], dtype=np.float64)
arr_close = np.array([c.close for c in M30], dtype=np.float64)
arr_vol = np.array([c.volume for c in M30], dtype=np.float64)

# BB(20, 2)
bb_u, bb_m, bb_l = talib.BBANDS(arr_close, timeperiod=BB_PERIOD, nbdevup=BB_STD, nbdevdn=BB_STD)
# MFI(14)
mfi = talib.MFI(arr_high, arr_low, arr_close, arr_vol, timeperiod=MFI_PERIOD)
# ATR(14) for hard-stop
atr = talib.ATR(arr_high, arr_low, arr_close, timeperiod=14)
# ADX(14) +DI -DI
adx_arr = talib.ADX(arr_high, arr_low, arr_close, timeperiod=ADX_PERIOD)
pdi_arr = talib.PLUS_DI(arr_high, arr_low, arr_close, timeperiod=ADX_PERIOD)
ndi_arr = talib.MINUS_DI(arr_high, arr_low, arr_close, timeperiod=ADX_PERIOD)

# BB width series
bb_widths = bb_u - bb_l
# SMA3 of widths
widths_sma3 = talib.SMA(bb_widths, timeperiod=3)
# bb_width_ratio = current / sma3
bb_w_ratio = np.where(widths_sma3 > 0, bb_widths / widths_sma3, 1.0)

# bb_width_direction (vs prev)
prev_widths = np.concatenate([[bb_widths[0]], bb_widths[:-1]])
bb_w_dir = np.where(bb_widths > prev_widths, 1,
                    np.where(bb_widths < prev_widths, -1, 0))  # 1=up -1=down 0=flat

# mfi_direction (vs prev)
prev_mfi = np.concatenate([[mfi[0]], mfi[:-1]])
mfi_dir = np.where(mfi > prev_mfi, 1,
                   np.where(mfi < prev_mfi, -1, 0))


def is_finite(*vals):
    return all((v is not None) and np.isfinite(v) for v in vals)


# ── 回测主循环 ──
trades = []
running_pnl = 0.0
peak = 0.0
max_dd = 0.0

pos_dir = None       # "BUY" / "SELL" / None
entry_price = 0.0
entry_idx = 0
trail = {}            # ticket-side: bb_width, bb_mid, has_crossed_band

signals = 0
buys = 0
sells = 0
skipped_no_indic = 0

t0 = time.time()
n = len(M30)

for i in range(MIN_BARS, n):
    c = M30[i]
    cl = float(c.close)
    bid = cl
    ask = cl
    ts = int(c.time)

    # ── 读取指标 ──
    bb_u_i = bb_u[i]
    bb_m_i = bb_m[i]
    bb_l_i = bb_l[i]
    mfi_i = mfi[i]
    bwr_i = bb_w_ratio[i]
    bwd_i = bb_w_dir[i]
    mfdir_i = mfi_dir[i]
    adx_i = adx_arr[i]
    pdi_i = pdi_arr[i]
    ndi_i = ndi_arr[i]

    if not is_finite(bb_u_i, bb_m_i, bb_l_i, mfi_i, bwr_i, adx_i):
        skipped_no_indic += 1
        continue

    # ── ① 出场检查 ──
    if pos_dir is not None:
        td = trail
        is_buy = pos_dir == "BUY"
        current_price = bid if is_buy else ask
        exit_now = False
        exit_reason = None

        # ① 顺势平: 穿轨后回抽 + MFI穿50
        if is_buy:
            if not td["has_crossed_band"] and bid > bb_u_i:
                td["has_crossed_band"] = True
            if td["has_crossed_band"] and bid <= bb_u_i + 0.01 and mfi_i > 50:
                exit_now = True
                exit_reason = "顺势穿轨回抽"
        else:
            if not td["has_crossed_band"] and ask < bb_l_i:
                td["has_crossed_band"] = True
            if td["has_crossed_band"] and ask >= bb_l_i - 0.01 and mfi_i < 50:
                exit_now = True
                exit_reason = "顺势穿轨回抽"

        # ② 逆势平1: 回到BB中轴
        if not exit_now and not td["has_crossed_band"]:
            if is_buy and current_price >= bb_m_i:
                exit_now = True
                exit_reason = "中轴平"
            elif (not is_buy) and current_price <= bb_m_i:
                exit_now = True
                exit_reason = "中轴平"

        # ③ 逆势平2: 走了开仓时BB宽度的一半
        if not exit_now:
            half_w = td["entry_bb_width"] / 2
            if is_buy and current_price >= entry_price + half_w:
                exit_now = True
                exit_reason = "半宽平"
            elif (not is_buy) and current_price <= entry_price - half_w:
                exit_now = True
                exit_reason = "半宽平"

        if exit_now:
            pnl = (cl - entry_price) * CONTRACT * LOT - COMMISSION if is_buy else (entry_price - cl) * CONTRACT * LOT - COMMISSION
            trades.append({
                "dir": pos_dir,
                "ep": round(entry_price, 2),
                "ex": round(cl, 2),
                "pnl": round(pnl, 2),
                "bars": i - entry_idx,
                "reason": exit_reason,
                "entry_t": datetime.fromtimestamp(int(M30[entry_idx].time)).strftime("%m-%d %H:%M"),
                "exit_t": datetime.fromtimestamp(ts).strftime("%m-%d %H:%M"),
                "adx_at_entry": td.get("adx_entry", 0),
                "adx_now": round(float(adx_i), 1),
                "mfi_now": round(float(mfi_i), 1),
            })
            running_pnl += pnl
            if running_pnl > peak:
                peak = running_pnl
            if peak - running_pnl > max_dd:
                max_dd = peak - running_pnl
            pos_dir = None
            trail = {}

    # ── ② 入场检查 ──
    if pos_dir is None:
        # BB扩张保护: 3选2
        block_long = False
        block_short = False
        score = 0
        if bwr_i > 1 + BB_EXPAND_THRESHOLD:
            score += 1
        if bwd_i == 1:  # 方向扩张
            score += 1
        if cl > bb_m_i and mfdir_i in (1, 0):
            score += 1
        if cl < bb_m_i and mfdir_i in (-1, 0):
            score += 1
        if score >= 2:
            if cl > bb_m_i and mfdir_i in (1, 0):
                block_short = True
            if cl < bb_m_i and mfdir_i in (-1, 0):
                block_long = True

        # 入场信号
        buy_signal = cl < bb_l_i and not block_long
        sell_signal = cl > bb_u_i and not block_short

        if buy_signal:
            pos_dir = "BUY"
            entry_price = cl
            entry_idx = i
            trail = {
                "entry_bb_width": float(bb_u_i - bb_l_i),
                "entry_bb_mid": float(bb_m_i),
                "has_crossed_band": False,
                "adx_entry": round(float(adx_i), 1),
            }
            signals += 1
            buys += 1
        elif sell_signal:
            pos_dir = "SELL"
            entry_price = cl
            entry_idx = i
            trail = {
                "entry_bb_width": float(bb_u_i - bb_l_i),
                "entry_bb_mid": float(bb_m_i),
                "has_crossed_band": False,
                "adx_entry": round(float(adx_i), 1),
            }
            signals += 1
            sells += 1

# ── 强制收尾 ──
if pos_dir is not None:
    cl = M30[-1].close
    pnl = (cl - entry_price) * CONTRACT * LOT - COMMISSION if pos_dir == "BUY" else (entry_price - cl) * CONTRACT * LOT - COMMISSION
    trades.append({
        "dir": pos_dir,
        "ep": round(entry_price, 2),
        "ex": round(cl, 2),
        "pnl": round(pnl, 2),
        "bars": n - 1 - entry_idx,
        "reason": "END",
        "entry_t": datetime.fromtimestamp(int(M30[entry_idx].time)).strftime("%m-%d %H:%M"),
        "exit_t": datetime.fromtimestamp(int(M30[-1].time)).strftime("%m-%d %H:%M"),
        "adx_at_entry": trail.get("adx_entry", 0),
        "adx_now": round(float(adx_arr[-1]), 1),
        "mfi_now": round(float(mfi[-1]), 1),
    })

elapsed = time.time() - t0
n_tr = len(trades)
wins = [t for t in trades if t["pnl"] > 0]
losses = [t for t in trades if t["pnl"] <= 0]
wr = len(wins) / n_tr * 100 if n_tr else 0
aw = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
al = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
gp = sum(t["pnl"] for t in wins)
gl = abs(sum(t["pnl"] for t in losses))
pf = gp / gl if gl else 999
longs = [t for t in trades if t["dir"] == "BUY"]
shorts = [t for t in trades if t["dir"] == "SELL"]
long_pnl = sum(t["pnl"] for t in longs)
short_pnl = sum(t["pnl"] for t in shorts)
long_wr = sum(1 for t in longs if t["pnl"] > 0) / len(longs) * 100 if longs else 0
short_wr = sum(1 for t in shorts if t["pnl"] > 0) / len(shorts) * 100 if shorts else 0

print(f"\n{'=' * 100}")
print(f"  mfi_bb_m30_upgraded v8 — 数据库回测报告")
print(f"  {'=' * 96}")
print(f"  数据源:    data/market_data.db (SQLite)")
print(f"  M30 范围:  {len(M30):,} 根 K线 "
      f"({datetime.fromtimestamp(int(M30[0].time)):%Y-%m-%d} ~ "
      f"{datetime.fromtimestamp(int(M30[-1].time)):%Y-%m-%d})")
print(f"  初始资金:  $10,000  |  LOT: 0.01  |  合约: 100  |  佣金: $0.50")
print(f"  耗时:      {elapsed:.1f}s")
print(f"  信号触发:  {signals} (BUY={buys}  SELL={sells})")
print(f"  跳过(指标缺失): {skipped_no_indic}")
print(f"  {'=' * 96}")
print(f"  [核心指标]")
print(f"  总交易:     {n_tr}")
print(f"  总盈亏:     ${running_pnl:>+10.2f}  ({running_pnl / 10000 * 100:+.2f}%)")
print(f"  胜率:       {wr:.1f}%  ({len(wins)}胜 / {len(losses)}负)")
print(f"  平均盈利:   ${aw:+.2f}  |  平均亏损: ${al:+.2f}  |  盈亏比: {abs(aw / al) if al else 0:.2f}")
print(f"  利润因子:   {pf:.2f}")
print(f"  最大回撤:   ${max_dd:.2f}  ({max_dd / 10000 * 100:.2f}%)")
print(f"  {'=' * 96}")

# ── 多空分项 ──
print(f"\n  [方向分项]")
print(f"  BUY  {len(longs):>4}笔  胜率 {long_wr:5.1f}%  盈亏 ${long_pnl:>+9.2f}")
print(f"  SELL {len(shorts):>4}笔  胜率 {short_wr:5.1f}%  盈亏 ${short_pnl:>+9.2f}")

# ── 出场原因分项 ──
print(f"\n  [出场原因]")
reasons = {}
for t in trades:
    r = t["reason"]
    reasons.setdefault(r, {"n": 0, "pnl": 0.0, "wins": 0})
    reasons[r]["n"] += 1
    reasons[r]["pnl"] += t["pnl"]
    if t["pnl"] > 0:
        reasons[r]["wins"] += 1
for r, d in reasons.items():
    wr2 = d["wins"] / d["n"] * 100 if d["n"] else 0
    print(f"  {r:<14} {d['n']:>4}笔  胜率{wr2:5.1f}%  盈亏 ${d['pnl']:>+8.2f}")

# ── ADX>25 下跌趋势期表现 ──
print(f"\n  [ADX>25 趋势期表现]")
adx_high_trades = [t for t in trades if t["adx_at_entry"] > 25]
if adx_high_trades:
    wins_2 = [t for t in adx_high_trades if t["pnl"] > 0]
    pnl_2 = sum(t["pnl"] for t in adx_high_trades)
    wr_2 = len(wins_2) / len(adx_high_trades) * 100
    print(f"  ADX>25 共 {len(adx_high_trades)} 笔, 胜率 {wr_2:.1f}%, 总盈亏 ${pnl_2:+.2f}")
    # 按 ADX 分桶
    buckets = [(25, 30), (30, 40), (40, 100)]
    for lo, hi in buckets:
        bucket = [t for t in adx_high_trades if lo <= t["adx_at_entry"] < hi]
        if not bucket:
            continue
        bw = [t for t in bucket if t["pnl"] > 0]
        bp = sum(t["pnl"] for t in bucket)
        bwr = len(bw) / len(bucket) * 100
        print(f"    ADX {lo}-{hi}: {len(bucket):>3}笔  胜率 {bwr:5.1f}%  盈亏 ${bp:>+8.2f}")

# ── 月度统计 ──
print(f"\n  [月份盈亏]")
monthly = {}
for t in trades:
    m = t["exit_t"][:2]
    monthly.setdefault(m, {"n": 0, "wins": 0, "pnl": 0.0})
    monthly[m]["n"] += 1
    monthly[m]["pnl"] += t["pnl"]
    if t["pnl"] > 0:
        monthly[m]["wins"] += 1
for m in sorted(monthly.keys()):
    d = monthly[m]
    wr2 = d["wins"] / d["n"] * 100 if d["n"] else 0
    print(f"    {m}月: {d['n']:>3}笔  胜率 {wr2:5.1f}%  盈亏 ${d['pnl']:>+8.2f}")

# ── 连续盈亏 ──
mw = ml = cw = cl = 0
for t in trades:
    if t["pnl"] > 0:
        cw += 1
        cl = 0
        mw = max(mw, cw)
    else:
        cl += 1
        cw = 0
        ml = max(ml, cl)
print(f"\n  最大连胜: {mw}  最大连败: {ml}")

# ── 最近 15 笔明细 ──
print(f"\n  [最近 15 笔交易]")
print(f"  {'方向':<5} {'入场':>8} {'出场':>8} {'盈亏':>8} {'bars':>4}  {'ADX入':>5}  {'ADX出':>5}  {'MFI出':>5}  {'理由':<14} {'时间':<12}")
for t in trades[-15:]:
    sgn = "+" if t["pnl"] > 0 else ""
    print(f"  {t['dir']:<5} {t['ep']:>8.2f} {t['ex']:>8.2f} {sgn}${t['pnl']:>+6.2f} "
          f"{t['bars']:>4}  {t['adx_at_entry']:>5.1f}  {t['adx_now']:>5.1f}  {t['mfi_now']:>5.1f}  "
          f"{t['reason']:<14} {t['exit_t']:<12}")

# ── 全部交易明细 (CSV 风格摘要) ──
print(f"\n  [全部交易明细] (共 {n_tr} 笔)")
print(f"  {'方向':<5} {'入场':>8} {'出场':>8} {'盈亏':>8} {'bars':>4}  {'ADX入':>5}  {'理由':<14} {'时间':<12}")
for t in trades:
    sgn = "+" if t["pnl"] > 0 else ""
    print(f"  {t['dir']:<5} {t['ep']:>8.2f} {t['ex']:>8.2f} {sgn}${t['pnl']:>+6.2f} "
          f"{t['bars']:>4}  {t['adx_at_entry']:>5.1f}  {t['reason']:<14} {t['exit_t']:<12}")
print(f"{'=' * 100}")
