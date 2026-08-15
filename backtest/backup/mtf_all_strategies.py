"""
全策略 × 多周期 (M30/H1/H4) 对比回测
====================================
测试所有 10 个策略在三个时间周期上的表现:
  - 归档旧策略: 双均线, ATR突破, 双确认, RSI+BB, Stoch+BB, RSI+BB_M30, RSI掉头
  - 当前实盘: M30 RSI+BB
  - V6 变体: V6v1(原版), V6v6(去BB/KC)

出场统一使用 ATR 动态追踪(4x) + 硬止损(2.5x)，公平比较
"""
import sys, os, math, json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.database import init_db, get_conn
from core.bridge import Candle

init_db()
conn = get_conn()

# ── 加载三周期数据 ──
DATA = {}
for tf in ['M30', 'H1', 'H4']:
    rows = conn.execute(
        "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe=? ORDER BY timestamp",
        (tf,)
    ).fetchall()
    CL = [float(r[1]) for r in rows]
    CND = [Candle(time=str(r[0]),open=r[1],high=r[2],low=r[3],close=r[4],volume=r[5]) for r in rows]
    DATA[tf] = {
        'cl': [float(r[4]) for r in rows],
        'hi': [float(r[2]) for r in rows],
        'lo': [float(r[3]) for r in rows],
        'op': [float(r[1]) for r in rows],
        'ts': [int(r[0]) for r in rows],
        'candles': CND,
        'n': len(rows),
    }
    d0 = datetime.fromtimestamp(DATA[tf]['ts'][0])
    d1 = datetime.fromtimestamp(DATA[tf]['ts'][-1])
    print(f"{tf}: {DATA[tf]['n']} candles ({d0.strftime('%Y-%m-%d')} ~ {d1.strftime('%Y-%m-%d')})")
conn.close()

COMMISSION = 0.50
LOT = 0.01
CONTRACT = 100

# ── 公共指标函数 ──
def calc_sma(cl, p):
    if len(cl) < p: return None
    return sum(cl[-p:]) / p

def calc_ema(cl, p):
    if len(cl) < p: return None
    k = 2.0 / (p + 1)
    e = cl[0]
    for v in cl[1:]: e = (v - e) * k + e
    return e

def calc_ema_series(cl, p):
    if len(cl) < 3: return None
    k = 2.0 / (p + 1)
    e = cl[0]; r = [e]
    for v in cl[1:]: e = (v - e) * k + e; r.append(e)
    return r

def calc_rsi(cl, p=14):
    if len(cl) < p + 1: return None
    g = l = 0
    for j in range(1, p+1):
        d = cl[j] - cl[j-1]
        g += max(d, 0); l += max(-d, 0)
    ag = g / p; al = l / p
    for j in range(p+1, len(cl)):
        d = cl[j] - cl[j-1]
        ag = (ag * (p-1) + max(d, 0)) / p
        al = (al * (p-1) + max(-d, 0)) / p
    return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

def calc_atr(candles, p=14):
    """return list of atr values aligned to candles (index 0 = p-1)"""
    if len(candles) < p + 2: return None
    tr = []
    for i in range(1, len(candles)):
        h = candles[i].high; l = candles[i].low; pc = candles[i-1].close
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(tr) < p: return None
    atr = [sum(tr[:p]) / p]
    for i in range(p, len(tr)):
        atr.append((atr[-1] * (p-1) + tr[i]) / p)
    return atr  # atr[j] corresponds to candle[p + j - 1]

def get_atr(atr_list, idx, warmup):
    """Get ATR value for candle idx (with warmup offset)"""
    if idx < warmup or atr_list is None: return None
    atr_idx = idx - warmup
    if atr_idx >= len(atr_list): return None
    return atr_list[atr_idx]

def calc_bb(cl, p=20, std_mul=2.0):
    if len(cl) < p: return None
    r = cl[-p:]; s = sum(r) / p
    v = sum((c - s) ** 2 for c in r) / p
    d = math.sqrt(v)
    return {'lower': s - std_mul * d, 'upper': s + std_mul * d, 'sma': s}

