"""
震荡指标组合策略回测 V2 — 加权评分 + 多场景
=============================================
V1教训: 3个振荡器高度相关, ±1评分信号太弱
V2改进:
  A) RSI(±2) + CCI(±1) + MA14(±1), threshold=2/3/4
  B) RSI(±2) + BB(±1) + MA14(±1), threshold=2/3/4
  C) RSI(±2) + CCI(±1) + MA14(±1) + BB(±1), threshold=2/3/4
  D) 出场优化: ATR trail 1.5/2.0, hard 2.0/3.0
  E) RSI周期: 5/8/14对比
"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.database import init_db, get_conn
from core.bridge import Candle

init_db()
conn = get_conn()
TF_QUERIES = {
    'M30': "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp",
    'M15': "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M15' ORDER BY timestamp",
    'H1':  "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='H1' ORDER BY timestamp",
}
ALL_DATA = {}
for tf, sql in TF_QUERIES.items():
    rows = conn.execute(sql).fetchall()
    ALL_DATA[tf] = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in rows]
conn.close()

COMMISSION = 0.5
LOT = 0.01

# ── 指标 ──

def calc_rsi(closes, period=14):
    if len(closes) < period+1: return None
    g,l=[],[]
    for i in range(1,period+1):
        d=closes[i]-closes[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g)/period; al=sum(l)/period
    for i in range(period+1,len(closes)):
        d=closes[i]-closes[i-1]
        ag=(ag*(period-1)+max(d,0))/period; al=(al*(period-1)+max(-d,0))/period
    return 100.0 if al==0 else 100.0-100.0/(1.0+ag/al)

def calc_williams_r(highs, lows, closes, period=14):
    if len(closes) < period: return None
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh == ll: return -50.0
    return -100.0 * (hh - closes[-1]) / (hh - ll)

def calc_cci(highs, lows, closes, period=20):
    if len(closes) < period+1: return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(-period, 0)]
    sma = sum(tp) / period
    md = sum(abs(t - sma) for t in tp) / period
    if md == 0: return 0.0
    return (tp[-1] - sma) / (0.015 * md)

def calc_atr(candles, p=20):
    if len(candles) < p+2: return None
    tr = []
    for i in range(1, len(candles)):
        h=candles[i].high; l=candles[i].low; pc=candles[i-1].close
        tr.append(max(h-l, abs(h-pc), abs(l-pc)))
    if len(tr) < p: return None
    atr = [sum(tr[:p])/p]
    for i in range(p, len(tr)): atr.append((atr[-1]*(p-1)+tr[i])/p)
    return atr[-1]

def calc_bb(closes, p=20, std_mul=2.0):
    if len(closes) < p+1: return None
    r = closes[-p:]; s = sum(r)/p
    v = sum((c-s)**2 for c in r)/p
    return {'sma': s, 'upper': s+std_mul*math.sqrt(v), 'lower': s-std_mul*math.sqrt(v)}

def calc_adx(highs, lows, closes, period=14):
    n = len(highs)
    if n < period+2: return None
    tr_list, pdm, mdm = [], [], []
    for i in range(1, n):
        h,l,pc = highs[i],lows[i],closes[i-1]
        ph,pl = highs[i-1], lows[i-1]
        tr_list.append(max(h-l, abs(h-pc), abs(l-pc)))
        up = h-ph; down = pl-l
        pdm.append(up if(up>down and up>0) else 0)
        mdm.append(down if(down>up and down>0) else 0)
    if len(tr_list) < period: return None
    atr = [sum(tr_list[:period])/period]
    sp = [sum(pdm[:period])/period]
    sm_ = [sum(mdm[:period])/period]
    for j in range(period, len(tr_list)):
        atr.append((atr[-1]*(period-1)+tr_list[j])/period)
        sp.append((sp[-1]*(period-1)+pdm[j])/period)
        sm_.append((sm_[-1]*(period-1)+mdm[j])/period)
    dx_list = []
    for j in range(len(atr)):
        p = 100*sp[j]/atr[j] if atr[j]>0 else 0
        n_ = 100*sm_[j]/atr[j] if atr[j]>0 else 0
        dx = abs(p-n_)/(p+n_)*100 if(p+n_)>0 else 0
        dx_list.append(dx)
    adx_val = sum(dx_list[:period])/period
    for j in range(period, len(dx_list)):
        adx_val = (adx_val*(period-1)+dx_list[j])/period
    pdi_f = 100*sp[-1]/atr[-1] if atr[-1]>0 else 0
    ndi_f = 100*sm_[-1]/atr[-1] if atr[-1]>0 else 0
    return {'adx': adx_val, 'pdi': pdi_f, 'ndi': ndi_f}

# ── 加权评分 ──

def score_v2(rsi, cci, close, ma14, bb,
             rsi_os=30, rsi_ob=70,
             cci_os=-100, cci_ob=100,
             use_ma14=True, use_bb=False, use_adx_mode=False,
             adx_data=None, adx_range=20, adx_trend=25):
    """
    加权评分:
      RSI极限: ±2
      CCI: ±1
      MA14方向: ±1 (可选)
      BB碰轨: ±1 (可选)
    ADX模式门禁(可选)
    """
    ls = 0; ss = 0

    # RSI (±2)
    if rsi is not None:
        if rsi < rsi_os: ls += 2
        elif rsi > rsi_ob: ss += 2

    # CCI (±1)
    if cci is not None:
        if cci < cci_os: ls += 1
        elif cci > cci_ob: ss += 1

    # MA14 (±1)
    if use_ma14 and ma14 is not None:
        if close > ma14: ls += 1
        elif close < ma14: ss += 1

    # BB (±1)
    if use_bb and bb is not None:
        if close <= bb['lower']: ls += 1
        elif close >= bb['upper']: ss += 1

    # ADX模式
    mode = 'neutral'
    if use_adx_mode and adx_data:
        adx_val = adx_data['adx']
        pdi = adx_data['pdi']; ndi = adx_data['ndi']
        if adx_val < adx_range:
            mode = 'range'
        elif adx_val > adx_trend:
            if pdi > ndi: mode = 'trend_bull'
            elif ndi > pdi: mode = 'trend_bear'

    return ls, ss, mode


# ── 回测 ──

def run_bt(candles,
           entry_threshold=2,
           trail_atr=1.0, hard_atr=2.0, min_bars=100,
           rsi_period=14, rsi_os=30, rsi_ob=70,
           cci_period=20, cci_os=-100, cci_ob=100,
           use_ma14=True, use_bb=False,
           use_adx_mode=False, adx_range=20, adx_trend=25,
           require_bb=False):
    """通用回测函数"""
    trades=[]; pos=None; ep=0; ei=0
    trail_h={}; trail_l={}
    n=len(candles)

    for i in range(min_bars, n):
        c=candles[i]; close=c.close; low=c.low; high=c.high
        ts=int(c.time)
        sub=candles[:i+1]
        sc=[x.close for x in sub]
        highs=[x.high for x in sub]
        lows=[x.low for x in sub]

        bb=calc_bb(sc,20,2.0)
        if bb is None: continue
        atr_val=calc_atr(sub,20)
        if atr_val is None: continue
        ma14=sum(sc[-14:])/14 if len(sc)>=14 else None
        if ma14 is None and use_ma14: continue

        adx_data = None
        if use_adx_mode or use_bb:
            adx_data = calc_adx(highs, lows, sc, 14)
            if adx_data is None: continue

        rsi_val=calc_rsi(sc, rsi_period)
        cci_val=calc_cci(highs, lows, sc, cci_period)

        ls, ss, mode = score_v2(
            rsi_val, cci_val, close, ma14, bb,
            rsi_os=rsi_os, rsi_ob=rsi_ob,
            cci_os=cci_os, cci_ob=cci_ob,
            use_ma14=use_ma14, use_bb=use_bb,
            use_adx_mode=use_adx_mode,
            adx_data=adx_data, adx_range=adx_range, adx_trend=adx_trend)
        net = ls - ss

        # ADX门禁
        allow_long = True; allow_short = True
        if use_adx_mode:
            if mode == 'trend_bull': allow_short = False
            elif mode == 'trend_bear': allow_long = False

        # BB硬条件
        bb_long_ok = not require_bb or (close <= bb['lower'])
        bb_short_ok = not require_bb or (close >= bb['upper'])

        # Exit
        tid=f"{ts}_{ep}" if pos else ""
        if pos=='BUY' and ei>=0 and i>ei+4:
            trail_h[tid]=max(trail_h.get(tid,ep),high)
            if close<trail_h[tid]-atr_val*trail_atr:
                pnl=(close-ep)*10*LOT-COMMISSION
                trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'trail'})
                pos=None;ei=-1;continue
        elif pos=='SELL' and ei>=0 and i>ei+4:
            trail_l[tid]=min(trail_l.get(tid,ep),low)
            if close>trail_l[tid]+atr_val*trail_atr:
                pnl=(ep-close)*10*LOT-COMMISSION
                trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'trail'})
                pos=None;ei=-1;continue
        if pos=='BUY' and (ep-close)>atr_val*hard_atr:
            pnl=(close-ep)*10*LOT-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'hard'})
            pos=None;ei=-1;continue
        elif pos=='SELL' and (close-ep)>atr_val*hard_atr:
            pnl=(ep-close)*10*LOT-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'hard'})
            pos=None;ei=-1;continue

        # Entry
        sig=None
        if net >= entry_threshold and allow_long and bb_long_ok: sig='BUY'
        elif net <= -entry_threshold and allow_short and bb_short_ok: sig='SELL'

        if sig and pos is None:
            pos=sig; ep=close; ei=i
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-close)*10*LOT-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'flip'})
            pos=sig; ep=close; ei=i

    if pos:
        pnl=(candles[-1].close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-candles[-1].close)*10*LOT-COMMISSION
        trades.append({'d':pos,'ep':ep,'ex':candles[-1].close,'pnl':pnl,'b':n-1-ei,'exit':'eod'})

    closed=[t for t in trades if t['exit']!='eod']
    if not closed: return None
    wins=[t for t in closed if t['pnl']>0]
    losses=[t for t in closed if t['pnl']<=0]
    tp=sum(t['pnl'] for t in closed)
    gp=sum(t['pnl'] for t in wins)
    gl=abs(sum(t['pnl'] for t in losses))
    longs=sum(1 for t in closed if t['d']=='BUY')
    shorts=sum(1 for t in closed if t['d']=='SELL')
    long_pnl=sum(t['pnl'] for t in closed if t['d']=='BUY')
    short_pnl=sum(t['pnl'] for t in closed if t['d']=='SELL')
    cum,peak,mdd=0,0,0
    for t in closed:
        cum+=t['pnl']; peak=max(peak,cum); mdd=max(mdd,peak-cum)
    avg_win = round(gp/len(wins), 2) if wins else 0
    avg_loss = round(gl/len(losses), 2) if losses else 0
    return {
        'trades':len(closed),'wins':len(wins),
        'total_pnl':round(tp,2),'win_rate':round(len(wins)/len(closed)*100,1),
        'pf':round(gp/gl,2) if gl>0 else 0,
        'max_dd':round(mdd,2),'avg_pnl':round(tp/len(closed),2),
        'longs':longs,'shorts':shorts,'long_pnl':round(long_pnl,2),'short_pnl':round(short_pnl,2),
        'avg_win':avg_win,'avg_loss':avg_loss,
    }

def r(label, **kw):
    """Helper to run and format result"""
    base = dict(trail_atr=1.0, hard_atr=2.0, min_bars=100,
                rsi_period=14, rsi_os=30, rsi_ob=70,
                cci_period=20, cci_os=-100, cci_ob=100,
                use_ma14=True, use_bb=False,
                use_adx_mode=False, adx_range=20, adx_trend=25,
                require_bb=False, entry_threshold=2)
    base.update(kw)
    res = run_bt(ALL_DATA[label], **base)
    return res

def p(res, tag=''):
    """Print one result"""
    if res is None:
        print(f"    {tag}: 无交易")
        return
    m = 'V' if res['total_pnl']>0 else 'X'
    print(f"    {tag}: {res['trades']}笔 ${res['total_pnl']} PF={res['pf']} "
          f"WR={res['win_rate']}% DD=${res['max_dd']} "
          f"avgW=${res['avg_win']} avgL=${res['avg_loss']} "
          f"多${res['long_pnl']} 空${res['short_pnl']} {m}")


# ═══════════════════ 运行 ═══════════════════

print("="*120)
print("  震荡指标组合 V2 — 加权评分 + 多场景 (0.01 lot)")
print("  A) RSI(±2) + CCI(±1) + MA14(±1)  → threshold=2/3/4")
print("  B) RSI(±2) + BB(±1) + MA14(±1)    → threshold=2/3/4")
print("  C) RSI(±2) + CCI(±1) + BB(±1) + MA14(±1)  → threshold=2/3/4")
print("  D) 出场优化 (ATR trail 1.5/2.0)")
print("  E) RSI周期 5/8/14 + RSI阈值变体")
print("  F) 去MA14, 仅RSI+CCI+BB")
print("="*120)

for label in ['M30', 'M15', 'H1']:
    data = ALL_DATA.get(label)
    if not data: continue
    print(f"\n{'#'*80}")
    print(f"  ## {label} ({len(data):,}根K线)")
    print(f"{'#'*80}")

    # ── A: RSI(±2) + CCI(±1) + MA14(±1) ──
    print("\n  ── A: RSI(±2) + CCI(±1) + MA14(±1) ──")
    config_a = dict(use_ma14=True, use_bb=False, use_adx_mode=False)
    for thr in [2, 3, 4]:
        res = r(label, entry_threshold=thr, **config_a)
        p(res, f"thr={thr}")

    # ADX模式 + thr=2 (不用config_a因为里面use_adx_mode=False会冲突)
    for adx_r, adx_t in [(20,25),(22,27)]:
        res = r(label, entry_threshold=2, use_adx_mode=True, adx_range=adx_r, adx_trend=adx_t,
                use_ma14=True, use_bb=False)
        p(res, f"thr=2 ADX<{adx_r}/>{adx_t}")

    # ── B: RSI(±2) + BB(±1) + MA14(±1) ──
    print("\n  ── B: RSI(±2) + BB(±1) + MA14(±1) ──")
    config_b = dict(use_ma14=True, use_bb=True, use_adx_mode=False)
    for thr in [2, 3, 4]:
        res = r(label, entry_threshold=thr, **config_b)
        p(res, f"thr={thr}")

    # ── C: RSI(±2) + CCI(±1) + BB(±1) + MA14(±1) ──
    print("\n  ── C: RSI(±2) + CCI(±1) + BB(±1) + MA14(±1) ──")
    config_c = dict(use_ma14=True, use_bb=True, use_adx_mode=False)
    for thr in [2, 3, 4]:
        res = r(label, entry_threshold=thr, **config_c)
        p(res, f"thr={thr}")

    # ── D: 出场优化 ──
    print("\n  ── D: 出场优化 (基准A+thr=2) ──")
    for trail, hard in [(1.5, 2.0), (1.5, 3.0), (2.0, 3.0), (1.0, 3.0)]:
        res = r(label, trail_atr=trail, hard_atr=hard, entry_threshold=2, **config_a)
        p(res, f"trail={trail} hard={hard}")

    # ── E: RSI周期 ──
    print("\n  ── E: RSI周期 (thr=2, A基准) ──")
    for rsi_p in [5, 8, 14]:
        res = r(label, rsi_period=rsi_p, entry_threshold=2, **config_a)
        p(res, f"RSI周期{rsi_p}")
    for rsi_p, os, ob in [(5, 20, 80), (8, 25, 75), (14, 25, 75)]:
        res = r(label, rsi_period=rsi_p, rsi_os=os, rsi_ob=ob, entry_threshold=2, **config_a)
        p(res, f"RSI{rsi_p}<{os}/>{ob}")

    # ── F: 去MA14, 仅RSI+CCI+BB ──
    print("\n  ── F: 去MA14, 仅RSI(±2)+CCI(±1)+BB(±1) ──")
    config_f = dict(use_ma14=False, use_bb=True, use_adx_mode=False)
    for thr in [2, 3]:
        res = r(label, entry_threshold=thr, **config_f)
        p(res, f"thr={thr}")

    # ── G: RSI窄阈值+require_bb (A基准 thr=2) ──
    print("\n  ── G: RSI窄阈值+require_bb (A基准 thr=2) ──")
    for rsi_os, rsi_ob in [(20, 80), (25, 75), (15, 85)]:
        res = r(label, entry_threshold=2, rsi_os=rsi_os, rsi_ob=rsi_ob, **config_a)
        p(res, f"RSI<{rsi_os}/>{rsi_ob}")
    res = r(label, entry_threshold=2, require_bb=True, **config_a)
    p(res, "require_bb=True")

print("\n" + "="*120)
print("  扫描完成")
print("="*120)
