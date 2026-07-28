"""
stoch_trend_h1_upgraded 回测
  v10 真正逆势: K<=35 金叉做多, K>=65 死叉做空
  对比 v9 趋势中段 (K>=65 金叉做多, K<=35 死叉做空)
"""
import sqlite3
import numpy as np
import pandas as pd
import talib
from datetime import datetime

DB = r'D:\backup\BaoBao\PythonProgram\xauusd\data\market_data.db'
TF = 'H1'
LOT = 0.01
CONTRACT = 100
COMM = 0.50
STOCH_K = 14
STOCH_D = 3
STOCH_S = 3
ADX_PERIOD = 14
ADX_THRESHOLD = 25
MFI_PERIOD = 14
BB_PERIOD = 20
BB_STD = 2


def load_data():
    conn = sqlite3.connect(DB)
    df = pd.read_sql(f"SELECT timestamp, open, high, low, close FROM ohlcv WHERE timeframe='{TF}' ORDER BY timestamp", conn)
    conn.close()
    arr_h = df['high'].values.astype(float)
    arr_l = df['low'].values.astype(float)
    arr_c = df['close'].values.astype(float)
    df['stoch_k'], df['stoch_d'] = talib.STOCH(arr_h, arr_l, arr_c, fastk_period=STOCH_K, slowk_period=STOCH_D, slowd_period=STOCH_S)
    df['adx'] = talib.ADX(arr_h, arr_l, arr_c, timeperiod=ADX_PERIOD)
    df['mfi'] = talib.MFI(arr_h, arr_l, arr_c, df['volume'].values, MFI_PERIOD) if 'volume' in df.columns else np.zeros(len(df))
    df['mfi_dir'] = np.where(df['mfi'] > 50, 1, np.where(df['mfi'] < 50, -1, 0))
    df['bb_u'], df['bb_m'], df['bb_l'] = talib.BBANDS(arr_c, BB_PERIOD, BB_STD, BB_STD)
    df['ema21'] = talib.EMA(arr_c, 21)
    df['pdi'] = talib.PLUS_DI(arr_h, arr_l, arr_c, timeperiod=ADX_PERIOD)
    df['ndi'] = talib.MINUS_DI(arr_h, arr_l, arr_c, timeperiod=ADX_PERIOD)
    df = df.dropna().reset_index(drop=True)
    return df


def run_sim(df, version="v10"):
    """回测：v10 真逆势, v9 追涨杀跌"""
    trades = []
    n = len(df)
    pos_dir, ep, ei, trail = None, 0, 0, {}

    for i in range(50, n):
        cl = df['close'].iloc[i]
        k_curr = df['stoch_k'].iloc[i]
        d_curr = df['stoch_d'].iloc[i]
        k_prev = df['stoch_k'].iloc[i-1] if i > 0 else 50
        d_prev = df['stoch_d'].iloc[i-1] if i > 0 else 50
        adx = df['adx'].iloc[i]
        mfi_dir = df['mfi_dir'].iloc[i]
        bbm = df['bb_m'].iloc[i]
        ma21 = df['ema21'].iloc[i]
        pdi = df['pdi'].iloc[i]
        ndi = df['ndi'].iloc[i]

        if not np.isfinite([k_curr, d_curr, k_prev, d_prev, adx, bbm, ma21, pdi, ndi]).all():
            continue

        # 出场
        if pos_dir is not None:
            is_buy = pos_dir == "BUY"
            td = trail
            ex, reason = False, None
            # 止盈
            if is_buy and cl >= ep * 1.03: ex, reason = True, "止盈"
            if (not is_buy) and cl <= ep * 0.97: ex, reason = True, "止盈"
            # 止损 (1.5×ATR)
            if not ex:
                atr_val = df['bb_u'].iloc[i] - df['bb_l'].iloc[i]  # 用 BB 宽度近似 ATR
                if is_buy and cl <= ep - 1.5 * atr_val: ex, reason = True, "止损"
                if (not is_buy) and cl >= ep + 1.5 * atr_val: ex, reason = True, "止损"
            if ex:
                pnl = (cl - ep) * CONTRACT * LOT - COMM if is_buy else (ep - cl) * CONTRACT * LOT - COMM
                trades.append({"dir": pos_dir, "ep": ep, "ex": cl, "pnl": pnl, "bars": i - ei,
                                "reason": reason, "k_at_exit": k_curr, "ts": int(df['timestamp'].iloc[i]),
                                "entry_ts": int(df['timestamp'].iloc[ei])})
                pos_dir = None
                trail = {}

        # 入场
        if pos_dir is None:
            if adx > ADX_THRESHOLD:
                cross_up_now = (k_curr > d_curr) and (k_prev <= d_prev)
                cross_down_now = (k_curr < d_curr) and (k_prev >= d_prev)
                has_extreme_buy = k_curr < 20
                has_extreme_sell = k_curr > 80

                long_score, short_score = 0, 0

                if version == "v10":
                    # 真正逆势：K<=35 金叉做多, K>=65 死叉做空
                    if cross_up_now and k_curr <= 35:
                        long_score += 2
                        if has_extreme_buy:
                            long_score += 1
                    if cross_down_now and k_curr >= 65:
                        short_score += 2
                        if has_extreme_sell:
                            short_score += 1
                else:
                    # v9 趋势中段：K>=65 金叉做多, K<=35 死叉做空（追涨杀跌）
                    if cross_up_now and k_curr >= 65:
                        long_score += 2
                        if has_extreme_buy:
                            long_score += 1
                    if cross_down_now and k_curr <= 35:
                        short_score += 2
                        if has_extreme_sell:
                            short_score += 1

                # 辅助分
                if cl > ma21: long_score += 1
                if cl < ma21: short_score += 1
                if pdi > ndi: long_score += 1
                if ndi > pdi: short_score += 1
                if h4_down(df, i): short_score += 1
                if h4_up(df, i): long_score += 1

                if long_score >= 4:
                    pos_dir, ep, ei = "BUY", cl, i
                    trail = {"cross_time": df['timestamp'].iloc[i]}
                elif short_score >= 4:
                    pos_dir, ep, ei = "SELL", cl, i
                    trail = {"cross_time": df['timestamp'].iloc[i]}

    if pos_dir:
        cl = df['close'].iloc[-1]
        pnl = (cl - ep) * CONTRACT * LOT - COMM if pos_dir == "BUY" else (ep - cl) * CONTRACT * LOT - COMM
        trades.append({"dir": pos_dir, "ep": ep, "ex": cl, "pnl": pnl, "bars": n - 1 - ei,
                        "reason": "END", "k_at_exit": k_curr, "ts": int(df['timestamp'].iloc[-1]),
                        "entry_ts": int(df['timestamp'].iloc[ei])})

    return trades