def calc_stoch(candles, kp=9, slowing=3, dp=3):
    n = len(candles)
    if n < kp + slowing + dp + 1: return None
    rk = []
    for j in range(kp-1, n):
        w = candles[j-kp+1:j+1]
        hi = max(x.high for x in w); lo = min(x.low for x in w); cl = w[-1].close
        rk.append(50.0 if hi == lo else (cl - lo) / (hi - lo) * 100)
    if len(rk) < slowing + dp + 1: return None
    sk = [sum(rk[j-slowing+1:j+1]) / slowing for j in range(slowing-1, len(rk))]
    if len(sk) < dp + 1: return None
    return {'curr_k': sk[-1], 'prev_k': sk[-2], 'curr_d': sum(sk[-dp:]) / dp}

def calc_macd(cl):
    if len(cl) < 35: return None
    k12, k26, k9 = 2.0/13, 2.0/27, 2.0/10
    e12 = e26 = cl[0]; ml = []
    for p in cl:
        e12 = (p - e12) * k12 + e12
        e26 = (p - e26) * k26 + e26
        ml.append(e12 - e26)
    sig = [ml[0]]
    for v in ml[1:]: sig.append((v - sig[-1]) * k9 + sig[-1])
    hv = [ml[i] - sig[i] for i in range(len(ml))]
    return {'hist_values': hv, 'curr_hist': hv[-1] if hv else 0}

def check_bottom_div(hist, lb=10):
    n = len(hist); s = n - lb * 2
    if s < 1: return False
    lows = []
    for j in range(s+1, n-1):
        if hist[j] < hist[j-1] and hist[j] < hist[j+1]:
            lows.append((j, hist[j]))
    return len(lows) >= 2 and lows[-1][1] > lows[-2][1]

def check_top_div(hist, lb=10):
    n = len(hist); s = n - lb * 2
    if s < 1: return False
    highs = []
    for j in range(s+1, n-1):
        if hist[j] > hist[j-1] and hist[j] > hist[j+1]:
            highs.append((j, hist[j]))
    return len(highs) >= 2 and highs[-1][1] < highs[-2][1]

def find_nearest_idx(ts, ts_list):
    """binary search: largest index where ts_list[idx] <= ts"""
    lo, hi = 0, len(ts_list) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if ts_list[mid] <= ts: lo = mid + 1
        else: hi = mid - 1
    return hi

def calc_m30_trend_at(m30_cl, m30_idx):
    """M30 trend: EMA20 slope + SMA50"""
    if m30_idx < 0 or len(m30_cl) < 60: return 'NEUTRAL', 0
    sub = m30_cl[:m30_idx+1]
    if len(sub) < 60: return 'NEUTRAL', 0
    ema = calc_ema_series(sub, 20)
    if ema is None or len(ema) < 6: return 'NEUTRAL', 0
    slope = ema[-1] - ema[-6]
    sma50 = calc_sma(sub, 50)
    if sma50 is None: return 'NEUTRAL', 0
    price = sub[-1]
    if slope > 0 and price > sma50: return 'UP', 1
    if slope < 0 and price < sma50: return 'DOWN', -1
    if slope > 0: return 'UP', 0.5
    if slope < 0: return 'DOWN', -0.5
    return 'NEUTRAL', 0

