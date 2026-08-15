"""
stoch_trend_h1_upgraded v12 KDJ 周期策略 回测 (修正版)
入场: ADX>25 + KDJ交叉 + K<50(Buy)/K>50(Sell) + BBI 方向
出场: 极值入场等反向极值+KDJ反向; 非极值入场BBI反转或KDJ反向
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
STOCH_FASTK = 5
STOCH_SLOWK = 3
STOCH_SLOWD = 3
ADX_PERIOD = 14
BBI_PERIODS = (3, 6, 12, 24)
K_MIDLINE = 50
K_EXTREME_BUY = 20
K_EXTREME_SELL = 80


def load_data():
    conn = sqlite3.connect(DB)
    df = pd.read_sql(f"SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='{TF}' ORDER BY timestamp", conn)
    conn.close()
    arr_h = df['high'].values.astype(float)
    arr_l = df['low'].values.astype(float)
    arr_c = df['close'].values.astype(float)
    df['stoch_k'], df['stoch_d'] = talib.STOCH(arr_h, arr_l, arr_c, fastk_period=STOCH_FASTK, slowk_period=STOCH_SLOWK, slowd_period=STOCH_SLOWD)
    df['adx'] = talib.ADX(arr_h, arr_l, arr_c, timeperiod=ADX_PERIOD)
    bbi = np.zeros(len(df))
    for p in BBI_PERIODS:
        bbi += df['close'].rolling(p).mean().values
    bbi /= len(BBI_PERIODS)
    df['bbi'] = bbi
    df = df.dropna().reset_index(drop=True)
    return df


def run_sim_v12(df):
    """v12 KDJ 周期策略"""
    trades = []
    n = len(df)
    pos_dir, ep, ei, trail = None, 0, 0, {}

    for i in range(50, n):
        cl = df['close'].iloc[i]
        k_curr = df['stoch_k'].iloc[i]
        d_curr = df['stoch_d'].iloc[i]
        k_prev = df['stoch_k'].iloc[i-1]
        d_prev = df['stoch_d'].iloc[i-1]
        adx = df['adx'].iloc[i]
        bbi = df['bbi'].iloc[i]

        if not np.isfinite([k_curr, d_curr, k_prev, d_prev, adx, bbi]).all():
            continue

        cross_up = (k_curr > d_curr) and (k_prev <= d_prev)
        cross_down = (k_curr < d_curr) and (k_prev >= d_prev)

        # 出场
        if pos_dir is not None:
            is_buy = pos_dir == "BUY"
            entry_k = trail.get('entry_k', 50)
            is_extreme = trail.get('is_extreme', False)
            ex = False
            reason = None
            if is_buy:
                # KDJ 死叉
                if cross_down:
                    if is_extreme:
                        if k_curr > K_EXTREME_SELL and d_curr > K_EXTREME_SELL:
                            ex, reason = True, "BUY 极值出场"
                    else:
                        ex, reason = True, "BUY KDJ反向"
                # 非极值入场: BBI 反转也出场
                if not ex and not is_extreme and cl < bbi:
                    ex, reason = True, "BUY BBI反转"
            else:  # SELL
                if cross_up:
                    if is_extreme:
                        if k_curr < K_EXTREME_BUY and d_curr < K_EXTREME_BUY:
                            ex, reason = True, "SELL 极值出场"
                    else:
                        ex, reason = True, "SELL KDJ反向"
                if not ex and not is_extreme and cl > bbi:
                    ex, reason = True, "SELL BBI反转"
            if ex:
                pnl = (cl - ep) * CONTRACT * LOT - COMM if is_buy else (ep - cl) * CONTRACT * LOT - COMM
                trades.append({"dir": pos_dir, "ep": ep, "ex": cl, "pnl": pnl,
                                "bars": i - ei, "reason": reason,
                                "k_at_exit": k_curr, "d_at_exit": d_curr,
                                "ts": int(df['timestamp'].iloc[i]),
                                "entry_ts": int(df['timestamp'].iloc[ei]),
                                "entry_k": entry_k, "is_extreme": is_extreme})
                pos_dir = None
                trail = {}

        # 入场
        if pos_dir is None:
            if adx > 25:
                # BUY: 金叉 + K<50 + close>BBI
                if cross_up and k_curr < K_MIDLINE and cl > bbi:
                    pos_dir, ep, ei = "BUY", cl, i
                    trail = {"entry_k": k_curr, "is_extreme": k_curr < K_EXTREME_BUY, "cross_time": int(df['timestamp'].iloc[i])}
                # SELL: 死叉 + K>50 + close<BBI
                elif cross_down and k_curr > K_MIDLINE and cl < bbi:
                    pos_dir, ep, ei = "SELL", cl, i
                    trail = {"entry_k": k_curr, "is_extreme": k_curr > K_EXTREME_SELL, "cross_time": int(df['timestamp'].iloc[i])}

    if pos_dir:
        cl = df['close'].iloc[-1]
        pnl = (cl - ep) * CONTRACT * LOT - COMM if pos_dir == "BUY" else (ep - cl) * CONTRACT * LOT - COMM
        trades.append({"dir": pos_dir, "ep": ep, "ex": cl, "pnl": pnl, "bars": n - 1 - ei,
                        "reason": "END", "k_at_exit": k_curr, "ts": int(df['timestamp'].iloc[-1]),
                        "entry_ts": int(df['timestamp'].iloc[ei])})

    return trades


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
        f"    平均持仓: {np.mean([t['bars'] for t in trades]):.1f} bars ({np.mean([t['bars'] for t in trades])*1:.0f} 小时)\n"
        f"    最大回撤: ${mdd:.2f}\n"
        f"    BUY 盈亏: ${sum(t['pnl'] for t in buys):+.2f}  SELL 盈亏: ${sum(t['pnl'] for t in sells):+.2f}\n"
    )


def main():
    print("=" * 80)
    print("  stoch_trend_h1_upgraded v12 KDJ 周期策略 (修正版)")
    print("=" * 80)
    print("  入场: ADX>25 + KDJ交叉 + K<50(Buy)/K>50(Sell) + BBI方向")
    print("  出场: 极值入场等反向极值+KDJ反向; 非极值入场BBI反转或KDJ反向")
    print("=" * 80)

    df = load_data()
    print(f"  H1 数据: {len(df)} 根  ({datetime.fromtimestamp(df['timestamp'].iloc[0])} ~ {datetime.fromtimestamp(df['timestamp'].iloc[-1])})\n")

    trades = run_sim_v12(df)
    print(stats(trades, "v12 KDJ周期 (修正版)"))

    # 详细列出每笔交易
    if trades:
        print("\n  [每笔交易明细]")
        print(f"  {'方向':4s} {'入场K':>6s} {'极值':>4s} {'入场价':>8s} {'离场K':>6s} {'离场价':>8s} {'持仓bars':>8s} {'盈亏':>8s} {'原因':12s}")
        for t in trades:
            ek = t.get('entry_k', 0)
            ie = "Y" if t.get('is_extreme') else "N"
            xk = t.get('k_at_exit', 0)
            from datetime import datetime as dt
            entry_dt = dt.fromtimestamp(t.get('entry_ts', 0)).strftime('%Y-%m-%d')
            print(f"  {t['dir']:4s} {ek:6.1f} {ie:>4s} {t['ep']:8.2f} {xk:6.1f} {t['ex']:8.2f} {t['bars']:8d} {t['pnl']:>+8.2f} {t['reason']:12s}  ({entry_dt})")

    total = sum(t['pnl'] for t in trades)
    print(f"\n  [结论]")
    print(f"  v12 总盈亏: ${total:+.2f}  (笔数 {len(trades)})")
    if total > 0:
        print(f"  ✅ v12 扭亏为盈!")


if __name__ == "__main__":
    main()
