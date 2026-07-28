"""
mfi_bb_m30_upgraded v8 vs v12 对比回测
  v8:  BB扩张 3选2 保护 + 无硬止损
  v12: BB扩张 3选2 保护 + 1.5×ATR 统一硬止损
"""
import sqlite3
import numpy as np
import pandas as pd
import talib
from datetime import datetime

DB = r'D:\backup\BaoBao\PythonProgram\xauusd\data\market_data.db'
TF = 'M30'
LOT = 0.01
CONTRACT = 100
COMM = 0.50
BB_PERIOD = 20
BB_STD = 2
ATR_PERIOD = 14
MFI_PERIOD = 14
BB_EXPAND = 1.05


def load_data():
    conn = sqlite3.connect(DB)
    df = pd.read_sql(f"SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='{TF}' ORDER BY timestamp", conn)
    conn.close()
    arr_h = df['high'].values.astype(float)
    arr_l = df['low'].values.astype(float)
    arr_c = df['close'].values.astype(float)
    df['bb_u'], df['bb_m'], df['bb_l'] = talib.BBANDS(arr_c, BB_PERIOD, BB_STD, BB_STD)
    df['bbw'] = (df['bb_u'] - df['bb_l']) / df['bb_m']
    df['bbw_ratio'] = df['bbw'] / talib.SMA(df['bbw'].values, 3)
    df['bbw_dir'] = np.where(df['bbw_ratio'] > df['bbw_ratio'].shift(1), 1, np.where(df['bbw_ratio'] < df['bbw_ratio'].shift(1), -1, 0))
    df['atr'] = talib.ATR(arr_h, arr_l, arr_c, ATR_PERIOD)
    df['mfi'] = talib.MFI(arr_h, arr_l, arr_c, df['volume'].values if 'volume' in df else np.zeros(len(df)), MFI_PERIOD) if 'volume' in df.columns else np.zeros(len(df))
    df['mfi_dir'] = np.where(df['mfi'] > 50, 1, np.where(df['mfi'] < 50, -1, 0))
    df = df.dropna().reset_index(drop=True)
    return df


def v8_block_check(cl, bbm, bwr, bwd, mfdir):
    """v8: 3选2 模糊打分"""
    s = 0
    if bwr is not None and bwr > BB_EXPAND: s += 1
    if bwd is not None and bwd == 1: s += 1
    if cl > bbm and mfdir in (1, 0): s += 1
    if cl < bbm and mfdir in (-1, 0): s += 1
    block_l = (cl < bbm and mfdir in (-1, 0))
    block_s = (cl > bbm and mfdir in (1, 0))
    if s < 2:
        block_l = block_s = False
    return block_l, block_s