# ── 回测引擎 ──
def run_backtest(data, signal_fn, min_bars=100,
                 trail_atr=4.0, hard_atr=2.5, name="unknown"):
    """通用回测引擎
    Args:
        data: dict with cl, hi, lo, op, ts, candles, n
        signal_fn: function(bar_idx, data, extra) -> 'BUY'/'SELL'/None
        min_bars: minimum bars before first trade
        trail_atr: trailing stop ATR multiplier
        hard_atr: hard stop ATR multiplier
    """
    cl = data['cl']; hi = data['hi']; lo = data['lo']
    candles = data['candles']; n = data['n']
    trades = []; pos = None; ep = 0; ei = 0
    trail_extreme = {}

    for i in range(min_bars, n):
        close = cl[i]; low = lo[i]; high = hi[i]

        # ATR for this bar
        atr_list = data.get('_atr')
        atr_val = None
        if atr_list is not None:
            atr_idx = i - data['_atr_warmup']
            if 0 <= atr_idx < len(atr_list):
                atr_val = atr_list[atr_idx]

        # ── Exit logic ──
        if pos is not None and ei >= 0 and i > ei + 2 and atr_val and atr_val > 0:
            closed = False
            if pos == 'BUY':
                th = trail_extreme.get('h', ep)
                th = max(th, high)
                trail_extreme['h'] = th
                if close < th - atr_val * trail_atr:
                    pnl = (close - ep) * 1.0 - COMMISSION
                    trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                    closed = True
                elif (ep - close) > atr_val * hard_atr:
                    pnl = (close - ep) * 1.0 - COMMISSION
                    trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                    closed = True
            else:  # SELL
                tl = trail_extreme.get('l', ep)
                tl = min(tl, low)
                trail_extreme['l'] = tl
                if close > tl + atr_val * trail_atr:
                    pnl = (ep - close) * 1.0 - COMMISSION
                    trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                    closed = True
                elif (close - ep) > atr_val * hard_atr:
                    pnl = (ep - close) * 1.0 - COMMISSION
                    trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                    closed = True
            if closed:
                pos = None; ei = -1
                continue

        # ── Entry logic ──
        sig = signal_fn(i, data)
        if sig and pos is None:
            pos = sig; ep = close; ei = i
            trail_extreme = {}
        elif sig and sig != pos and pos:
            pnl = (close - ep) * 1.0 - COMMISSION if pos == 'BUY' else (ep - close) * 1.0 - COMMISSION
            trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
            pos = sig; ep = close; ei = i
            trail_extreme = {}

    # Close any open position at end
    if pos:
        pnl = (cl[-1] - ep) * 1.0 - COMMISSION if pos == 'BUY' else (ep - cl[-1]) * 1.0 - COMMISSION
        trades.append({'d': pos, 'ep': ep, 'ex': cl[-1], 'pnl': round(pnl, 2), 'b': n - 1 - ei})

    return trades


def summarize_trades(trades, name):
    """Calculate metrics from trade list"""
    if not trades:
        return {'name': name, 'trades': 0, 'pnl': 0, 'wr': 0, 'avg_w': 0, 'avg_l': 0,
                'best': 0, 'worst': 0, 'buy': 0, 'sell': 0, 'buy_pnl': 0, 'sell_pnl': 0,
                'longest_bar': 0, 'avg_bar': 0}

    tp = sum(t['pnl'] for t in trades)
    w = [t for t in trades if t['pnl'] > 0]
    l = [t for t in trades if t['pnl'] <= 0]
    aw = sum(t['pnl'] for t in w) / len(w) if w else 0
    al = sum(t['pnl'] for t in l) / len(l) if l else 0
    bt = max(t['pnl'] for t in w) if w else 0
    wt = min(t['pnl'] for t in l) if l else 0
    wr = len(w) / len(trades) * 100
    buys = sum(1 for t in trades if t['d'] == 'BUY')
    sells = sum(1 for t in trades if t['d'] == 'SELL')
    buy_pnl = sum(t['pnl'] for t in trades if t['d'] == 'BUY')
    sell_pnl = sum(t['pnl'] for t in trades if t['d'] == 'SELL')
    avg_bar = sum(t['b'] for t in trades) / len(trades)
    longest_bar = max(t['b'] for t in trades)

    return {
        'name': name, 'trades': len(trades), 'pnl': round(tp, 2),
        'wr': round(wr, 1), 'avg_w': round(aw, 2), 'avg_l': round(al, 2),
        'best': round(bt, 2), 'worst': round(wt, 2),
        'buy': buys, 'sell': sells, 'buy_pnl': round(buy_pnl, 2), 'sell_pnl': round(sell_pnl, 2),
        'longest_bar': longest_bar, 'avg_bar': round(avg_bar, 1),
    }


# ====================================================================
# 策略信号函数 (每个接收 bar_idx 和 data, 返回 'BUY'/'SELL'/None)
# ====================================================================