def h4_down(df, i):
    if i < 4: return False
    return df['ema21'].iloc[i] < df['ema21'].iloc[i-4]


def h4_up(df, i):
    if i < 4: return False
    return df['ema21'].iloc[i] > df['ema21'].iloc[i-4]


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
    running = peak = mdd = 0
    for t in trades:
        running += t['pnl']
        if running > peak: peak = running
        if peak - running > mdd: mdd = peak - running
    buys = [t for t in trades if t['dir'] == 'BUY']
    sells = [t for t in trades if t['dir'] == 'SELL']
    return (
        f"  {label}:\n"
        f"    笔数: {len(trades)} (BUY {len(buys)} / SELL {len(sells)})  胜率: {wr:.1f}%\n"
        f"    总盈亏: ${total:+.2f}  盈亏比: {avg_w/abs(avg_l) if avg_l else 0:.2f}  PF: {pf:.2f}\n"
        f"    最大单笔盈: ${max_w:+.2f}  最大单笔亏: ${max_l:+.2f}\n"
        f"    最大回撤: ${mdd:.2f}\n"
        f"    BUY 盈亏: ${sum(t['pnl'] for t in buys):+.2f}  SELL 盈亏: ${sum(t['pnl'] for t in sells):+.2f}\n"
    )


def main():
    print("=" * 80)
    print("  stoch_trend_h1_upgraded v9 vs v10 对比回测")
    print("  v9 = 追涨杀跌: K>=65 金叉做多, K<=35 死叉做空")
    print("  v10 = 真逆势: K<=35 金叉做多, K>=65 死叉做空")
    print("=" * 80)

    df = load_data()
    print(f"  H1 数据: {len(df)} 根  ({datetime.fromtimestamp(df['timestamp'].iloc[0])} ~ {datetime.fromtimestamp(df['timestamp'].iloc[-1])})\n")

    trades_v9 = run_sim(df, version="v9")
    trades_v10 = run_sim(df, version="v10")

    # 找 outlier
    print("  [v9 大单 Top 5]")
    sorted_v9 = sorted(trades_v9, key=lambda t: t['pnl'], reverse=True)
    for t in sorted_v9[:5]:
        from datetime import datetime as dt
        entry_dt = dt.fromtimestamp(t.get('entry_ts', 0))
        exit_dt = dt.fromtimestamp(t.get('ts', 0))
        print(f"    {t['dir']:4s}  entry={t['ep']:8.2f}  exit={t['ex']:8.2f}  pnl=${t['pnl']:+8.2f}  bars={t['bars']:5d}  {t['reason']:6s}  {entry_dt} → {exit_dt}")

    print("\n  [v9 小单 Bottom 5]")
    for t in sorted_v9[-5:]:
        from datetime import datetime as dt
        entry_dt = dt.fromtimestamp(t.get('entry_ts', 0))
        exit_dt = dt.fromtimestamp(t.get('ts', 0))
        print(f"    {t['dir']:4s}  entry={t['ep']:8.2f}  exit={t['ex']:8.2f}  pnl=${t['pnl']:+8.2f}  bars={t['bars']:5d}  {t['reason']:6s}  {entry_dt} → {exit_dt}")

    print(stats(trades_v9, "v9 (追涨杀跌)"))
    print()
    print(stats(trades_v10, "v10 (真逆势)"))

    # 排除 outlier 后的真实表现
    v9_no_outlier = sum(t['pnl'] for t in trades_v9 if t['pnl'] < 1000)
    v10_no_outlier = sum(t['pnl'] for t in trades_v10 if abs(t['pnl']) < 500)

    total_v9 = sum(t['pnl'] for t in trades_v9)
    total_v10 = sum(t['pnl'] for t in trades_v10)
    print(f"  [结论]")
    print(f"  v9  2.5 年总盈亏: ${total_v9:+.2f}  (笔数 {len(trades_v9)})")
    print(f"  v9 排除 $1000+ outlier: ${v9_no_outlier:+.2f}")
    print(f"  v10 2.5 年总盈亏: ${total_v10:+.2f}  (笔数 {len(trades_v10)})")
    print(f"  v10 排除 $500+ outlier: ${v10_no_outlier:+.2f}")
    print(f"  v10 vs v9: {total_v10 - total_v9:+.2f}")
    if total_v10 > 0 and total_v10 > total_v9:
        print(f"  ✅ v10 扭亏为盈! 多赚 ${total_v10 - total_v9:.2f}")
    elif total_v10 > total_v9:
        print(f"  ✓ v10 改善, 少亏 ${total_v9 - total_v10:.2f}")
    else:
        print(f"  ✗ v10 仍亏, 多亏 ${total_v10 - total_v9:.2f}")


if __name__ == "__main__":
    main()