def run_sim(df, use_hard_sl=False):
    """回测: v8 = no hard stop, v12 = 1.5×ATR hard stop"""
    trades = []
    n = len(df)
    pos_dir, ep, ei, trail = None, 0, 0, {}
    hard_sl_log = []

    for i in range(50, n):
        cl = df['close'].iloc[i]
        ts = int(df['timestamp'].iloc[i])
        bbu, bbm, bbl = df['bb_u'].iloc[i], df['bb_m'].iloc[i], df['bb_l'].iloc[i]
        bwr, bwd = df['bbw_ratio'].iloc[i], df['bbw_dir'].iloc[i]
        mfi_v, mfdir = df['mfi'].iloc[i], df['mfi_dir'].iloc[i]
        atr_v = df['atr'].iloc[i]
        if not np.isfinite([bbu, bbm, bbl, bwr, bwd, mfi_v, atr_v]).all():
            continue

        # 出场
        if pos_dir is not None:
            is_buy = pos_dir == "BUY"
            td = trail
            ex, reason = False, None
            # 硬止损
            if use_hard_sl:
                if is_buy and cl <= td["sl_price"]: ex, reason = True, "硬止损"
                elif (not is_buy) and cl >= td["sl_price"]: ex, reason = True, "硬止损"
            if not ex:
                if is_buy:
                    if not td["crossed"] and cl > bbu:
                        td["crossed"] = True
                    if td["crossed"] and cl <= bbu + 0.01 and mfi_v > 50:
                        ex, reason = True, "顺势穿轨+MFI50"
                else:
                    if not td["crossed"] and cl < bbl:
                        td["crossed"] = True
                    if td["crossed"] and cl >= bbl - 0.01 and mfi_v < 50:
                        ex, reason = True, "顺势穿轨+MFI50"
            if not ex:
                if is_buy and cl >= bbm: ex, reason = True, "中轴"
                if (not is_buy) and cl <= bbm: ex, reason = True, "中轴"
            if not ex:
                bw = bbu - bbl
                if is_buy and cl >= ep + bw / 2: ex, reason = True, "半宽"
                if (not is_buy) and cl <= ep - bw / 2: ex, reason = True, "半宽"
            if ex:
                pnl = (cl - ep) * CONTRACT * LOT - COMM if is_buy else (ep - cl) * CONTRACT * LOT - COMM
                trades.append({"dir": pos_dir, "ep": ep, "ex": cl, "pnl": pnl, "bars": i - ei,
                                "reason": reason, "ts": ts, "sl_dist": td.get("sl_dist", 0)})
                if reason == "硬止损": hard_sl_log.append(trades[-1])
                pos_dir = None
                trail = {}

        # 入场
        if pos_dir is None:
            block_l, block_s = v8_block_check(cl, bbm, bwr, bwd, mfdir)
            if cl < bbl and not block_l:
                pos_dir, ep, ei = "BUY", cl, i
                sl_dist = 1.5 * atr_v if use_hard_sl else None
                sl_price = cl - sl_dist if use_hard_sl else None
                trail = {"bw": bbu - bbl, "crossed": False, "ax": 0, "sl_price": sl_price, "sl_dist": sl_dist or 0}
            elif cl > bbu and not block_s:
                pos_dir, ep, ei = "SELL", cl, i
                sl_dist = 1.5 * atr_v if use_hard_sl else None
                sl_price = cl + sl_dist if use_hard_sl else None
                trail = {"bw": bbu - bbl, "crossed": False, "ax": 0, "sl_price": sl_price, "sl_dist": sl_dist or 0}

    # 末尾平仓
    if pos_dir:
        cl, ts = df['close'].iloc[-1], int(df['timestamp'].iloc[-1])
        pnl = (cl - ep) * CONTRACT * LOT - COMM if pos_dir == "BUY" else (ep - cl) * CONTRACT * LOT - COMM
        trades.append({"dir": pos_dir, "ep": ep, "ex": cl, "pnl": pnl, "bars": n - 1 - ei,
                        "reason": "END", "ts": ts, "sl_dist": trail.get("sl_dist", 0)})

    return trades, hard_sl_log


def stats(trades, label):
    if not trades:
        return f"  {label}: 无交易"
    total = sum(t['pnl'] for t in trades)
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    wr = len(wins) / len(trades) * 100
    avg_w = np.mean([t['pnl'] for t in wins]) if wins else 0
    avg_l = np.mean([t['pnl'] for t in losses]) if losses else 0
    pf = sum(t['pnl'] for t in wins) / max(1, abs(sum(t['pnl'] for t in losses)))
    max_w = max(t['pnl'] for t in trades)
    max_l = min(t['pnl'] for t in trades)
    avg_bars = np.mean([t['bars'] for t in trades])
    # MDD
    running = 0
    peak = 0
    mdd = 0
    for t in trades:
        running += t['pnl']
        if running > peak: peak = running
        if peak - running > mdd: mdd = peak - running
    buys = [t for t in trades if t['dir'] == 'BUY']
    sells = [t for t in trades if t['dir'] == 'SELL']
    hard_sl = [t for t in trades if t['reason'] == '硬止损']
    return (
        f"  {label}:\n"
        f"    笔数: {len(trades)} (BUY {len(buys)} / SELL {len(sells)})  胜率: {wr:.1f}%\n"
        f"    总盈亏: ${total:+.2f}  盈亏比: {avg_w/abs(avg_l) if avg_l else 0:.2f}  PF: {pf:.2f}\n"
        f"    最大单笔盈: ${max_w:+.2f}  最大单笔亏: ${max_l:+.2f}\n"
        f"    平均持仓: {avg_bars:.1f} bars\n"
        f"    最大回撤: ${mdd:.2f}\n"
        f"    BUY 盈亏: ${sum(t['pnl'] for t in buys):+.2f}  SELL 盈亏: ${sum(t['pnl'] for t in sells):+.2f}\n"
        f"    硬止损: {len(hard_sl)} 笔  盈亏: ${sum(t['pnl'] for t in hard_sl):+.2f}\n"
    )