# --- 1. 双均线 ---
def make_signal_double_ma(fast=10, slow=30, **kwargs):
    def fn(i, d):
        if i < slow + 2: return None
        cl = d['cl']
        fast_now = calc_ema(cl[:i+1], fast)
        slow_now = calc_ema(cl[:i+1], slow)
        if fast_now is None or slow_now is None: return None
        fast_prev = calc_ema(cl[:i], fast)
        slow_prev = calc_ema(cl[:i], slow)
        if fast_prev is None or slow_prev is None: return None
        if fast_prev <= slow_prev and fast_now > slow_now: return 'BUY'
        if fast_prev >= slow_prev and fast_now < slow_now: return 'SELL'
        return None
    return fn

# --- 2. ATR突破 ---
def make_signal_atr_breakout(period=20, **kwargs):
    def fn(i, d):
        if i < period + 5: return None
        hi = d['hi']; lo = d['lo']; cl = d['cl']
        lookback_hi = max(hi[i-period:i])
        lookback_lo = min(lo[i-period:i])
        if cl[i] > lookback_hi: return 'BUY'
        if cl[i] < lookback_lo: return 'SELL'
        return None
    return fn

# --- 3. 双确认 (双均线 + ATR) ---
def make_signal_combined(**kwargs):
    ma = make_signal_double_ma(10, 30)
    atr = make_signal_atr_breakout(20)
    def fn(i, d):
        ma_sig = ma(i, d)
        atr_sig = atr(i, d)
        if ma_sig is not None and atr_sig is not None and ma_sig == atr_sig:
            if ma_sig == 'BUY': return 'BUY'
            if ma_sig == 'SELL': return 'SELL'
        return None
    return fn

# --- 4. RSI+BB 均值回归 ---
def make_signal_rsi_bollinger(oversold=30, overbought=70, bb_std=2.0, bb_period=20, **kwargs):
    def fn(i, d):
        if i < bb_period + 15: return None
        cl = d['cl']; hi = d['hi']; lo = d['lo']; candles = d['candles']
        bb = calc_bb(cl[:i+1], bb_period, bb_std)
        if bb is None: return None
        rsi = calc_rsi(cl[:i+1], 14)
        if rsi is None: return None
        close = cl[i]; low = lo[i]; high = hi[i]

        # Score-based entry (similar to current M30 RSI but without H1 trend)
        ls = ss = 0
        if close <= bb['lower']: ls += 1
        if close >= bb['upper']: ss += 1
        if rsi < oversold: ls += 1
        if rsi > overbought: ss += 1

        if ls >= 2: return 'BUY'
        if ss >= 2: return 'SELL'
        return None
    return fn

# --- 5. Stoch+BB ---
def make_signal_stoch_bollinger(oversold=20, overbought=80, **kwargs):
    def fn(i, d):
        if i < 30: return None
        cl = d['cl']; candles = d['candles']
        stoch = calc_stoch(candles[:i+1], 9, 3, 3)
        if stoch is None: return None
        k = stoch['curr_k']; d_val = stoch['curr_d']
        prev_k = stoch['prev_k']
        golden = prev_k <= d_val and k > d_val
        death = prev_k >= d_val and k < d_val

        # MACD filter
        macd = calc_macd(cl[:i+1])
        macd_ok = True
        if macd:
            if golden and k < oversold and macd['curr_hist'] < 0:
                macd_ok = False
            if death and k > overbought and macd['curr_hist'] > 0:
                macd_ok = False

        if golden and k < oversold and macd_ok: return 'BUY'
        if death and k > overbought and macd_ok: return 'SELL'
        return None
    return fn

# --- 6. RSI 掉头 ---
def make_signal_rsi_turn(**kwargs):
    def fn(i, d):
        if i < 20: return None
        cl = d['cl']
        if len(cl[:i+1]) < 18: return None
        rsi_prev = calc_rsi(cl[:i], 14)
        rsi_curr = calc_rsi(cl[:i+1], 14)
        if rsi_prev is None or rsi_curr is None: return None
        if rsi_prev < rsi_curr: return 'BUY'
        if rsi_prev > rsi_curr: return 'SELL'
        return None
    return fn

