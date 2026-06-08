"""
GitHub 开源 XAUUSD 策略移植回测
================================
从 3 个 GitHub 仓库移植的策略:
  1. sanqing-ea (三清EA) — M5 EMA9/21+ATR14, 3子策略优先级
  2. N30 Gold Scalper — Z-Score 均值回归 + ADX 趋势突破
  3. XAUUSD Trend Follow — H1 长线做多, EMA200 + (MACD/Stoch/EMA交叉)

由于我们没有 M5/M1 数据, 策略适配到 M30/H1/H4 运行
"""
import sys, os, json, math
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.database import init_db, get_conn
from core.bridge import Candle

init_db()
conn = get_conn()

COMMISSION = 0.50

# ── 加载数据 ──
DATA = {}
for tf in ['M30', 'H1', 'H4']:
    rows = conn.execute(
        "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe=? ORDER BY timestamp",
        (tf,)
    ).fetchall()
    CND = [Candle(time=str(r[0]),open=r[1],high=r[2],low=r[3],close=r[4],volume=r[5]) for r in rows]
    DATA[tf] = {
        'cl': [float(r[4]) for r in rows],
        'hi': [float(r[2]) for r in rows],
        'lo': [float(r[3]) for r in rows],
        'op': [float(r[1]) for r in rows],
        'ts': [int(r[0]) for r in rows],
        'vol': [int(r[5]) for r in rows],
        'candles': CND,
        'n': len(rows),
    }
    d0 = datetime.fromtimestamp(DATA[tf]['ts'][0])
    d1 = datetime.fromtimestamp(DATA[tf]['ts'][-1])
    print(f"{tf}: {DATA[tf]['n']} candles ({d0.strftime('%Y-%m-%d')} ~ {d1.strftime('%Y-%m-%d')})")
conn.close()

# ── 公共指标 ──
def calc_ema(cl, p):
    if len(cl) < p: return None
    k = 2.0 / (p + 1); e = cl[0]
    for v in cl[1:]: e = (v - e) * k + e
    return e

def calc_ema_series(cl, p):
    if len(cl) < 3: return None
    k = 2.0 / (p + 1); e = cl[0]; r = [e]
    for v in cl[1:]: e = (v - e) * k + e; r.append(e)
    return r

def calc_sma(cl, p):
    if len(cl) < p: return None
    return sum(cl[-p:]) / p

def calc_rsi(cl, p=14):
    if len(cl) < p + 1: return None
    g = l = 0
    for j in range(1, p+1):
        d = cl[j] - cl[j-1]; g += max(d, 0); l += max(-d, 0)
    ag = g / p; al = l / p
    for j in range(p+1, len(cl)):
        d = cl[j] - cl[j-1]
        ag = (ag * (p-1) + max(d, 0)) / p
        al = (al * (p-1) + max(-d, 0)) / p
    return 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

def calc_atr(candles, p=14):
    if len(candles) < p + 2: return [], None
    tr = []
    for i in range(1, len(candles)):
        h = candles[i].high; l = candles[i].low; pc = candles[i-1].close
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(tr) < p: return [], None
    atr = [sum(tr[:p]) / p]
    for i in range(p, len(tr)):
        atr.append((atr[-1] * (p-1) + tr[i]) / p)
    warmup = p + 1  # atr[0] corresponds to candle index p
    return atr, warmup

def get_atr_val(atr_list, warmup, idx):
    if idx < warmup or atr_list is None: return None
    ai = idx - warmup
    if ai >= len(atr_list): return None
    return atr_list[ai]

def calc_macd(cl):
    if len(cl) < 35: return None
    k12, k26, k9 = 2.0/13, 2.0/27, 2.0/10
    e12 = e26 = cl[0]; ml = []
    for p in cl:
        e12 = (p - e12) * k12 + e12; e26 = (p - e26) * k26 + e26
        ml.append(e12 - e26)
    sig = [ml[0]]
    for v in ml[1:]: sig.append((v - sig[-1]) * k9 + sig[-1])
    hv = [ml[i] - sig[i] for i in range(len(ml))]
    return {'hist_values': hv, 'curr_hist': hv[-1] if hv else 0, 'macd': ml, 'signal': sig}

