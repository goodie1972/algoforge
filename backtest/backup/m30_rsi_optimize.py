"""
M30 RSI + BB 策略参数优化回测
入口: RSI+BB评分制 | 出场: ATR动态追踪
"""
import sys, os, math, json
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.database import init_db, get_conn
from core.bridge import Candle

init_db()
conn = get_conn()
m30_rows = conn.execute(
    "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
).fetchall()
h1_rows = conn.execute(
    "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='H1' ORDER BY timestamp"
).fetchall()
conn.close()

MC = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in m30_rows]
HC = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in h1_rows]
MP = [c.close for c in MC]

print(f"M30: {len(MC)} candles ({datetime.fromtimestamp(int(MC[0].time)).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(int(MC[-1].time)).strftime('%Y-%m-%d')})")
print(f"H1:  {len(HC)} candles")

def calc_rsi(closes, period=14):
    if len(closes)<period+1: return None
    gains,losses=[],[]
    for i in range(1,period+1):
        d=closes[i]-closes[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains)/period; al=sum(losses)/period
    for i in range(period+1,len(closes)):
        d=closes[i]-closes[i-1]
        ag=(ag*(period-1)+max(d,0))/period; al=(al*(period-1)+max(-d,0))/period
    return 100.0 if al==0 else 100.0-100.0/(1.0+ag/al)

def calc_ema(closes, p):
    if len(closes)<p: return None
    k=2.0/(p+1); e=closes[0]
    for v in closes[1:]: e=(v-e)*k+e
    return e

def calc_sma(closes, p):
    if len(closes)<p: return None
    return sum(closes[-p:])/p

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

def get_h1_trend_at(m30_ts):
    idx=-1
    for j in range(len(HC)-1,-1,-1):
        if int(HC[j].time) <= m30_ts: idx=j; break
    if idx<200: return 'NEUTRAL'
    sub=[c.close for c in HC[:idx+1]]
    sma200=sum(sub[-200:])/200
    return 'UP' if sub[-1]>sma200 else 'DOWN'

COMMISSION = 0.5