# --- 7. M30 RSI+BB (当前实盘) ---
def make_signal_m30_rsi_bb(h1_data=None, **kwargs):
    """M30 RSI+BB: 5因子评分 + H1趋势过滤
    h1_data: H1 timeframe data for trend reference
    """
    def fn(i, d):
        if i < 30: return None
        cl = d['cl']; hi = d['hi']; lo = d['lo']; candles = d['candles']
        close = cl[i]; low = lo[i]; high = hi[i]

        bb = calc_bb(cl[:i+1], 20, 2.0)
        if bb is None: return None
        rsi = calc_rsi(cl[:i+1], 14)
        if rsi is None: return None

        # H1 trend (SMA200 of H1)
        h1_trend = 'NEUTRAL'
        if h1_data and h1_data['n'] >= 200:
            h1_cl = h1_data['cl']
            # Find H1 candle <= current timestamp
            ts = d['ts'][i]
            h1_idx = find_nearest_idx(ts, h1_data['ts'])
            if h1_idx >= 199:
                sma200 = sum(h1_cl[h1_idx-199:h1_idx+1]) / 200
                h1_trend = 'UP' if h1_cl[h1_idx] > sma200 else 'DOWN'

        # M30 RSI direction (same TF)
        m30_dir = 'flat'
        if i >= 16:
            rsi_p = calc_rsi(cl[:i], 14)
            rsi_c = calc_rsi(cl[:i+1], 14)
            if rsi_p is not None and rsi_c is not None:
                m30_dir = 'up' if rsi_p < rsi_c else 'down' if rsi_p > rsi_c else 'flat'

        # Low vol
        vr = sum(cl[max(0, i-9):i+1]) / min(10, i+1)
        atr_list = d.get('_atr')
        atr_val = None
        if atr_list:
            atr_idx = i - d['_atr_warmup']
            if 0 <= atr_idx < len(atr_list):
                atr_val = atr_list[atr_idx]
        low_vol = False
        if atr_val and vr > 0:
            low_vol = atr_val < vr * 0.025

        ls = ss = 0
        if h1_trend == 'UP': ls += 1
        elif h1_trend == 'DOWN': ss += 1
        if close <= bb['lower']: ls += 1
        if close >= bb['upper']: ss += 1
        if rsi < 30: ls += 1
        if rsi > 65: ss += 1
        if m30_dir == 'up': ls += 1
        if m30_dir == 'down': ss += 1
        if low_vol: ls += 1; ss += 1

        if ls >= 3 and h1_trend == 'UP': return 'BUY'
        if ss >= 3 and h1_trend == 'DOWN': return 'SELL'
        return None
    return fn

# --- 8. V6v1: 原版多因子评分 ---
def make_signal_v6v1(lower_tf_data=None, **kwargs):
    """V6: 8因子评分 >= 3
    lower_tf_data: 次级周期数据用于方向判断
    """
    def fn(i, d):
        if i < 250: return None
        cl = d['cl']; hi = d['hi']; lo = d['lo']; candles = d['candles']
        close = cl[i]; low = lo[i]; high = hi[i]
        sc = cl[:i+1]; sca = candles[:i+1]

        sma200 = calc_sma(sc, 200)
        if sma200 is None: return None
        stoch = calc_stoch(sca)
        if stoch is None: return None
        rsi = calc_rsi(sc)
        if rsi is None: return None

        # BB
        bb = calc_bb(sc, 20, 2.5)
        if bb is None: return None

        # ATR for BB
        atr_list = d.get('_atr')
        atr_val = None
        if atr_list:
            atr_idx = i - d['_atr_warmup']
            if 0 <= atr_idx < len(atr_list):
                atr_val = atr_list[atr_idx]

        # Keltner (use approximate with SMA20)
        ema20 = calc_ema(sc, 20)
        if ema20 is None or atr_val is None: return None
        kc_upper = ema20 + atr_val * 2.5
        kc_lower = ema20 - atr_val * 2.5

        macd = calc_macd(sc)
        bdiv = check_bottom_div(macd['hist_values']) if macd else False
        tdiv = check_top_div(macd['hist_values']) if macd else False

        vr = sum(cl[max(0, i-9):i+1]) / min(10, i+1)
        lv = atr_val is not None and atr_val < vr * 0.02

        # Lower TF direction
        lower_dir = 0
        if lower_tf_data:
            ts = d['ts'][i]
            lt_idx = find_nearest_idx(ts, lower_tf_data['ts'])
            _, lower_dir = calc_m30_trend_at(lower_tf_data['cl'], lt_idx)

        ls = ss = 0
        if close > sma200: ls += 1
        if stoch['curr_k'] < 30 or stoch['prev_k'] < 30: ls += 1
        if low <= bb['lower']: ls += 1
        if low <= kc_lower: ls += 1
        if bdiv: ls += 2
        if rsi < 30: ls += 1
        if lv: ls += 1
        if lower_dir > 0: ls += 1
        elif lower_dir < 0: ls -= 1

        if close <= sma200:
            if stoch['curr_k'] > 65: ss += 1
            if high >= kc_upper: ss += 1
            if tdiv: ss += 2
            if rsi > 70: ss += 1
            if lower_dir < 0: ss += 1
            elif lower_dir > 0: ss -= 1

        if ls >= 3: return 'BUY'
        if ss >= 3: return 'SELL'
        return None
    return fn