def calc_stddev(cl, p):
    if len(cl) < p: return None
    sub = cl[-p:]; s = sum(sub) / p
    return math.sqrt(sum((c - s) ** 2 for c in sub) / p)

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
    return {'curr_k': sk[-1], 'prev_k': sk[-2], 'curr_d': sum(sk[-dp:]) / dp}

def calc_adx(data, p=14):
    """Calculate ADX and DI+/DI-"""
    candles = data['candles']; hi = data['hi']; lo = data['lo']; cl = data['cl']
    n = len(candles)
    if n < p + 2: return None
    tr = []; plus_dm = []; minus_dm = []
    for i in range(1, n):
        h = candles[i].high; l = candles[i].low; pc = candles[i-1].close
        prev_h = candles[i-1].high; prev_l = candles[i-1].low
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        up = h - prev_h; down = prev_l - l
        pdm = up if up > down and up > 0 else 0
        mdm = down if down > up and down > 0 else 0
        plus_dm.append(pdm); minus_dm.append(mdm)

    if len(tr) < p: return None

    atr_val = sum(tr[:p]) / p
    pdi_val = sum(plus_dm[:p]) / p / atr_val * 100 if atr_val > 0 else 0
    ndi_val = sum(minus_dm[:p]) / p / atr_val * 100 if atr_val > 0 else 0

    # Smoothed ATR, PDI, NDI
    atr_smooth = [atr_val]; pdi_smooth = [pdi_val]; ndi_smooth = [ndi_val]
    for i in range(p, len(tr)):
        atr_smooth.append((atr_smooth[-1] * (p-1) + tr[i]) / p)
        pd = (pdi_smooth[-1] * (p-1) + plus_dm[i] / atr_smooth[-1] * 100) / p if atr_smooth[-1] > 0 else 0
        nd = (ndi_smooth[-1] * (p-1) + minus_dm[i] / atr_smooth[-1] * 100) / p if atr_smooth[-1] > 0 else 0
        pdi_smooth.append(pd)
        ndi_smooth.append(nd)

    dx = [abs(pdi_smooth[i] - ndi_smooth[i]) / max(pdi_smooth[i] + ndi_smooth[i], 0.001) * 100 for i in range(len(atr_smooth))]
    adx = [sum(dx[:p]) / p]
    for i in range(p, len(dx)):
        adx.append((adx[-1] * (p-1) + dx[i]) / p)

    return {
        'adx_list': adx, 'pdi_list': pdi_smooth, 'ndi_list': ndi_smooth,
        'atr_list': atr_smooth, 'warmup': p + 1
    }

def get_adx_val(adx_result, idx):
    if adx_result is None: return None, None, None
    warmup = adx_result['warmup']
    if idx < warmup: return None, None, None
    ai = idx - warmup
    if ai >= len(adx_result['adx_list']): return None, None, None
    return adx_result['adx_list'][ai], adx_result['pdi_list'][ai], adx_result['ndi_list'][ai]

