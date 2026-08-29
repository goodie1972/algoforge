"""
FollowAve v1.0 vs v1.2 对比回测
=============================
v1.0: 使用当前未完成蜡烛 candles[-1]，per-tick 出场计数
v1.2: 使用已完成蜡烛 candles[-2]，per-candle 出场计数，4 层出场优先级
      ① 超买死叉止盈（曾触 BB 上轨 + K>80 死叉）
      ② 趋势反转止盈（close 跌破 BBI + bbi_dir down，连续 3 根）
      ③ BB 硬止损（close 跌破 BB 下轨）
      ④ Trailing Stop（2.0×ATR 从最高点回撤）
"""
import sys, os, sqlite3, json, numpy as np, datetime as dt
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = 'D:/backup/BaoBao/PythonProgram/xauusd/data/market_data.db'

def load_candles(tf, start='2026-07-01', end='2026-08-27'):
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
    """计算所有指标"""
    closes = np.array([c['close'] for c in candles], dtype=float)
    highs = np.array([c['high'] for c in candles], dtype=float)
    lows = np.array([c['low'] for c in candles], dtype=float)
    
    import talib
    
    # BBI
    sma3 = talib.SMA(closes, 3)
    sma6 = talib.SMA(closes, 6)
    sma12 = talib.SMA(closes, 12)
    sma24 = talib.SMA(closes, 24)
    bbi = (sma3 + sma6 + sma12 + sma24) / 4
    
    # Stoch
    stoch_k, stoch_d = talib.STOCH(highs, lows, closes, 5, 3, 0, 3, 0)
    
    # BB
    bb_up, bb_mid, bb_low = talib.BBANDS(closes, 20, 2, 2)
    
    # ±DI
    pdi = talib.PLUS_DI(highs, lows, closes, 14)
    ndi = talib.MINUS_DI(highs, lows, closes, 14)
    
    # ATR
    atr = talib.ATR(highs, lows, closes, 14)
    
    # BBI direction (bb_mid_direction)
    bbi_dir = np.where(bbi > np.roll(bbi, 1), 'up', 
                  np.where(bbi < np.roll(bbi, 1), 'down', 'flat'))
    bbi_dir[0] = 'flat'
    
    # Store
    for i, c in enumerate(candles):
        c['bbi'] = bbi[i]
        c['stoch_k'] = stoch_k[i]
        c['stoch_d'] = stoch_d[i]
        c['bb_mid'] = bb_mid[i]
        c['bb_up'] = bb_up[i]
        c['bb_low'] = bb_low[i]
        c['pdi'] = pdi[i]
        c['ndi'] = ndi[i]
        c['atr'] = atr[i]
        c['bbi_dir'] = bbi_dir[i]
    
    return candles

def run_v1(candles):
    """v1.0: 使用 candles[-1]（当前未完成蜡烛），per-tick 计数"""
    trades = []
    in_pos = False
    direction = None
    entry_price = 0
    entry_bar = -1
    exit_count = 0
    pending = None
    
    for i in range(30, len(candles)):
        row = candles[i]
        bbi = row['bbi']
        close = row['close']
        pdi = row['pdi']
        ndi = row['ndi']
        stoch_k = row['stoch_k']
        stoch_d = row['stoch_d']
        bb_mid = row['bb_mid']
        
        if any(np.isnan(v) for v in [bbi, close, pdi, ndi, stoch_k]):
            continue
        
        # 执行挂单
        if pending and not in_pos:
            entry_price = row['open']
            entry_bar = i
            direction = pending
            in_pos = True
            exit_count = 0
            pending = None
            continue
        
        # 持仓中：出场（v1.0 per-tick 计数）
        if in_pos:
            if direction == 'LONG':
                if close < bbi:
                    exit_count += 1
                else:
                    exit_count = 0
                if exit_count >= 3:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'LONG', 
                                   'ep': entry_price, 'xp': close, 
                                   'pnl': close - entry_price, 'reason': 'trend_reversal'})
                    in_pos = False; direction = None
            else:  # SHORT
                if close > bbi:
                    exit_count += 1
                else:
                    exit_count = 0
                if exit_count >= 3:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'SHORT',
                                   'ep': entry_price, 'xp': close,
                                   'pnl': entry_price - close, 'reason': 'trend_reversal'})
                    in_pos = False; direction = None
            continue
        
        # 空仓：入场
        if abs(pdi - ndi) <= 5:
            continue
        if pdi > ndi and close > bbi and stoch_k > stoch_d and stoch_k < 80 and close >= bb_mid:
            pending = 'LONG'
        elif ndi > pdi and close < bbi and stoch_k < stoch_d and stoch_k > 20 and close <= bb_mid:
            pending = 'SHORT'
    
    return trades