# --- 9. V6v6: 去BB/KC ---
def make_signal_v6v6(lower_tf_data=None, **kwargs):
    """V6v6: removed BB/KC touch signals"""
    def fn(i, d):
        if i < 250: return None
        cl = d['cl']; hi = d['hi']; lo = d['lo']; candles = d['candles']
        close = cl[i]; low = lo[i]; high = hi[i]
        sc = cl[:i+1]; sca = candles[:i+1]

        sma200 = calc_sma(sc, 200)
        if sma200 is None: return None
        stoch = calc_stoch(sca)
        if stoch is None: return None
        rsi = calc_rsi(sc)
        if rsi is None: return None

        atr_list = d.get('_atr')
        atr_val = None
        if atr_list:
            atr_idx = i - d['_atr_warmup']
            if 0 <= atr_idx < len(atr_list):
                atr_val = atr_list[atr_idx]

        macd = calc_macd(sc)
        bdiv = check_bottom_div(macd['hist_values']) if macd else False
        tdiv = check_top_div(macd['hist_values']) if macd else False

        vr = sum(cl[max(0, i-9):i+1]) / min(10, i+1)
        lv = atr_val is not None and atr_val < vr * 0.02

        lower_dir = 0
        if lower_tf_data:
            ts = d['ts'][i]
            lt_idx = find_nearest_idx(ts, lower_tf_data['ts'])
            _, lower_dir = calc_m30_trend_at(lower_tf_data['cl'], lt_idx)

        ls = ss = 0
        if close > sma200: ls += 1
        if stoch['curr_k'] < 30 or stoch['prev_k'] < 30: ls += 1
        if bdiv: ls += 2
        if rsi < 30: ls += 1
        if lv: ls += 1
        if lower_dir > 0: ls += 1
        elif lower_dir < 0: ls -= 1

        if close <= sma200:
            if stoch['curr_k'] > 65: ss += 1
            if tdiv: ss += 2
            if rsi > 70: ss += 1
            if lower_dir < 0: ss += 1
            elif lower_dir > 0: ss -= 1

        if ls >= 3: return 'BUY'
        if ss >= 3: return 'SELL'
        return None
    return fn

