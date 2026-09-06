"""
FollowAve v1.2 参数对比测试（历史脚本，已废弃）
================================================
⚠️ 本脚本仅保留 ECB×TRAIL 网格的探索性结果，且默认区间已改为库内全量。
   其 run_v12 硬编码 70/30 + TRAIL 2.0，且 bbi_dir 按 BBI 斜率算——与线上 v1.2
   （proxy bb_mid_direction/SMA20）语义并不一致，数字仅供历史参考，不可直接用于
   "改进是否生效"的判定。
📌 权威回测引擎与 v1.2↔v1.3 对比见 followave_exit_value.py / followave_v1_compare.py。
"""
import sys, sqlite3, numpy as np, datetime as dt
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = 'D:/backup/BaoBao/PythonProgram/xauusd/data/market_data.db'

def load_candles(tf, start='2026-01-01', end='2026-09-30'):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    ts_start = int(dt.datetime.strptime(start, '%Y-%m-%d').replace(
        tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp())
    ts_end = int(dt.datetime.strptime(end, '%Y-%m-%d').replace(
        tzinfo=dt.timezone(dt.timedelta(hours=8))).timestamp()) + 86400
    cur.execute('''
        SELECT timestamp, open, high, low, close, volume
        FROM ohlcv WHERE timeframe=? AND timestamp BETWEEN ? AND ?
        ORDER BY timestamp
    ''', (tf, ts_start, ts_end))
    rows = cur.fetchall()
    conn.close()
    return [{'time': r[0], 'open': r[1], 'high': r[2], 'low': r[3], 'close': r[4], 'volume': r[5]} for r in rows]

def calc_indicators(candles):
    closes = np.array([c['close'] for c in candles], dtype=float)
    highs = np.array([c['high'] for c in candles], dtype=float)
    lows = np.array([c['low'] for c in candles], dtype=float)
    import talib
    sma3 = talib.SMA(closes, 3); sma6 = talib.SMA(closes, 6)
    sma12 = talib.SMA(closes, 12); sma24 = talib.SMA(closes, 24)
    bbi = (sma3 + sma6 + sma12 + sma24) / 4
    stoch_k, stoch_d = talib.STOCH(highs, lows, closes, 5, 3, 0, 3, 0)
    bb_up, bb_mid, bb_low = talib.BBANDS(closes, 20, 2, 2)
    pdi = talib.PLUS_DI(highs, lows, closes, 14)
    ndi = talib.MINUS_DI(highs, lows, closes, 14)
    atr = talib.ATR(highs, lows, closes, 14)
    bbi_dir = np.where(bbi > np.roll(bbi, 1), 'up',
                  np.where(bbi < np.roll(bbi, 1), 'down', 'flat'))
    bbi_dir[0] = 'flat'
    for i, c in enumerate(candles):
        c['bbi'] = bbi[i]; c['stoch_k'] = stoch_k[i]; c['stoch_d'] = stoch_d[i]
        c['bb_mid'] = bb_mid[i]; c['bb_up'] = bb_up[i]; c['bb_low'] = bb_low[i]
        c['pdi'] = pdi[i]; c['ndi'] = ndi[i]; c['atr'] = atr[i]; c['bbi_dir'] = bbi_dir[i]
    return candles

def run_v12(candles, EXIT_CONFIRM_BARS=3, TRAIL_ATR=2.0):
    trades = []
    in_pos = False; direction = None; entry_price = 0; entry_bar = -1
    exit_count = 0; last_bar_time = 0; trail_peak = None
    touched_bb_extreme = False; pending = None
    DI_GATE = 5; STOCH_K_OB = 70; STOCH_K_OS = 30
    STOCH_EXIT_OB = 80; STOCH_EXIT_OS = 20; BB_TOL = 3
    for i in range(30, len(candles)):
        row = candles[i-1]
        bbi = row['bbi']; close = row['close']; high = row['high']; low = row['low']
        pdi = row['pdi']; ndi = row['ndi']
        stoch_k = row['stoch_k']; stoch_d = row['stoch_d']
        bb_mid = row['bb_mid']; bb_up = row['bb_up']; bb_low = row['bb_low']
        bbi_dir = row['bbi_dir']; atr_val = row['atr']
        if any(np.isnan(v) for v in [bbi, close, pdi, ndi, stoch_k, atr_val]):
            continue
        if pending and not in_pos:
            entry_price = candles[i]['open']; entry_bar = i; direction = pending
            in_pos = True; exit_count = 0; trail_peak = None
            touched_bb_extreme = False; pending = None
            last_bar_time = candles[i]['time']
            continue
        if in_pos:
            if candles[i]['time'] == last_bar_time:
                continue
            last_bar_time = candles[i]['time']
            prev = candles[i-2] if i >= 2 else None
            k_prev = prev['stoch_k'] if prev and not np.isnan(prev['stoch_k']) else stoch_k
            d_prev = prev['stoch_d'] if prev and not np.isnan(prev['stoch_d']) else stoch_d
            if direction == 'LONG':
                if trail_peak is None or high > trail_peak:
                    trail_peak = high
                if high >= bb_up - BB_TOL:
                    touched_bb_extreme = True
                # 1) overbought cross TP
                if touched_bb_extreme and stoch_k < stoch_d and k_prev >= d_prev and stoch_k > STOCH_EXIT_OB:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'LONG', 'ep': entry_price, 'xp': close, 'pnl': close - entry_price, 'reason': 'overbought_cross'})
                    in_pos = False; direction = None; continue
                # 2) trend reversal
                if close < bbi and bbi_dir == 'down':
                    exit_count += 1
                else:
                    exit_count = 0
                if exit_count >= EXIT_CONFIRM_BARS:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'LONG', 'ep': entry_price, 'xp': close, 'pnl': close - entry_price, 'reason': 'trend_reversal'})
                    in_pos = False; direction = None; continue
                # 3) bb stop
                if close < bb_low:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'LONG', 'ep': entry_price, 'xp': close, 'pnl': close - entry_price, 'reason': 'bb_stop'})
                    in_pos = False; direction = None; continue
                # 4) trailing
                if TRAIL_ATR > 0 and trail_peak is not None:
                    trail_stop = trail_peak - TRAIL_ATR * atr_val
                    if close < trail_stop:
                        trades.append({'entry': entry_bar, 'exit': i, 'dir': 'LONG', 'ep': entry_price, 'xp': close, 'pnl': close - entry_price, 'reason': 'trailing'})
                        in_pos = False; direction = None; continue
            else:
                if trail_peak is None or low < trail_peak:
                    trail_peak = low
                if low <= bb_low + BB_TOL:
                    touched_bb_extreme = True
                if touched_bb_extreme and stoch_k > stoch_d and k_prev <= d_prev and stoch_k < STOCH_EXIT_OS:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'SHORT', 'ep': entry_price, 'xp': close, 'pnl': entry_price - close, 'reason': 'oversold_cross'})
                    in_pos = False; direction = None; continue
                if close > bbi and bbi_dir == 'up':
                    exit_count += 1
                else:
                    exit_count = 0
                if exit_count >= EXIT_CONFIRM_BARS:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'SHORT', 'ep': entry_price, 'xp': close, 'pnl': entry_price - close, 'reason': 'trend_reversal'})
                    in_pos = False; direction = None; continue
                if close > bb_up:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'SHORT', 'ep': entry_price, 'xp': close, 'pnl': entry_price - close, 'reason': 'bb_stop'})
                    in_pos = False; direction = None; continue
                if TRAIL_ATR > 0 and trail_peak is not None:
                    trail_stop = trail_peak + TRAIL_ATR * atr_val
                    if close > trail_stop:
                        trades.append({'entry': entry_bar, 'exit': i, 'dir': 'SHORT', 'ep': entry_price, 'xp': close, 'pnl': entry_price - close, 'reason': 'trailing'})
                        in_pos = False; direction = None; continue
            continue
        if abs(pdi - ndi) <= DI_GATE:
            continue
        prev = candles[i-2] if i >= 2 else None
        k_prev = prev['stoch_k'] if prev and not np.isnan(prev['stoch_k']) else stoch_k
        d_prev = prev['stoch_d'] if prev and not np.isnan(prev['stoch_d']) else stoch_d
        golden = stoch_k > stoch_d and k_prev <= d_prev
        death = stoch_k < stoch_d and k_prev >= d_prev
        if pdi > ndi and close > bbi and golden and stoch_k < STOCH_K_OB and close >= bb_mid:
            pending = 'LONG'
        elif ndi > pdi and close < bbi and death and stoch_k > STOCH_K_OS and close <= bb_mid:
            pending = 'SHORT'
    return trades