def run_v12(candles):
    """v1.2: 使用已完成蜡烛 candles[-2]，per-candle 计数，4 层出场优先级"""
    trades = []
    in_pos = False
    direction = None
    entry_price = 0
    entry_bar = -1
    exit_count = 0
    last_bar_time = 0
    trail_peak = None
    touched_bb_extreme = False
    pending = None
    
    # 参数
    DI_GATE = 5
    EXIT_CONFIRM_BARS = 3
    TRAIL_ATR = 2.0
    STOCH_K_OVERBOUGHT = 70
    STOCH_K_OVERSOLD = 30
    STOCH_EXIT_OVERBOUGHT = 80
    STOCH_EXIT_OVERSOLD = 20
    BB_EXTREME_TOLERANCE = 3
    
    for i in range(30, len(candles)):
        # v1.2 使用已完成蜡烛 candles[-2]
        row = candles[i-1]  # 上一根已完成蜡烛
        bbi = row['bbi']
        close = row['close']
        high = row['high']
        low = row['low']
        pdi = row['pdi']
        ndi = row['ndi']
        stoch_k = row['stoch_k']
        stoch_d = row['stoch_d']
        bb_mid = row['bb_mid']
        bb_up = row['bb_up']
        bb_low = row['bb_low']
        bbi_dir = row['bbi_dir']
        atr_val = row['atr']
        
        if any(np.isnan(v) for v in [bbi, close, pdi, ndi, stoch_k, atr_val]):
            continue
        
        # 执行挂单
        if pending and not in_pos:
            entry_price = candles[i]['open']
            entry_bar = i
            direction = pending
            in_pos = True
            exit_count = 0
            trail_peak = None
            touched_bb_extreme = False
            pending = None
            last_bar_time = candles[i]['time']
            continue
        
        # 持仓中：出场（v1.2 per-candle 计数 + last_bar_time 防重）
        if in_pos:
            # 防重：只在蜡烛收盘时检查一次
            if candles[i]['time'] == last_bar_time:
                continue
            last_bar_time = candles[i]['time']
            
            # Stoch 穿越（用于超买/超卖止盈）：对比前一根已完成 K 线
            prev = candles[i-2] if i >= 2 else None
            k_prev = prev['stoch_k'] if prev and not np.isnan(prev['stoch_k']) else stoch_k
            d_prev = prev['stoch_d'] if prev and not np.isnan(prev['stoch_d']) else stoch_d
            
            if direction == 'LONG':
                # 更新 trailing peak
                if trail_peak is None or high > trail_peak:
                    trail_peak = high
                
                # 标记是否触碰过 BB 上轨
                if high >= bb_up - BB_EXTREME_TOLERANCE:
                    touched_bb_extreme = True
                
                # ① 超买死叉止盈：曾触 BB 上轨 + Stoch K>80 死叉
                if touched_bb_extreme and stoch_k < stoch_d and k_prev >= d_prev and stoch_k > STOCH_EXIT_OVERBOUGHT:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'LONG',
                                   'ep': entry_price, 'xp': close,
                                   'pnl': close - entry_price, 'reason': 'overbought_cross'})
                    in_pos = False; direction = None; continue
                
                # ② 趋势反转止盈：close < BBI + bbi_dir=down，连续 N 根
                if close < bbi and bbi_dir == 'down':
                    exit_count += 1
                else:
                    exit_count = 0
                if exit_count >= EXIT_CONFIRM_BARS:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'LONG',
                                   'ep': entry_price, 'xp': close,
                                   'pnl': close - entry_price, 'reason': 'trend_reversal'})
                    in_pos = False; direction = None; continue
                
                # ③ BB 硬止损
                if close < bb_low:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'LONG',
                                   'ep': entry_price, 'xp': close,
                                   'pnl': close - entry_price, 'reason': 'bb_stop'})
                    in_pos = False; direction = None; continue
                
                # ④ Trailing Stop
                if TRAIL_ATR > 0 and trail_peak is not None:
                    trail_stop = trail_peak - TRAIL_ATR * atr_val
                    if close < trail_stop:
                        trades.append({'entry': entry_bar, 'exit': i, 'dir': 'LONG',
                                       'ep': entry_price, 'xp': close,
                                       'pnl': close - entry_price, 'reason': 'trailing'})
                        in_pos = False; direction = None; continue
            else:  # SHORT
                # 更新 trailing peak
                if trail_peak is None or low < trail_peak:
                    trail_peak = low
                
                # 标记是否触碰过 BB 下轨
                if low <= bb_low + BB_EXTREME_TOLERANCE:
                    touched_bb_extreme = True
                
                # ① 超卖金叉止盈：曾触 BB 下轨 + Stoch K<20 金叉
                if touched_bb_extreme and stoch_k > stoch_d and k_prev <= d_prev and stoch_k < STOCH_EXIT_OVERSOLD:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'SHORT',
                                   'ep': entry_price, 'xp': close,
                                   'pnl': entry_price - close, 'reason': 'oversold_cross'})
                    in_pos = False; direction = None; continue
                
                # ② 趋势反转止盈：close > BBI + bbi_dir=up，连续 N 根
                if close > bbi and bbi_dir == 'up':
                    exit_count += 1
                else:
                    exit_count = 0
                if exit_count >= EXIT_CONFIRM_BARS:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'SHORT',
                                   'ep': entry_price, 'xp': close,
                                   'pnl': entry_price - close, 'reason': 'trend_reversal'})
                    in_pos = False; direction = None; continue
                
                # ③ BB 硬止损
                if close > bb_up:
                    trades.append({'entry': entry_bar, 'exit': i, 'dir': 'SHORT',
                                   'ep': entry_price, 'xp': close,
                                   'pnl': entry_price - close, 'reason': 'bb_stop'})
                    in_pos = False; direction = None; continue
                
                # ④ Trailing Stop
                if TRAIL_ATR > 0 and trail_peak is not None:
                    trail_stop = trail_peak + TRAIL_ATR * atr_val
                    if close > trail_stop:
                        trades.append({'entry': entry_bar, 'exit': i, 'dir': 'SHORT',
                                       'ep': entry_price, 'xp': close,
                                       'pnl': entry_price - close, 'reason': 'trailing'})
                        in_pos = False; direction = None; continue
            continue
        
        # 空仓：入场（使用已完成蜡烛数据，穿越检测）
        if abs(pdi - ndi) <= DI_GATE:
            continue
        
        # 穿越检测：对比前一根已完成 K 线 Stoch
        prev = candles[i-2] if i >= 2 else None
        k_prev = prev['stoch_k'] if prev and not np.isnan(prev['stoch_k']) else stoch_k
        d_prev = prev['stoch_d'] if prev and not np.isnan(prev['stoch_d']) else stoch_d
        
        # 多头：当根金叉（k>d）且前根未金叉（k_prev<=d_prev）
        golden_cross = stoch_k > stoch_d and k_prev <= d_prev
        # 空头：当根死叉（k<d）且前根未死叉（k_prev>=d_prev）
        death_cross = stoch_k < stoch_d and k_prev >= d_prev
        
        if pdi > ndi and close > bbi and golden_cross and stoch_k < STOCH_K_OVERBOUGHT and close >= bb_mid:
            pending = 'LONG'
        elif ndi > pdi and close < bbi and death_cross and stoch_k > STOCH_K_OVERSOLD and close <= bb_mid:
            pending = 'SHORT'
    
    return trades