# --- 10. RSI+BB M30 变体 (用M15方向) ---
def make_signal_rsi_bollinger_m30(oversold=30, overbought=70, **kwargs):
    """Same as rsi_bollinger but different oversold/overbought thresholds"""
    def fn(i, d):
        if i < 30: return None
        cl = d['cl']; hi = d['hi']; lo = d['lo']
        bb = calc_bb(cl[:i+1], 20, 2.0)
        if bb is None: return None
        rsi = calc_rsi(cl[:i+1], 14)
        if rsi is None: return None
        close = cl[i]

        # Dynamic thresholds based on EMA20 trend
        ema20 = calc_ema(cl[:i+1], 20)
        ema20_2 = calc_ema(cl[:i], 20)
        ema_trend = None
        if ema20 is not None and ema20_2 is not None:
            ema_trend = 'up' if ema20 > ema20_2 else 'down' if ema20 < ema20_2 else 'flat'

        actual_os = 35 if ema_trend == 'up' else oversold
        actual_ob = 65 if ema_trend == 'down' else overbought

        ls = ss = 0
        if close <= bb['lower']: ls += 1
        if close >= bb['upper']: ss += 1
        if rsi < actual_os: ls += 1
        if rsi > actual_ob: ss += 1

        if ls >= 2: return 'BUY'
        if ss >= 2: return 'SELL'
        return None
    return fn


# ====================================================================
# 配置: 策略 × 时间周期
# ====================================================================
STRATEGIES = [
    # (name, signal_maker, min_bars, trail_atr, hard_atr, needs_lower_tf, needs_h1)
    ('双均线', make_signal_double_ma, 60, 4.0, 2.5, False, False),
    ('ATR突破', make_signal_atr_breakout, 60, 4.0, 2.5, False, False),
    ('双确认', make_signal_combined, 60, 4.0, 2.5, False, False),
    ('RSI+BB', make_signal_rsi_bollinger, 60, 4.0, 2.5, False, False),
    ('Stoch+BB', make_signal_stoch_bollinger, 60, 4.0, 2.5, False, False),
    ('RSI掉头', make_signal_rsi_turn, 30, 4.0, 2.5, False, False),
    ('RSI+BB_M30', make_signal_rsi_bollinger_m30, 60, 4.0, 2.5, False, False),
    ('M30_RSI+BB', make_signal_m30_rsi_bb, 100, 4.0, 3.0, False, True),
    ('V6v1', make_signal_v6v1, 260, 4.0, 2.0, True, False),
    ('V6v6', make_signal_v6v6, 260, 4.0, 2.0, True, False),
]

TIMEFRAMES = ['M30', 'H1', 'H4']

LOWER_TF_MAP = {
    'M30': 'M15' if 'M15' in DATA else None,
    'H1': 'M30',
    'H4': 'H1',
}

# Precompute ATR for each timeframe
for tf in TIMEFRAMES:
    d = DATA[tf]
    atr_list = calc_atr(d['candles'], 14)
    d['_atr'] = atr_list
    d['_atr_warmup'] = 15  # ATR starts at candle 15