def run_variant(rsi_os, rsi_ob, bb_std, thresh, atr_trail, atr_hard, min_bars=100):
    trades=[]; pos=None; ep=0; ei=0
    trail_h={}; trail_l={}

    for i in range(min_bars, len(MC)):
        c=MC[i]; close=c.close; low=c.low; high=c.high
        ts=int(c.time); sc=MP[:i+1]; sca=MC[:i+1]

        bb=calc_bb(sc,20,bb_std)
        if bb is None: continue
        rsi_val=calc_rsi(sc,14)
        if rsi_val is None: continue
        atr_val=calc_atr(sca,20)
        if atr_val is None: continue
        ema30=calc_ema(sc,30)
        if ema30 is None: continue

        h1_trend=get_h1_trend_at(ts)

        # M30 RSI direction (2-bar)
        if i>=19:
            rm=calc_rsi(sc[:-1],14); rn=calc_rsi(sc,14)
            m30d='up' if(rm and rn and rm<rn) else 'down' if(rm and rn and rm>rn) else 'flat'
        else: m30d='flat'

        # Low vol filter
        vol_recent=sum(MP[max(0,i-9):i+1])/min(10,i+1)
        low_vol=atr_val<vol_recent*0.025

        # Scoring
        ls=0; ss=0
        # 1) H1 trend
        if h1_trend=='UP': ls+=1
        elif h1_trend=='DOWN': ss+=1
        # 2) BB + RSI
        if close<=bb['lower']: ls+=1
        if close>=bb['upper']: ss+=1
        # 3) RSI extreme
        if rsi_val<rsi_os: ls+=1
        if rsi_val>rsi_ob: ss+=1
        # 4) M30 RSI direction
        if m30d=='up': ls+=1
        if m30d=='down': ss+=1
        # 5) Low volatility
        if low_vol: ls+=1; ss+=1

        # === EXIT ===
        if pos=='BUY' and ei>=0 and i>ei+4:
            tid=f"{ts}_{ep}"
            trail_h[tid]=max(trail_h.get(tid,ep),high)
            if close<trail_h[tid]-atr_val*atr_trail:
                pnl=(close-ep)*1.0-COMMISSION
                trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei});
                pos=None;ei=-1;continue
        elif pos=='SELL' and ei>=0 and i>ei+4:
            tid=f"{ts}_{ep}"
            trail_l[tid]=min(trail_l.get(tid,ep),low)
            if close>trail_l[tid]+atr_val*atr_trail:
                pnl=(ep-close)*1.0-COMMISSION
                trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei});
                pos=None;ei=-1;continue
        # Hard stop
        if pos=='BUY' and (ep-close)>atr_val*atr_hard:
            pnl=(close-ep)*1.0-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei});
            pos=None;ei=-1;continue
        elif pos=='SELL' and (close-ep)>atr_val*atr_hard:
            pnl=(ep-close)*1.0-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei});
            pos=None;ei=-1;continue

        # === ENTRY ===
        sig=None
        if ls>=thresh: sig='BUY'
        elif ss>=thresh: sig='SELL'

        if sig and pos is None:
            pos=sig; ep=close; ei=i
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*1.0-COMMISSION if pos=='BUY' else (ep-close)*1.0-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei});
            pos=sig; ep=close; ei=i

    if pos:
        pnl=(MP[-1]-ep)*1.0-0.5 if pos=='BUY' else (ep-MP[-1])*1.0-0.5
        trades.append({'d':pos,'ep':ep,'ex':MP[-1],'pnl':pnl,'b':len(MC)-1-ei})

    closed=[t for t in trades]
    if not closed: return {'trades':0,'pnl':0,'wr':0,'avg_w':0,'avg_l':0,'score':-999}
    tp=sum(t['pnl'] for t in closed)
    w=[t for t in closed if t['pnl']>0]; l=[t for t in closed if t['pnl']<=0]
    wr=len(w)/len(closed)*100 if closed else 0
    aw=sum(t['pnl'] for t in w)/len(w) if w else 0
    al=sum(t['pnl'] for t in l)/len(l) if l else 0
    # Scoring: prefer high PnL + good win rate + decent trade count
    n_trades=len(closed)
    score= tp * (wr/100) - abs(al)*(n_trades-len(w))/max(n_trades,1)*0.5
    return {'trades':n_trades,'pnl':round(tp,2),'wr':round(wr,1),
            'avg_w':round(aw,2),'avg_l':round(al,2),'score':round(score,2)}

# ============= Parameter Scan =============
variants=[]
for rsi_os in [30, 35]:
    for rsi_ob in [65, 70]:
        for bb_std in [2.0, 2.5]:
            for thresh in [2, 3]:
                for atr_trail in [3.0, 4.0]:
                    for atr_hard in [2.0, 3.0]:
                        variants.append((rsi_os, rsi_ob, bb_std, thresh, atr_trail, atr_hard))

print(f"\nScanning {len(variants)} parameter combinations...")
results=[]
for v in variants:
    r=run_variant(*v)
    r['params']={'rsi_os':v[0],'rsi_ob':v[1],'bb_std':v[2],'thresh':v[3],'atr_trail':v[4],'atr_hard':v[5]}
    results.append(r)

# Sort by score
results.sort(key=lambda x: x['score'], reverse=True)