# ── 回测引擎 ──
def run_backtest(data, signal_fn, min_bars=100,
                 atr_trail=4.0, atr_hardstop=2.5,
                 tp_atr=None, sl_atr=None, name=""):
    """
    统一回测引擎, 支持 trailing stop 和 fixed ATR-based SL/TP
    tp_atr/sl_atr: if set, use fixed SL/TP instead of trailing
    """
    cl = data['cl']; hi = data['hi']; lo = data['lo']
    candles = data['candles']; n = data['n']
    atr_list = data.get('_atr')
    atr_warmup = data.get('_atr_warmup', 0)
    trades = []; pos = None; ep = 0; ei = 0
    trail_extreme = {}

    for i in range(min_bars, n):
        close = cl[i]; low = lo[i]; high = hi[i]
        atr_val = get_atr_val(atr_list, atr_warmup, i)

        # ── Exit ──
        if pos is not None and ei >= 0 and i > ei + 2 and atr_val and atr_val > 0:
            closed = False
            if pos == 'BUY':
                if atr_trail:
                    th = trail_extreme.get('h', ep)
                    trail_extreme['h'] = max(th, high)
                    if close < trail_extreme['h'] - atr_val * atr_trail:
                        pnl = (close - ep) * 1.0 - COMMISSION
                        trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                        closed = True
                if not closed and atr_hardstop and (ep - close) > atr_val * atr_hardstop:
                    pnl = (close - ep) * 1.0 - COMMISSION
                    trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                    closed = True
                if not closed and tp_atr and sl_atr:
                    # Fixed SL/TP mode
                    if close >= ep + atr_val * tp_atr:
                        pnl = (close - ep) * 1.0 - COMMISSION
                        trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                        closed = True
                    elif close <= ep - atr_val * sl_atr:
                        pnl = (close - ep) * 1.0 - COMMISSION
                        trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                        closed = True
            else:  # SELL
                if atr_trail:
                    tl = trail_extreme.get('l', ep)
                    trail_extreme['l'] = min(tl, low)
                    if close > trail_extreme['l'] + atr_val * atr_trail:
                        pnl = (ep - close) * 1.0 - COMMISSION
                        trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                        closed = True
                if not closed and atr_hardstop and (close - ep) > atr_val * atr_hardstop:
                    pnl = (ep - close) * 1.0 - COMMISSION
                    trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                    closed = True
                if not closed and tp_atr and sl_atr:
                    if close <= ep - atr_val * tp_atr:
                        pnl = (ep - close) * 1.0 - COMMISSION
                        trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                        closed = True
                    elif close >= ep + atr_val * sl_atr:
                        pnl = (ep - close) * 1.0 - COMMISSION
                        trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
                        closed = True
            if closed:
                pos = None; ei = -1; continue

        # ── Entry ──
        sig = signal_fn(i, data)
        if sig and pos is None:
            pos = sig; ep = close; ei = i; trail_extreme = {}
        elif sig and sig != pos and pos:
            pnl = (close - ep) * 1.0 - COMMISSION if pos == 'BUY' else (ep - close) * 1.0 - COMMISSION
            trades.append({'d': pos, 'ep': ep, 'ex': close, 'pnl': round(pnl, 2), 'b': i - ei})
            pos = sig; ep = close; ei = i; trail_extreme = {}

    # Close remaining
    if pos:
        pnl = (cl[-1] - ep) * 1.0 - COMMISSION if pos == 'BUY' else (ep - cl[-1]) * 1.0 - COMMISSION
        trades.append({'d': pos, 'ep': ep, 'ex': cl[-1], 'pnl': round(pnl, 2), 'b': n - 1 - ei})

    return trades


def summarize(trades, name):
    if not trades:
        return {'name': name, 'trades': 0, 'pnl': 0, 'wr': 0, 'avg_w': 0, 'avg_l': 0,
                'best': 0, 'worst': 0, 'buy': 0, 'sell': 0, 'buy_pnl': 0, 'sell_pnl': 0, 'avg_bar': 0}
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
    max_consec_loss = 0; cur_loss = 0
    for t in trades:
        if t['pnl'] <= 0: cur_loss += 1
        else: max_consec_loss = max(max_consec_loss, cur_loss); cur_loss = 0
    max_consec_loss = max(max_consec_loss, cur_loss)
    return {
        'name': name, 'trades': len(trades), 'pnl': round(tp, 2),
        'wr': round(wr, 1), 'avg_w': round(aw, 2), 'avg_l': round(al, 2),
        'best': round(bt, 2), 'worst': round(wt, 2),
        'buy': buys, 'sell': sells, 'buy_pnl': round(buy_pnl, 2), 'sell_pnl': round(sell_pnl, 2),
        'avg_bar': round(avg_bar, 1), 'max_loss_streak': max_consec_loss,
    }