def summarize(trades):
    if not trades:
        return 0, 0, 0, {}, 0, 0, 0
    total = len(trades)
    wins = sum(1 for t in trades if t['pnl'] > 0)
    wr = wins / total * 100
    pnl = sum(t['pnl'] for t in trades)
    avg = pnl / total
    mxw = max(t['pnl'] for t in trades)
    mxl = min(t['pnl'] for t in trades)
    reasons = {}
    for t in trades:
        r = t['reason']
        reasons.setdefault(r, {'c': 0, 'p': 0.0})
        reasons[r]['c'] += 1
        reasons[r]['p'] += t['pnl']
    return total, wr, pnl, reasons, avg, mxw, mxl

if __name__ == '__main__':
    for tf in ['M15', 'M30']:
        print(f'\n{"="*60}')
        print(f'{tf}')
        print('='*60)
        candles = load_candles(tf)
        candles = calc_indicators(candles)
        print(f'数据: {len(candles)} 根 K 线')
        print(f'\n{"Param":<22} {"Trades":>6} {"WR%":>6} {"PnL":>9} {"Avg":>6} {"Reasons"}')
        print('-'*100)
        results = []
        for ecb in [2, 3]:
            for trail in [2.0, 3.0, 4.0]:
                trades = run_v12(candles, EXIT_CONFIRM_BARS=ecb, TRAIL_ATR=trail)
                total, wr, pnl, reasons, avg, mxw, mxl = summarize(trades)
                results.append((ecb, trail, total, wr, pnl, avg, reasons))
                r_str = ' '.join(f'{k}:{v["c"]}({v["p"]:+.0f})' for k, v in sorted(reasons.items(), key=lambda x: -x[1]['c']))
                print(f'ECB={ecb} Trail={trail:<4.1f} {total:>6} {wr:>5.1f} {pnl:>+9.1f} {avg:>+5.1f}  {r_str}')
        # best
        best = max(results, key=lambda x: x[4])
        print(f'\n[BEST] ECB={best[0]} Trail={best[1]} PnL={best[4]:+.2f} WR={best[3]:.1f}% Trades={best[2]}')