def summary(name, trades):
    if not trades:
        print(f'{name}: 0 trades')
        return
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total = len(trades)
    winrate = len(wins) / total * 100
    pnl = sum(t['pnl'] for t in trades)
    max_win = max(t['pnl'] for t in trades)
    max_loss = min(t['pnl'] for t in trades)
    avg_pnl = pnl / total
    print(f'{name}: {total} trades | WinRate={winrate:.1f}% | PnL={pnl:+.2f} | Avg={avg_pnl:+.2f} | MaxWin={max_win:.2f} | MaxLoss={max_loss:.2f}')
    
    # 按出场原因统计
    reasons = defaultdict(lambda: {'count': 0, 'pnl': 0.0})
    for t in trades:
        reasons[t['reason']]['count'] += 1
        reasons[t['reason']]['pnl'] += t['pnl']
    print(f'  出场分布:')
    for reason, stats in sorted(reasons.items(), key=lambda x: -x[1]['count']):
        print(f'    {reason}: {stats["count"]} 次, PnL={stats["pnl"]:+.2f}')

def main():
    print('=== FollowAve v1.0 vs v1.2 对比回测 ===\n')
    
    for tf in ['M15', 'M30']:
        print(f'\n{"="*50}')
        print(f'周期: {tf}')
        print('='*50)
        
        candles = load_candles(tf)
        candles = calc_indicators(candles)
        print(f'数据: {len(candles)} 根 K 线')
        
        trades_v1 = run_v1(candles)
        trades_v12 = run_v12(candles)
        
        summary('v1.0 (旧)', trades_v1)
        summary('v1.2 (新)', trades_v12)
        
        # 对比
        print(f'\n对比:')
        print(f'  交易次数: {len(trades_v1)} -> {len(trades_v12)} ({len(trades_v12)-len(trades_v1):+d})')
        pnl_v1 = sum(t['pnl'] for t in trades_v1)
        pnl_v12 = sum(t['pnl'] for t in trades_v12)
        print(f'  总 PnL:  {pnl_v1:+.2f} -> {pnl_v12:+.2f} ({pnl_v12-pnl_v1:+.2f})')

if __name__ == '__main__':
    main()