def main():
    print("=" * 80)
    print("  mfi_bb_m30_upgraded  v8 vs v12 对比回测")
    print("  v8 = BB扩张3选2 (无止损), v12 = BB扩张3选2 + 1.5×ATR 硬止损")
    print("=" * 80)

    df = load_data()
    print(f"  M30 数据: {len(df)} 根  ({datetime.fromtimestamp(df['timestamp'].iloc[0])} ~ {datetime.fromtimestamp(df['timestamp'].iloc[-1])})\n")

    trades_v8, _ = run_sim(df, use_hard_sl=False)
    trades_v12, hard_sl_v12 = run_sim(df, use_hard_sl=True)

    print(stats(trades_v8, "v8 (无硬止损)"))
    print()
    print(stats(trades_v12, "v12 (1.5×ATR 硬止损)"))
    print()

    # 月度对比
    def by_month(trs):
        m = {}
        for t in trs:
            month = datetime.fromtimestamp(t['ts']).strftime('%Y-%m')
            if month not in m: m[month] = []
            m[month].append(t['pnl'])
        return m

    m8 = by_month(trades_v8)
    m12 = by_month(trades_v12)
    months = sorted(set(m8.keys()) | set(m12.keys()))
    print("  [月度盈亏对比]")
    print(f"  {'月份':<10} {'v8 笔数':>8} {'v8 盈亏':>12} {'v12 笔数':>10} {'v12 盈亏':>12} {'v12-v8':>10}")
    for mo in months:
        v8_n, v8_p = len(m8.get(mo, [])), sum(m8.get(mo, []))
        v12_n, v12_p = len(m12.get(mo, [])), sum(m12.get(mo, []))
        diff = v12_p - v8_p
        print(f"  {mo:<10} {v8_n:>8} {v8_p:>+12.2f} {v12_n:>10} {v12_p:>+12.2f} {diff:>+10.2f}")

    print()
    total_v8 = sum(t['pnl'] for t in trades_v8)
    total_v12 = sum(t['pnl'] for t in trades_v12)
    print(f"  [结论]")
    print(f"  v8  4 月总盈亏: ${total_v8:+.2f}  (笔数 {len(trades_v8)})")
    print(f"  v12 4 月总盈亏: ${total_v12:+.2f}  (笔数 {len(trades_v12)})")
    print(f"  v12 硬止损触发: {len(hard_sl_v12)} 笔  盈亏: ${sum(t['pnl'] for t in hard_sl_v12):+.2f}")
    print(f"  v12 vs v8: {total_v12 - total_v8:+.2f}  ({(total_v12 - total_v8)/abs(total_v8)*100 if total_v8 else 0:+.1f}%)")
    if total_v12 > 0:
        print(f"  ✅ v12 扭亏为盈! 相比 v8 多赚 ${total_v12 - total_v8:.2f}")
    elif total_v12 > total_v8:
        print(f"  ✓ v12 改善, 相比 v8 少亏 ${total_v8 - total_v12:.2f}")
    else:
        print(f"  ✗ v12 仍亏, 相比 v8 多亏 ${total_v12 - total_v8:.2f}")


if __name__ == "__main__":
    main()