print(f"\n{'='*85}")
print(f"  Top 15 Parameter Combinations (sorted by composite score)")
print(f"{'='*85}")
print(f"{'Rank':>4} {'RSI_OS':>6} {'RSI_OB':>6} {'BB_STD':>6} {'Th':>3} {'Trl':>5} {'Hard':>5} {'Trades':>7} {'PnL':>10} {'WR':>6} {'AvgW':>7} {'AvgL':>7} {'Score':>8}")
print("-"*85)
for i,r in enumerate(results[:15]):
    p=r['params']
    print(f"{i+1:>4} {p['rsi_os']:>6} {p['rsi_ob']:>6} {p['bb_std']:>6.1f} {p['thresh']:>3} {p['atr_trail']:>5.1f} {p['atr_hard']:>5.1f} {r['trades']:>7} ${r['pnl']:>8.2f} {r['wr']:>5.1f}% ${r['avg_w']:>6.2f} ${r['avg_l']:>6.2f} {r['score']:>8.2f}")

# Also show by pure PnL
results_by_pnl=sorted(results, key=lambda x: x['pnl'], reverse=True)
print(f"\n{'='*85}")
print(f"  Top 15 by Pure PnL")
print(f"{'='*85}")
print(f"{'Rank':>4} {'RSI_OS':>6} {'RSI_OB':>6} {'BB_STD':>6} {'Th':>3} {'Trl':>5} {'Hard':>5} {'Trades':>7} {'PnL':>10} {'WR':>6} {'AvgW':>7} {'AvgL':>7} {'Score':>8}")
print("-"*85)
for i,r in enumerate(results_by_pnl[:15]):
    p=r['params']
    print(f"{i+1:>4} {p['rsi_os']:>6} {p['rsi_ob']:>6} {p['bb_std']:>6.1f} {p['thresh']:>3} {p['atr_trail']:>5.1f} {p['atr_hard']:>5.1f} {r['trades']:>7} ${r['pnl']:>8.2f} {r['wr']:>5.1f}% ${r['avg_w']:>6.2f} ${r['avg_l']:>6.2f} {r['score']:>8.2f}")

# Save best variant
best = results[0]
best_params = best['params']
print(f"\n{'='*85}")
print(f"  Best parameters (composite score)")
print(f"{'='*85}")
for k,v in best_params.items():
    print(f"  {k}: {v}")
print(f"  Result: {best['trades']} trades, ${best['pnl']} PnL, {best['wr']}% WR")
print()
print(f"  Running best variant in detail...")

# Run best variant in detail
r=run_variant(best_params['rsi_os'], best_params['rsi_ob'], best_params['bb_std'],
              best_params['thresh'], best_params['atr_trail'], best_params['atr_hard'], min_bars=100)

