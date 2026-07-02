"""
M30 RSI v7 — ADX 方案回测 (基线 + 方案B + 方案Cv2)
===================================================
基线: MA14 + BB + RSI极值 + RSI方向 (4因子评分≥3)
方案B: ADX≥30 方向门禁 (MA14=UP禁空, =DOWN禁多)
方案Cv2: ADX趋势加分 (ADX≥门限+MA14同向, +1分, 开仓≥4)
出场: ATR trailing + hard stop
"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.database import init_db, get_conn
from core.bridge import Candle

init_db()
conn = get_conn()
m30_rows = conn.execute(
    "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
).fetchall()
gc_rows = conn.execute(
    "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='GC_M30' ORDER BY timestamp"
).fetchall()
conn.close()

MC = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in m30_rows]
GC = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in gc_rows]

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

def calc_ema(closes, p):
    if len(closes)<p: return None
    k=2.0/(p+1); e=closes[0]
    for v in closes[1:]: e=(v-e)*k+e
    return e

def calc_atr(candles, p=20):
    if len(candles)<p+2: return None
    tr=[]
    for i in range(1,len(candles)):
        h=candles[i].high; l=candles[i].low; pc=candles[i-1].close
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    if len(tr)<p: return None
    atr=[sum(tr[:p])/p]
    for i in range(p,len(tr)): atr.append((atr[-1]*(p-1)+tr[i])/p)
    return atr[-1]

def calc_bb(closes, p=20, std_mul=2.0):
    if len(closes)<p: return None
    r=closes[-p:]; s=sum(r)/p
    v=sum((c-s)**2 for c in r)/p
    return {'sma':s,'upper':s+std_mul*math.sqrt(v),'lower':s-std_mul*math.sqrt(v)}

def calc_stoch(highs, lows, closes, k=14, d=3):
    """Stochastic %K and %D"""
    n=len(highs)
    if n<k: return None
    ll=min(lows[-k:]); hh=max(highs[-k:])
    if hh==ll: return {'k':50,'d':50}
    k_val=(closes[-1]-ll)/(hh-ll)*100
    if n<k+d: return {'k':k_val,'d':50}
    # %D = SMA of last d %K values
    k_list=[]
    for i in range(n-k-d+1, n+1):
        seg_lows=min(lows[max(0,i-k):i]); seg_highs=max(highs[max(0,i-k):i])
        if seg_highs!=seg_lows:
            k_list.append((closes[i-1]-seg_lows)/(seg_highs-seg_lows)*100)
        else:
            k_list.append(50)
    d_val=sum(k_list[-d:])/d if len(k_list)>=d else 50
    return {'k':k_list[-1],'d':d_val}

def calc_adx(highs, lows, closes, period=14):
    """Full Wilder ADX over the entire series up to current bar"""
    n=len(highs)
    if n<period+2: return None
    tr_list,pdm,mdm=[],[],[]
    for i in range(1,n):
        h,l,pc=highs[i],lows[i],closes[i-1]
        ph,pl=highs[i-1],lows[i-1]
        tr_list.append(max(h-l,abs(h-pc),abs(l-pc)))
        up=h-ph; down=pl-l
        pdm.append(up if(up>down and up>0) else 0)
        mdm.append(down if(down>up and down>0) else 0)
    if len(tr_list)<period: return None
    # Wilder smoothing
    atr=[sum(tr_list[:period])/period]
    sp=[sum(pdm[:period])/period]
    sm_=[sum(mdm[:period])/period]
    for j in range(period,len(tr_list)):
        atr.append((atr[-1]*(period-1)+tr_list[j])/period)
        sp.append((sp[-1]*(period-1)+pdm[j])/period)
        sm_.append((sm_[-1]*(period-1)+mdm[j])/period)
    # DX values
    dx_list=[]
    for j in range(len(atr)):
        p=100*sp[j]/atr[j] if atr[j]>0 else 0
        n_=100*sm_[j]/atr[j] if atr[j]>0 else 0
        dx=abs(p-n_)/(p+n_)*100 if(p+n_)>0 else 0
        dx_list.append(dx)
    # ADX = smoothed DX
    adx_val=sum(dx_list[:period])/period
    for j in range(period,len(dx_list)):
        adx_val=(adx_val*(period-1)+dx_list[j])/period
    pdi_f=100*sp[-1]/atr[-1] if atr[-1]>0 else 0
    ndi_f=100*sm_[-1]/atr[-1] if atr[-1]>0 else 0
    return {'adx':adx_val,'pdi':pdi_f,'ndi':ndi_f}

COMMISSION=0.5
LOT=0.01

def run_backtest(candles, variant='baseline', trail_atr=1.0, hard_atr=2.0, min_bars=100, enable_di_exit=False):
    """
    variant: 'baseline' | 'di_gate' | 'di_full'
    baseline: 原4因子评分, 无DI过滤
    di_gate:  DI方向门禁 (+DI>-DI只做多, -DI>+DI只做空)
    di_full:  门禁 + DI翻转出场 (开多后+DI<-DI则平, 开空后-DI<+DI则平)
    """
    trades=[]; pos=None; ep=0; ei=0
    trail_h={}; trail_l={}
    entry_di={}
    prev_k=50; prev_d=50
    n=len(candles)

    for i in range(min_bars, n):
        c=candles[i]; close=c.close; low=c.low; high=c.high
        ts=int(c.time)
        sub=candles[:i+1]
        sc=[x.close for x in sub]
        highs=[x.high for x in sub]
        lows=[x.low for x in sub]

        # Indicators
        bb=calc_bb(sc,20,2.0)
        if bb is None: continue
        rsi_val=calc_rsi(sc,14)
        if rsi_val is None: continue
        atr_val=calc_atr(sub,20)
        if atr_val is None: continue
        ma14=sum(sc[-14:])/14 if len(sc)>=14 else None
        if ma14 is None: continue

        # ADX
        adx_data=calc_adx(highs,lows,sc,14)
        adx=adx_data['adx'] if adx_data else 0
        pdi=adx_data['pdi'] if adx_data else 0
        ndi=adx_data['ndi'] if adx_data else 0

        # Stoch (用于金叉/死叉确认)
        stoch=calc_stoch(highs,lows,sc,14,3)
        k50=stoch['k'] if stoch else 50; d50=stoch['d'] if stoch else 50
        cross_up = prev_k <= prev_d and k50 > d50  # 金叉(本bar刚发生)
        cross_dn = prev_k >= prev_d and k50 < d50  # 死叉(本bar刚发生)
        stoch_bull = k50 > d50   # K在D上方(含已金叉和已在上方)
        stoch_bear = k50 < d50   # K在D下方(含已死叉和已在下方)
        prev_k=k50; prev_d=d50

        # MA14 trend
        m30_trend='UP' if close>ma14 else 'DOWN'

        # RSI direction
        if i>=19:
            rm=calc_rsi(sc[:-1],14); rn=calc_rsi(sc,14)
            m30d='up' if(rm and rn and rm<rn) else 'down' if(rm and rn and rm>rn) else 'flat'
        else: m30d='flat'

        # ═══ Scoring (4-factor base: ①MA14 ②BB ③RSI ④RSIdir) ═══
        entry_threshold=3
        ls=0; ss=0

        # ① MA14 trend
        if m30_trend=='UP': ls+=1
        else: ss+=1

        # ② BB touch + ③ RSI (base scores)
        bb_long=1 if close<=bb['lower'] else 0
        bb_short=1 if close>=bb['upper'] else 0
        rsi_long=1 if rsi_val<30 else 0
        rsi_short=1 if rsi_val>65 else 0

        # ④ RSI direction
        if m30d=='up': ls+=1
        if m30d=='down': ss+=1

        # Apply BB+RSI scores (先加基础分)
        ls+=bb_long+rsi_long
        ss+=bb_short+rsi_short

        # ── DI + Stoch 综合过滤 ──
        ls_entry=entry_threshold; ss_entry=entry_threshold
        need_stoch=False
        if variant=='always_stoch':
            need_stoch='both'
        elif variant in ('di_entry','di_full') and di_threshold>0:
            di_diff=pdi-ndi
            if di_diff < -di_threshold:
                ls_entry=entry_threshold+1
                need_stoch='buy'
            if di_diff >  di_threshold:
                ss_entry=entry_threshold+1
                need_stoch='sell'

        # ── Exit ──

        # ── Exit ──
        tid=f"{ts}_{ep}" if pos else ""
        # ATR trail stop
        if pos=='BUY' and ei>=0 and i>ei+4:
            trail_h[tid]=max(trail_h.get(tid,ep),high)
            if close<trail_h[tid]-atr_val*trail_atr:
                pnl=(close-ep)*10*LOT-COMMISSION
                trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'trail'});
                pos=None;ei=-1;continue
        elif pos=='SELL' and ei>=0 and i>ei+4:
            trail_l[tid]=min(trail_l.get(tid,ep),low)
            if close>trail_l[tid]+atr_val*trail_atr:
                pnl=(ep-close)*10*LOT-COMMISSION
                trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'trail'});
                pos=None;ei=-1;continue
        # Hard stop
        if pos=='BUY' and (ep-close)>atr_val*hard_atr:
            pnl=(close-ep)*10*LOT-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'hard'});
            pos=None;ei=-1;continue
        elif pos=='SELL' and (close-ep)>atr_val*hard_atr:
            pnl=(ep-close)*10*LOT-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'hard'});
            pos=None;ei=-1;continue
        # DI flip exit (当趋势方向逆转时提前出场)
        if pos and enable_di_exit and tid in entry_di:
            e_di=entry_di[tid]
            if pos=='BUY' and ndi>pdi:  # 开多时+DI>-DI, 现在反转
                pnl=(close-ep)*10*LOT-COMMISSION
                trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'di_flip'});
                del entry_di[tid]; pos=None;ei=-1;continue
            elif pos=='SELL' and pdi>ndi:  # 开空时-DI>+DI, 现在反转
                pnl=(ep-close)*10*LOT-COMMISSION
                trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'di_flip'});
                del entry_di[tid]; pos=None;ei=-1;continue

        # ── Entry ──
        sig=None
        if ls>=ls_entry:
            if need_stoch in (False,'sell') or (need_stoch in ('buy','both') and stoch_bull): sig='BUY'
        elif ss>=ss_entry:
            if need_stoch in (False,'buy') or (need_stoch in ('sell','both') and stoch_bear): sig='SELL'

        if sig and pos is None:
            pos=sig; ep=close; ei=i
            if enable_di_exit:
                entry_di[f"{ts}_{ep}"]={'pdi':pdi,'ndi':ndi}
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-close)*10*LOT-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'flip'});
            pos=sig; ep=close; ei=i

    if pos:
        pnl=(candles[-1].close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-candles[-1].close)*10*LOT-COMMISSION
        trades.append({'d':pos,'ep':ep,'ex':candles[-1].close,'pnl':pnl,'b':n-1-ei,'exit':'eod'})

    closed=[t for t in trades if t['exit']!='eod']
    if not closed:
        return {'trades':0,'wins':0,'total_pnl':0,'win_rate':0,'pf':0,'max_dd':0,'avg_pnl':0}
    wins=[t for t in closed if t['pnl']>0]
    losses=[t for t in closed if t['pnl']<=0]
    tp=sum(t['pnl'] for t in closed)
    gp=sum(t['pnl'] for t in wins)
    gl=abs(sum(t['pnl'] for t in losses))
    cum,peak,mdd=0,0,0
    for t in closed:
        cum+=t['pnl']; peak=max(peak,cum); mdd=max(mdd,peak-cum)
    return {
        'trades':len(closed),'wins':len(wins),
        'total_pnl':round(tp,2),'win_rate':round(len(wins)/len(closed)*100,1),
        'pf':round(gp/gl,2) if gl>0 else 0,
        'max_dd':round(mdd,2),
        'avg_pnl':round(tp/len(closed),2),
    }

# ═══════════════ Run ═══════════════
print("="*100)
print("  M30 RSI v7 — ±DI 门禁回测 (0.01 lot, 实盘手数)")
print("="*100)
print()

all_results={}
configs=[
    ("基线 v7",          'baseline', 0,   False),
    ("DI+StochK>D th30", 'di_entry', 30, False),
    ("DI+StochK>D th25", 'di_entry', 25, False),
    ("DI+StochK>D th22", 'di_entry', 22, False),
    ("永远Stoch",        'always_stoch', 0, False),
    ("完整 th=25",       'di_full', 25, True),
]
for label, data in [("M30", MC), ("GC_M30", GC)]:
    print(f"  ── {label} ({len(data)} 根) ──")
    for name, v, di_th, di_exit in configs:
        r=run_backtest(data, variant=v, di_threshold=di_th, enable_di_exit=di_exit)
        all_results[f"{label}_{name}"]=r
        m='✅' if r['total_pnl']>0 else '❌'
        print(f"  {name:<22}  {r['trades']:>4} 笔  胜率{r['win_rate']:>6.1f}%  "
              f"P/L ${r['total_pnl']:>+8.2f}  PF{r['pf']:>6.2f}  "
              f"DD${r['max_dd']:>6.2f}  {m}")
    print()

print("="*100)
print("  双品种对比")
print("="*100)
print(f"  {'方案':<22}  {'M30 P/L':>10}  {'M30胜率':>8}  {'M30 PF':>7}  | "
      f"{'GC P/L':>10}  {'GC胜率':>8}  {'GC PF':>7}")
print("  "+"-"*90)
for name, v, di_th, di_exit in configs:
    m_r=all_results[f"M30_{name}"]
    g_r=all_results[f"GC_M30_{name}"]
    both='✅✅' if(m_r['total_pnl']>0 and g_r['total_pnl']>0) else('✅--' if m_r['total_pnl']>0 else('--✅' if g_r['total_pnl']>0 else '----'))
    print(f"  {name:<22}  ${m_r['total_pnl']:>+8.2f}  {m_r['win_rate']:>6.1f}%  "
          f"{m_r['pf']:>6.2f}  | ${g_r['total_pnl']:>+8.2f}  {g_r['win_rate']:>6.1f}%  "
          f"{g_r['pf']:>6.2f}  {both}")