# ====================================================================
# 运行
# ====================================================================
def run():
    print("=" * 90)
    print("  全策略 × 多周期回测")
    print("=" * 90)

    all_results = {}  # {(strategy, timeframe): metrics}

    for tf in TIMEFRAMES:
        data = DATA[tf]
        cl = data['cl']
        d0 = datetime.fromtimestamp(data['ts'][0])
        d1 = datetime.fromtimestamp(data['ts'][-1])
        print(f"\n{'='*90}")
        print(f"  [{tf}] {data['n']} candles ({d0.strftime('%Y-%m-%d')} ~ {d1.strftime('%Y-%m-%d')})")
        print(f"{'='*90}")

        for sname, sig_maker, min_bars, t_atr, h_atr, needs_lower, needs_h1 in STRATEGIES:
            # Determine lower TF data
            lower_data = None
            if needs_lower or sname == 'M30_RSI+BB':
                if tf == 'M30':
                    # M30 RSI always uses H1 for trend. V6 on M30 uses M15 if available
                    if sname == 'M30_RSI+BB':
                        lower_data = DATA.get('H1')
                    else:
                        lower_data = DATA.get('M15') or DATA.get('M5')
                elif tf == 'H1':
                    lower_data = DATA.get('M30')
                elif tf == 'H4':
                    lower_data = DATA.get('H1')

            # Build signal function with appropriate data references
            kwargs = {}
            if needs_h1:
                kwargs['h1_data'] = DATA.get('H1')
            elif needs_lower:
                kwargs['lower_tf_data'] = lower_data
            sig_fn = sig_maker(**kwargs)

            # Calculate effective min bars
            actual_min = min(min_bars, data['n'] // 3)

            trades = run_backtest(data, sig_fn, min_bars=actual_min,
                                  trail_atr=t_atr, hard_atr=h_atr, name=sname)
            metrics = summarize_trades(trades, f"{sname}_{tf}")
            all_results[(sname, tf)] = metrics

            # Print
            pnl_s = f"${metrics['pnl']:+.2f}"
            wr_s = f"{metrics['wr']:.1f}%"
            print(f"  {sname:<14} 交易:{metrics['trades']:>4}  盈亏:{pnl_s:>9}  胜率:{wr_s:>6}  "
                  f"B/S:{metrics['buy']}/{metrics['sell']}  "
                  f"均盈:{metrics['avg_w']:>7.2f}  均亏:{metrics['avg_l']:>7.2f}")

        print()

    # ====================================================================
    # 汇总对比表
    # ====================================================================
    print("\n" + "=" * 90)
    print("  全策略 × 多周期 汇总对比")
    print("=" * 90)

    # Header
    hdr = f"{'策略':<14}"
    for tf in TIMEFRAMES:
        hdr += f" | {tf+'交易':>5} {tf+'盈亏':>10} {tf+'胜率':>6}"
    print(hdr)
    print("-" * 90)

    for sname, _, _, _, _, _, _ in STRATEGIES:
        row = f"{sname:<14}"
        for tf in TIMEFRAMES:
            r = all_results.get((sname, tf))
            if r and r['trades'] > 0:
                row += f" | {r['trades']:>5} ${r['pnl']:>+8.2f} {r['wr']:>5.1f}%"
            else:
                row += f" | {'-':>5} {'-':>10} {'-':>6}"
        print(row)

    # Best per timeframe
    print(f"\n  各周期最佳策略:")
    for tf in TIMEFRAMES:
        best = None
        for (sn, tff), r in all_results.items():
            if tff == tf and r['trades'] >= 5:
                if best is None or r['pnl'] > best['pnl']:
                    best = {**r, 'name': sn}
        if best:
            print(f"    {tf}: {best['name']}  ${best['pnl']:+.2f}  ({best['trades']} trades, {best['wr']}% WR)")
        else:
            print(f"    {tf}: 无有效策略")

    # Direction breakdown per strategy (across all TFs)
    print(f"\n  方向分析 (BUY/SELL 盈亏):")
    for sname, _, _, _, _, _, _ in STRATEGIES:
        parts = []
        for tf in TIMEFRAMES:
            r = all_results.get((sname, tf))
            if r and r['trades'] > 0:
                ratio = r['buy'] / max(r['sell'], 1)
                parts.append(f"{tf}: B{r['buy']}S{r['sell']}({ratio:.1f}:1) B${r['buy_pnl']:+.1f}S${r['sell_pnl']:+.1f}")
        if parts:
            print(f"  {sname:<14}: {' | '.join(parts)}")

    # ====================================================================
    # JSON输出
    # ====================================================================
    output = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'data_ranges': {
            tf: {
                'candles': DATA[tf]['n'],
                'from': datetime.fromtimestamp(DATA[tf]['ts'][0]).strftime('%Y-%m-%d'),
                'to': datetime.fromtimestamp(DATA[tf]['ts'][-1]).strftime('%Y-%m-%d'),
            }
            for tf in TIMEFRAMES
        },
        'results_by_strategy': {},
        'results_by_timeframe': {},
    }

    for (sn, tf), r in all_results.items():
        if sn not in output['results_by_strategy']:
            output['results_by_strategy'][sn] = {}
        output['results_by_strategy'][sn][tf] = {
            k: v for k, v in r.items() if k != 'name'
        }
        if tf not in output['results_by_timeframe']:
            output['results_by_timeframe'][tf] = {}
        output['results_by_timeframe'][tf][sn] = {
            k: v for k, v in r.items() if k != 'name'
        }

    with open('backtest/mtf_all_strategies.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存到 backtest/mtf_all_strategies.json")


if __name__ == '__main__':
    run()