# Also run baseline: no H1 trend, no low-vol filter
print(f"\n  Best variant detailed trades:")
trades=[]; pos=None; ep=0; ei=0
trail_h={}; trail_l={}
p=best_params
for i in range(100, len(MC)):
    c=MC[i]; close=c.close; low=c.low; high=c.high
    ts=int(c.time); sc=MP[:i+1]; sca=MC[:i+1]
    bb=calc_bb(sc,20,p['bb_std'])
    if bb is None: continue
    rsi_val=calc_rsi(sc,14)
    if rsi_val is None: continue
    atr_val=calc_atr(sca,20)
    if atr_val is None: continue
    ema30=calc_ema(sc,30)
    if ema30 is None: continue
    h1_trend=get_h1_trend_at(ts)
    if i>=19:
        rm=calc_rsi(sc[:-1],14); rn=calc_rsi(sc,14)
        m30d='up' if(rm and rn and rm<rn) else 'down' if(rm and rn and rm>rn) else 'flat'
    else: m30d='flat'
    vol_recent=sum(MP[max(0,i-9):i+1])/min(10,i+1)
    low_vol=atr_val<vol_recent*0.025
    ls=0; ss=0
    if h1_trend=='UP': ls+=1
    elif h1_trend=='DOWN': ss+=1
    if close<=bb['lower']: ls+=1
    if close>=bb['upper']: ss+=1
    if rsi_val<p['rsi_os']: ls+=1
    if rsi_val>p['rsi_ob']: ss+=1
    if m30d=='up': ls+=1
    if m30d=='down': ss+=1
    if low_vol: ls+=1; ss+=1

    # Exit
    if pos=='BUY' and ei>=0 and i>ei+4:
        tid=f"{ts}_{ep}"; trail_h[tid]=max(trail_h.get(tid,ep),high)
        if close<trail_h[tid]-atr_val*p['atr_trail']:
            pnl=(close-ep)*1.0-COMMISSION; trades.append({'dir':pos,'ep':ep,'ex':close,'pnl':pnl,'bars':i-ei,'r':'trail'}); pos=None;ei=-1;continue
    elif pos=='SELL' and ei>=0 and i>ei+4:
        tid=f"{ts}_{ep}"; trail_l[tid]=min(trail_l.get(tid,ep),low)
        if close>trail_l[tid]+atr_val*p['atr_trail']:
            pnl=(ep-close)*1.0-COMMISSION; trades.append({'dir':pos,'ep':ep,'ex':close,'pnl':pnl,'bars':i-ei,'r':'trail'}); pos=None;ei=-1;continue
    if pos=='BUY' and (ep-close)>atr_val*p['atr_hard']:
        pnl=(close-ep)*1.0-COMMISSION; trades.append({'dir':pos,'ep':ep,'ex':close,'pnl':pnl,'bars':i-ei,'r':'hard'}); pos=None;ei=-1;continue
    elif pos=='SELL' and (close-ep)>atr_val*p['atr_hard']:
        pnl=(ep-close)*1.0-COMMISSION; trades.append({'dir':pos,'ep':ep,'ex':close,'pnl':pnl,'bars':i-ei,'r':'hard'}); pos=None;ei=-1;continue

    sig=None
    if ls>=p['thresh']: sig='BUY'
    elif ss>=p['thresh']: sig='SELL'
    if sig and pos is None: pos=sig; ep=close; ei=i
    elif sig and sig!=pos and pos:
        pnl=(close-ep)*1.0-COMMISSION if pos=='BUY' else (ep-close)*1.0-COMMISSION
        trades.append({'dir':pos,'ep':ep,'ex':close,'pnl':pnl,'bars':i-ei,'r':'rev'}); pos=sig; ep=close; ei=i

if pos:
    pnl=(MP[-1]-ep)*1.0-0.5 if pos=='BUY' else (ep-MP[-1])*1.0-0.5
    trades.append({'dir':pos,'ep':ep,'ex':MP[-1],'pnl':pnl,'bars':len(MC)-1-ei,'r':'open'})

closed=[t for t in trades]
tp=sum(t['pnl'] for t in closed)
w=[t for t in closed if t['pnl']>0]; l=[t for t in closed if t['pnl']<=0]
print(f"  Trades: {len(closed)}  PnL: ${tp:.2f}  WR: {len(w)/len(closed)*100:.1f}%")
print(f"  AvgWin: ${sum(t['pnl'] for t in w)/len(w):.2f}" if w else "", end="")
print(f"  AvgLoss: ${sum(t['pnl'] for t in l)/len(l):.2f}" if l else "")
print(f"\n  Recent trades (last 10):")
for t in closed[-10:]:
    m='+' if t['pnl']>0 else '-'
    print(f"  {m} {t['dir']:4s} ${t['ep']:>7.2f} -> ${t['ex']:>7.2f} ${t['pnl']:>7.2f} [{t['bars']:3d}b] [{t.get('r','')}]")

# Save
with open("backtest/m30_rsi_optimize_result.json", "w") as f:
    json.dump({
        "best_params": best_params,
        "best_result": {"trades": r['trades'], "pnl": r['pnl'], "wr": r['wr']},
        "top10": [{"params": r['params'], "trades": r['trades'], "pnl": r['pnl'], "wr": r['wr']} for r in results[:10]]
    }, f, indent=2)
print(f"\n  Results saved to backtest/m30_rsi_optimize_result.json")