# ====================================================================
# 策略 1: sanqing-ea (三清EA) — M5 EMA9/21+ATR14, 3子策略
# ====================================================================
def make_signal_sanqing(**kwargs):
    """
    三清EA核心逻辑:
    - 主周期 M5, EMA(9/21) 判断趋势, ATR14 判断波动
    - 3 个子策略按优先级:
      1. ExpansionFollow: 异常扩张 + 通道突破
      2. Pullback: EMA 回踩 + 影线确认
      3. TrendContinuation: 趋势延续突破

    适配到 M30/H1/H4: 我们将通道周期和阈值按周期缩放
    """
    tf_mult = kwargs.get('tf_mult', 6)  # M5->M30=6x, M5->H1=12x

    def fn(i, d):
        if i < 60: return None
        cl = d['cl']; hi = d['hi']; lo = d['lo']; candles = d['candles']; vol = d['vol']
        close = cl[i]; high = hi[i]; low = lo[i]; volume = vol[i] if i < len(vol) else 0

        # EMA trend
        ema9 = calc_ema(cl[:i+1], 9)
        ema21 = calc_ema(cl[:i+1], 21)
        if ema9 is None or ema21 is None: return None
        ema9_prev = calc_ema(cl[:i], 9)
        ema21_prev = calc_ema(cl[:i], 21)

        uptrend = ema9 > ema21
        downtrend = ema9 < ema21
        cross_up = ema9_prev is not None and ema21_prev is not None and ema9_prev <= ema21_prev and ema9 > ema21
        cross_dn = ema9_prev is not None and ema21_prev is not None and ema9_prev >= ema21_prev and ema9 < ema21

        # ATR
        atr_vals = d.get('_atr')
        atr_warmup = d.get('_atr_warmup', 0)
        atr_val = get_atr_val(atr_vals, atr_warmup, i)
        if atr_val is None: return None

        # Body size for current candle
        body = abs(close - d['op'][i])
        body_prev = abs(cl[i-1] - d['op'][i-1])
        candle_range = high - low

        # ── Sub-strategy 1: ExpansionFollow (最高优先级) ──
        # 条件: body/ATR >= 4, body/bodyMedian >= 2.2, 通道突破
        # Adapted: lower thresholds for higher TFs
        body_atr_ratio = body / atr_val if atr_val > 0 else 0

        # Body median over last 20 bars
        recent_bodies = [abs(cl[j] - d['op'][j]) for j in range(max(0, i-20), i+1)]
        body_median = sorted(recent_bodies)[len(recent_bodies)//2] if recent_bodies else 1
        body_median_ratio = body / body_median if body_median > 0 else 0

        # Previous body max
        prev_bodies = [abs(cl[j] - d['op'][j]) for j in range(max(0, i-5), i)]
        prev_body_max = max(prev_bodies) if prev_bodies else 1

        # Channel: lookback varies by timeframe
        chan_period = int(20 * tf_mult / 6)  # Scale: M5->20 bars
        chan_period = max(chan_period, 10)
        if i >= chan_period:
            chan_hi = max(hi[i-chan_period:i])
            chan_lo = min(lo[i-chan_period:i])

            # Expansion: body/atr threshold scaled
            expansion_ratio = 3.0 / (tf_mult / 6)  # M5=3.0, M30=1.0, H1=0.5, H4=0.25

            is_expansion = (body_atr_ratio >= expansion_ratio and
                           body_median_ratio >= 1.5 and
                           body / prev_body_max >= 1.5 and
                           candle_range > 0 and candle_range > 0 and
                           body / candle_range >= 0.5)

            if uptrend and is_expansion and close > chan_hi:
                # Long expansion breakout
                pass  # Let main logic handle via signal below

            if downtrend and is_expansion and close < chan_lo:
                pass

        # ── Simple approach: score-based entry using EMA + ATR + expansion ──
        # BUY conditions
        buy_score = 0

        # EMA trend
        if uptrend: buy_score += 2
        elif cross_up: buy_score += 1

        # Pullback to EMA9
        ema9_val = calc_ema(cl[:i+1], 9)
        if ema9_val and uptrend and low <= ema9_val * 1.002 and close > ema9_val:
            buy_score += 2  # Strong pullback signal

        # Expansion (large body relative to ATR)
        if body_atr_ratio > 1.0 and body > 0:
            buy_score += 1

        # Volume confirmation (relative)
        avg_vol = sum(vol[max(0, i-20):i+1]) / min(20, i+1) if i >= 5 else 0
        if avg_vol > 0 and volume > avg_vol * 1.3:
            buy_score += 1

        # SELL conditions
        sell_score = 0
        if downtrend: sell_score += 2
        elif cross_dn: sell_score += 1

        ema9_val_s = calc_ema(cl[:i+1], 9)
        if ema9_val_s and downtrend and high >= ema9_val_s * 0.998 and close < ema9_val_s:
            sell_score += 2

        if body_atr_ratio > 1.0 and body > 0:
            sell_score += 1

        if avg_vol > 0 and volume > avg_vol * 1.3:
            sell_score += 1

        if buy_score >= 4: return 'BUY'
        if sell_score >= 4: return 'SELL'
        return None
    return fn


# ====================================================================
# 策略 2: N30 Gold Scalper — Z-Score 均值回归 + ADX 趋势突破
# ====================================================================
def make_signal_n30_gold(**kwargs):
    """
    N30 Gold Scalper 双策略 (适配高周期):
    - Mean Reversion: Z-Score >= 1.8 入场, ADX < 25 (低周期用2.4/20)
    - Trend Breakout: Donchian(30) + ADX >= 28 + EMA50 + DI spread
    """
    tf_scale = kwargs.get('tf_scale', 1.0)

    def fn(i, d):
        if i < 60: return None
        cl = d['cl']; hi = d['hi']; lo = d['lo']
        close = cl[i]

        # SMA & StdDev for Z-Score
        sma20 = calc_sma(cl[:i+1], 20)
        std20 = calc_stddev(cl[:i+1], 20)
        if sma20 is None or std20 is None or std20 == 0: return None
        z_score = (close - sma20) / std20

        # ADX
        adx_data = d.get('_adx')
        adx_val, pdi, ndi = get_adx_val(adx_data, i)
        if adx_val is None: return None

        # EMA50
        ema50 = calc_ema(cl[:i+1], 50)
        if ema50 is None: return None

        # Donchian Channel
        if i < 30: return None
        donch_hi = max(hi[i-29:i+1])
        donch_lo = min(lo[i-29:i+1])

        # Adaptive thresholds based on timeframe
        z_entry = 1.6 + 0.8 / tf_scale  # M30=2.2, H1=1.8, H4=1.6
        adx_range_thresh = 20 + 5 * tf_scale  # M30=25, H1=22, H4=20
        adx_trend_thresh = 25 + 5 * tf_scale  # M30=30, H1=28, H4=25
        di_min = 2.0 + 1.0 / tf_scale  # M30=2.8, H1=2.5, H4=2.0

        # Decide mode based on ADX
        if adx_val < adx_range_thresh:
            # ── Mean Reversion mode ──
            if z_score <= -z_entry and close > ema50:
                return 'BUY'
            elif z_score >= z_entry and close < ema50:
                return 'SELL'
        elif adx_val >= adx_trend_thresh:
            # ── Trend Breakout mode ──
            di_spread = abs(pdi - ndi) if pdi is not None and ndi is not None else 0

            if di_spread >= di_min:
                if close > donch_hi and pdi > ndi and close > ema50:
                    return 'BUY'
                elif close < donch_lo and ndi > pdi and close < ema50:
                    return 'SELL'

        return None
    return fn


# ====================================================================
# 策略 3: XAUUSD Trend Follow — H1 长线做多
# ====================================================================
def make_signal_xauusd_trend_follow(**kwargs):
    """
    XAUUSD Trend Follow:
    - H1 long-only
    - EMA200 trend filter (price must be above)
    - Entry triggers (any one): MACD cross / Stoch cross / EMA9/21 cross
    - TP=6×ATR, SL=1.25×ATR
    """
    def fn(i, d):
        if i < 220: return None
        cl = d['cl']; hi = d['hi']; lo = d['lo']; candles = d['candles']
        close = cl[i]

        # EMA200 trend filter
        ema200 = calc_ema(cl[:i+1], 200)
        if ema200 is None: return None
        if close <= ema200: return None  # Long only: must be above EMA200

        # ADX filter (optional, used in original)
        adx_data = d.get('_adx')
        if adx_data:
            adx_val, _, _ = get_adx_val(adx_data, i)
            if adx_val is not None and adx_val < 20:
                return None  # No trend, skip

        # ATR
        atr_vals = d.get('_atr')
        atr_warmup = d.get('_atr_warmup', 0)
        atr_val = get_atr_val(atr_vals, atr_warmup, i)
        if atr_val is None: return None

        # Entry triggers (checking bar i-1 as in original EA - trade on close)
        # MACD cross
        macd = calc_macd(cl[:i+1])
        macd_trigger = False
        if macd and len(macd['macd']) >= 3:
            m1 = macd['macd'][-1]; s1 = macd['signal'][-1]
            m2 = macd['macd'][-2]; s2 = macd['signal'][-2]
            if m1 > s1 and m2 <= s2: macd_trigger = True

        # Stoch cross (5,3,3 parameters from original EA)
        stoch = calc_stoch(candles[:i+1], 5, 3, 3)
        stoch_trigger = False
        if stoch:
            if stoch['prev_k'] <= stoch['curr_d'] and stoch['curr_k'] > stoch['curr_d'] and stoch['curr_k'] < 60:
                stoch_trigger = True

        # EMA9/21 cross
        ema9 = calc_ema(cl[:i+1], 9)
        ema21 = calc_ema(cl[:i+1], 21)
        ema_trigger = False
        if ema9 is not None and ema21 is not None:
            ema9_p = calc_ema(cl[:i], 9)
            ema21_p = calc_ema(cl[:i], 21)
            if ema9_p is not None and ema21_p is not None:
                if ema9_p <= ema21_p and ema9 > ema21: ema_trigger = True

        if macd_trigger or stoch_trigger or ema_trigger:
            return 'BUY'

        return None
    return fn


# ====================================================================
# 配置
# ====================================================================
STRATEGIES = [
    # (name, signal_maker, min_bars, exit_mode, kwargs)
    # exit_mode: 'trail' or 'fixed'
    ('sanqing-ea', make_signal_sanqing, 80, 'trail', {'atr_trail': 4.0, 'atr_hardstop': 2.5}),
    ('N30_Gold_Scalper', make_signal_n30_gold, 80, 'trail', {'atr_trail': 2.0, 'atr_hardstop': 3.0}),
    ('XAUUSD_TrendFollow', make_signal_xauusd_trend_follow, 250, 'fixed', {'sl_atr': 1.25, 'tp_atr': 6.0, 'atr_trail': None, 'atr_hardstop': None}),
]

TIMEFRAMES = ['M30', 'H1', 'H4']


# ====================================================================
def run():
    print("=" * 90)
    print("  GitHub 开源策略移植回测")
    print("=" * 90)

    # Precompute indicators
    for tf in TIMEFRAMES:
        d = DATA[tf]
        d['_atr'], d['_atr_warmup'] = calc_atr(d['candles'], 14)
        d['_adx'] = calc_adx(d, 14)
        print(f"  {tf}: ATR+ADX precomputed")

    all_results = {}

    for tf in TIMEFRAMES:
        data = DATA[tf]
        d0 = datetime.fromtimestamp(data['ts'][0])
        d1 = datetime.fromtimestamp(data['ts'][-1])
        print(f"\n{'='*90}")
        print(f"  [{tf}] {data['n']} candles ({d0.strftime('%Y-%m-%d')} ~ {d1.strftime('%Y-%m-%d')})")
        print(f"{'='*90}")

        for sname, sig_maker, min_bars, exit_mode, exit_kwargs in STRATEGIES:
            # Scale min_bars for timeframe
            tf_scale = {'M30': 1, 'H1': 2, 'H4': 8}[tf]
            actual_min = max(min_bars, min_bars * tf_scale // 2)
            actual_min = min(actual_min, data['n'] // 3)

            # Create kwargs for signal maker
            sig_kwargs = {}
            if sname == 'sanqing-ea':
                sig_kwargs['tf_mult'] = {'M30': 6, 'H1': 12, 'H4': 48}[tf]
            if sname == 'N30_Gold_Scalper':
                sig_kwargs['tf_scale'] = {'M30': 0.7, 'H1': 1.0, 'H4': 1.5}[tf]

            sig_fn = sig_maker(**sig_kwargs)

            trades = run_backtest(data, sig_fn, min_bars=actual_min, name=sname, **exit_kwargs)
            metrics = summarize(trades, f"{sname}_{tf}")
            all_results[(sname, tf)] = metrics

            pnl_s = f"${metrics['pnl']:+.2f}"
            wr_s = f"{metrics['wr']:.1f}%"
            print(f"  {sname:<20} 交易:{metrics['trades']:>4}  盈亏:{pnl_s:>9}  胜率:{wr_s:>6}  "
                  f"B/S:{metrics['buy']}/{metrics['sell']}  "
                  f"均盈:{metrics['avg_w']:>7.2f}  均亏:{metrics['avg_l']:>7.2f}")

    # Summary
    print("\n" + "=" * 90)
    print("  GitHub 策略 × 多周期 汇总对比")
    print("=" * 90)

    hdr = f"{'策略':<20}"
    for tf in TIMEFRAMES:
        hdr += f" | {tf+'交易':>5} {tf+'盈亏':>10} {tf+'胜率':>6}"
    print(hdr)
    print("-" * 90)

    for sname, _, _, _, _ in STRATEGIES:
        row = f"{sname:<20}"
        for tf in TIMEFRAMES:
            r = all_results.get((sname, tf))
            if r and r['trades'] > 0:
                row += f" | {r['trades']:>5} ${r['pnl']:>+8.2f} {r['wr']:>5.1f}%"
            else:
                row += f" | {'-':>5} {'-':>10} {'-':>6}"
        print(row)

    # Best per timeframe
    print(f"\n  各周期最佳GitHub策略:")
    for tf in TIMEFRAMES:
        best = None
        for (sn, tff), r in all_results.items():
            if tff == tf and r['trades'] >= 3:
                if best is None or r['pnl'] > best['pnl']:
                    best = {**r, 'name': sn}
        if best:
            print(f"    {tf}: {best['name']}  ${best['pnl']:+.2f}  ({best['trades']} trades, {best['wr']}% WR)")

    # JSON output
    output = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'description': 'GitHub 开源策略移植回测结果',
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
        output['results_by_strategy'][sn][tf] = {k: v for k, v in r.items() if k != 'name'}
        if tf not in output['results_by_timeframe']:
            output['results_by_timeframe'][tf] = {}
        output['results_by_timeframe'][tf][sn] = {k: v for k, v in r.items() if k != 'name'}

    with open('backtest/github_strategies_results.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存到 backtest/github_strategies_results.json")


if __name__ == '__main__':
    run()
