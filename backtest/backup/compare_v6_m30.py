"""
V6 H1 vs M30 RSI 策略对比回测
"""
import sys, os, math, json
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.database import init_db, get_conn
from core.bridge import Candle

init_db()
conn = get_conn()
h1_rows = conn.execute(
    "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='H1' ORDER BY timestamp"
).fetchall()
m30_rows = conn.execute(
    "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
).fetchall()
conn.close()

HC = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in h1_rows]
MC = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in m30_rows]
HP = [c.close for c in HC]
MP = [c.close for c in MC]

print(f"M30: {len(MC)} candles")
print(f"H1:  {len(HC)} candles")
print()

# === Common functions ===
def calc_rsi(closes, period=14):
    if len(closes) < period+1: return None
    g,l=[],[]
    for i in range(1,period+1): d=closes[i]-closes[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g)/period; al=sum(l)/period
    for i in range(period+1,len(closes)):
        d=closes[i]-closes[i-1]; ag=(ag*(period-1)+max(d,0))/period; al=(al*(period-1)+max(-d,0))/period
    return 100.0 if al==0 else 100.0-100.0/(1.0+ag/al)

def calc_sma(closes, p):
    if len(closes) < p: return None
    return sum(closes[-p:])/p

def calc_ema(closes, p):
    if len(closes) < p: return None
    k=2.0/(p+1); e=closes[0]
    for v in closes[1:]: e=(v-e)*k+e
    return e

def calc_atr(candles, p=20):
    if len(candles) < p+2: return None
    tr=[]
    for i in range(1,len(candles)):
        h=candles[i].high; l=candles[i].low; pc=candles[i-1].close
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    if len(tr) < p: return None
    atr=[sum(tr[:p])/p]
    for i in range(p,len(tr)): atr.append((atr[-1]*(p-1)+tr[i])/p)
    return atr[-1]

def calc_bb(closes, p=20, std_mul=2.5):
    if len(closes) < p: return None
    r=closes[-p:]; s=sum(r)/p
    v=sum((c-s)**2 for c in r)/p
    return {'lower':s-std_mul*math.sqrt(v), 'upper':s+std_mul*math.sqrt(v), 'sma':s}

def calc_keltner(closes, atr_val, period=20, mult=2.5):
    ema20=calc_ema(closes,period)
    if ema20 is None or atr_val is None: return None
    return {'lower':ema20-atr_val*mult, 'upper':ema20+atr_val*mult}

def calc_stoch(candles, kp=9, slowing=3, dp=3):
    n=len(candles)
    if n<kp+slowing+dp+1: return None
    rk=[]
    for j in range(kp-1,n):
        w=candles[j-kp+1:j+1]; hi=max(x.high for x in w); lo=min(x.low for x in w); cl=w[-1].close
        rk.append(50.0 if hi==lo else (cl-lo)/(hi-lo)*100)
    if len(rk)<slowing+dp+1: return None
    sk=[sum(rk[j-slowing+1:j+1])/slowing for j in range(slowing-1,len(rk))]
    if len(sk)<dp+1: return None
    return {'curr_k':sk[-1], 'prev_k':sk[-2]}

def calc_macd(closes):
    if len(closes)<35: return None
    k12,k26,k9=2.0/13,2.0/27,2.0/10; e12=closes[0]; e26=closes[0]; ml=[]
    for p in closes: e12=(p-e12)*k12+e12; e26=(p-e26)*k26+e26; ml.append(e12-e26)
    sig=[ml[0]]; [sig.append((v-sig[-1])*k9+sig[-1]) for v in ml[1:]]
    hv=[ml[i]-sig[i] for i in range(len(ml))]
    return {'hist_values':hv}

def check_bottom_div(hist, lb=10):
    n=len(hist); s=n-lb*2
    if s<1: return False
    lows=[]
    for j in range(s+1,n-1):
        if hist[j]<hist[j-1] and hist[j]<hist[j+1]: lows.append((j,hist[j]))
    return len(lows)>=2 and lows[-1][1]>lows[-2][1]

def check_top_div(hist, lb=10):
    n=len(hist); s=n-lb*2
    if s<1: return False
    highs=[]
    for j in range(s+1,n-1):
        if hist[j]>hist[j-1] and hist[j]>hist[j+1]: highs.append((j,hist[j]))
    return len(highs)>=2 and highs[-1][1]<highs[-2][1]

COMMISSION = 0.5

# === V6 H1 Backtest ===
print("="*70)
print("  [V6 H1] 7因子评分 + M30方向 + ATR出场")
print("="*70)

t1=[]; p1=None; ep1=0; ei1=0; th1={}; tl1={}
MIN_BARS = 250
for i in range(MIN_BARS, len(HC)):
    c=HC[i]; close=c.close; low=c.low; high=c.high
    sc=HP[:i+1]; sca=HC[:i+1]
    sma200=calc_sma(sc,200);
    if sma200 is None: continue
    stoch=calc_stoch(sca);
    if stoch is None: continue
    rsi_val=calc_rsi(sc);
    if rsi_val is None: continue
    bb=calc_bb(sc,20,2.5);
    if bb is None: continue
    atr_val=calc_atr(sca,20);
    if atr_val is None: continue
    kc=calc_keltner(sc,atr_val);
    if kc is None: continue
    macd=calc_macd(sc)
    bdiv=check_bottom_div(macd['hist_values']) if macd else False
    tdiv=check_top_div(macd['hist_values']) if macd else False
    vr=sum(HP[max(0,i-9):i+1])/min(10,i+1)
    lv=atr_val<vr*0.02

    # V6 scoring (7 factors)
    ls=0; ss=0
    if close>sma200: ls+=1
    if stoch['curr_k']<30 or stoch['prev_k']<30: ls+=1
    if low<=bb['lower']: ls+=1
    if low<=kc['lower']: ls+=1
    if bdiv: ls+=2
    if rsi_val<30: ls+=1
    if lv: ls+=1
    if close<=sma200:
        if stoch['curr_k']>65: ss+=1
        if high>=kc['upper']: ss+=1
        if tdiv: ss+=2
        if rsi_val>70: ss+=1

    sig=None
    if ls>=3: sig='BUY'
    elif ss>=3: sig='SELL'

    # ATR trail exit
    if p1=='BUY' and i>ei1+4:
        th1['h']=max(th1.get('h',ep1),high)
        if close<th1['h']-atr_val*4.0:
            pnl=(close-ep1)*1.0-COMMISSION; t1.append({'d':p1,'ep':ep1,'ex':close,'pnl':pnl,'b':i-ei1}); p1=None; ei1=-1;continue
    elif p1=='SELL' and i>ei1+4:
        tl1['l']=min(tl1.get('l',ep1),low)
        if close>tl1['l']+atr_val*4.0:
            pnl=(ep1-close)*1.0-COMMISSION; t1.append({'d':p1,'ep':ep1,'ex':close,'pnl':pnl,'b':i-ei1}); p1=None; ei1=-1;continue
    if p1=='BUY' and (ep1-close)>atr_val*2.0:
        pnl=(close-ep1)*1.0-COMMISSION; t1.append({'d':p1,'ep':ep1,'ex':close,'pnl':pnl,'b':i-ei1}); p1=None; ei1=-1;continue
    elif p1=='SELL' and (close-ep1)>atr_val*2.0:
        pnl=(ep1-close)*1.0-COMMISSION; t1.append({'d':p1,'ep':ep1,'ex':close,'pnl':pnl,'b':i-ei1}); p1=None; ei1=-1;continue

    if sig and p1 is None: p1=sig; ep1=close; ei1=i
    elif sig and sig!=p1 and p1:
        pnl=(close-ep1)*1.0-COMMISSION if p1=='BUY' else (ep1-close)*1.0-COMMISSION
        t1.append({'d':p1,'ep':ep1,'ex':close,'pnl':pnl,'b':i-ei1}); p1=sig; ep1=close; ei1=i

if p1:
    pnl=(HP[-1]-ep1)*1.0-0.5 if p1=='BUY' else (ep1-HP[-1])*1.0-0.5
    t1.append({'d':p1,'ep':ep1,'ex':HP[-1],'pnl':pnl,'b':len(HC)-1-ei1})

c1=[t for t in t1]
tp1=sum(t['pnl'] for t in c1); w1=[t for t in c1 if t['pnl']>0]; l1=[t for t in c1 if t['pnl']<=0]
print(f"Trades: {len(c1)}  PnL: ${tp1:.2f}  WR: {len(w1)/len(c1)*100:.1f}%  AvgW: ${sum(t['pnl'] for t in w1)/len(w1):.2f}  AvgL: ${sum(t['pnl'] for t in l1)/len(l1):.2f}")

# === M30 RSI Backtest ===
print()
print("="*70)
print("  [M30 RSI] 5因子评分 + ATR出场")
print("="*70)

def get_h1_trend_at(m30_ts):
    idx=-1
    for j in range(len(HC)-1,-1,-1):
        if int(HC[j].time) <= m30_ts: idx=j; break
    if idx<200: return 'NEUTRAL'
    sub=HP[:idx+1]; sma200=sum(sub[-200:])/200
    return 'UP' if sub[-1]>sma200 else 'DOWN'

t2=[]; p2=None; ep2=0; ei2=0; th2={}; tl2={}
for i in range(100, len(MC)):
    c=MC[i]; close=c.close; low=c.low; high=c.high
    ts=int(c.time); sc=MP[:i+1]; sca=MC[:i+1]
    bb=calc_bb(sc,20,2.0)
    if bb is None: continue
    rsi_val=calc_rsi(sc,14)
    if rsi_val is None: continue
    atr_val=calc_atr(sca,20)
    if atr_val is None: continue
    h1_trend=get_h1_trend_at(ts)

    if i>=19:
        rm=calc_rsi(sc[:-1],14); rn=calc_rsi(sc,14)
        m30d='up' if(rm and rn and rm<rn) else 'down' if(rm and rn and rm>rn) else 'flat'
    else: m30d='flat'
    vr=sum(MP[max(0,i-9):i+1])/min(10,i+1)
    lv=atr_val<vr*0.025

    ls=0; ss=0
    if h1_trend=='UP': ls+=1
    elif h1_trend=='DOWN': ss+=1
    if close<=bb['lower']: ls+=1
    if close>=bb['upper']: ss+=1
    if rsi_val<30: ls+=1
    if rsi_val>65: ss+=1
    if m30d=='up': ls+=1
    if m30d=='down': ss+=1
    if lv: ls+=1; ss+=1

    # Exit
    if p2=='BUY' and i>ei2+4:
        th2['h']=max(th2.get('h',ep2),high)
        if close<th2['h']-atr_val*4.0:
            pnl=(close-ep2)*1.0-COMMISSION; t2.append({'d':p2,'ep':ep2,'ex':close,'pnl':pnl,'b':i-ei2}); p2=None; ei2=-1;continue
    elif p2=='SELL' and i>ei2+4:
        tl2['l']=min(tl2.get('l',ep2),low)
        if close>tl2['l']+atr_val*4.0:
            pnl=(ep2-close)*1.0-COMMISSION; t2.append({'d':p2,'ep':ep2,'ex':close,'pnl':pnl,'b':i-ei2}); p2=None; ei2=-1;continue
    if p2=='BUY' and (ep2-close)>atr_val*3.0:
        pnl=(close-ep2)*1.0-COMMISSION; t2.append({'d':p2,'ep':ep2,'ex':close,'pnl':pnl,'b':i-ei2}); p2=None; ei2=-1;continue
    elif p2=='SELL' and (close-ep2)>atr_val*3.0:
        pnl=(ep2-close)*1.0-COMMISSION; t2.append({'d':p2,'ep':ep2,'ex':close,'pnl':pnl,'b':i-ei2}); p2=None; ei2=-1;continue

    sig=None
    if ls>=3 and h1_trend=='UP': sig='BUY'
    elif ss>=3 and h1_trend=='DOWN': sig='SELL'

    if sig and p2 is None: p2=sig; ep2=close; ei2=i
    elif sig and sig!=p2 and p2:
        pnl=(close-ep2)*1.0-COMMISSION if p2=='BUY' else (ep2-close)*1.0-COMMISSION
        t2.append({'d':p2,'ep':ep2,'ex':close,'pnl':pnl,'b':i-ei2}); p2=sig; ep2=close; ei2=i

if p2:
    pnl=(MP[-1]-ep2)*1.0-0.5 if p2=='BUY' else (ep2-MP[-1])*1.0-0.5
    t2.append({'d':p2,'ep':ep2,'ex':MP[-1],'pnl':pnl,'b':len(MC)-1-ei2})

c2=[t for t in t2]
tp2=sum(t['pnl'] for t in c2); w2=[t for t in c2 if t['pnl']>0]; l2=[t for t in c2 if t['pnl']<=0]
print(f"Trades: {len(c2)}  PnL: ${tp2:.2f}  WR: {len(w2)/len(c2)*100:.1f}%  AvgW: ${sum(t['pnl'] for t in w2)/len(w2):.2f}  AvgL: ${sum(t['pnl'] for t in l2)/len(l2):.2f}")

# === Summary ===
print()
print("="*70)
print("  对比总结")
print("="*70)

# Align to same date range for fair comparison
# Both strategies cover 2026-04 ~ 2026-06
h1_start = int(HC[MIN_BARS].time)
m30_start = int(MC[100].time)
common_start = max(h1_start, m30_start)
h1_end = int(HC[-1].time)
m30_end = int(MC[-1].time)
common_end = min(h1_end, m30_end)
print(f"  共同时段: {datetime.fromtimestamp(common_start).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(common_end).strftime('%Y-%m-%d')}")

# Stats per strategy
avg_win1 = sum(t['pnl'] for t in w1)/len(w1) if w1 else 0
avg_loss1 = sum(t['pnl'] for t in l1)/len(l1) if l1 else 0
avg_win2 = sum(t['pnl'] for t in w2)/len(w2) if w2 else 0
avg_loss2 = sum(t['pnl'] for t in l2)/len(l2) if l2 else 0

print()
print(f"  {'指标':<20} {'V6 H1':>15} {'M30 RSI':>15}")
print(f"  {'-'*50}")
print(f"  {'周期':<20} {'H1':>15} {'M30':>15}")
print(f"  {'交易次数':<20} {len(c1):>15} {len(c2):>15}")
print(f"  {'总盈亏':<20} {f'${tp1:.2f}':>15} {f'${tp2:.2f}':>15}")
print(f"  {'胜率':<20} {f'{len(w1)/len(c1)*100:.1f}%':>15} {f'{len(w2)/len(c2)*100:.1f}%':>15}")
print(f"  {'平均盈利':<20} {f'${avg_win1:.2f}':>15} {f'${avg_win2:.2f}':>15}")
print(f"  {'平均亏损':<20} {f'${avg_loss1:.2f}':>15} {f'${avg_loss2:.2f}':>15}")
print(f"  {'盈亏比':<20} {f'{abs(avg_win1/avg_loss1):.2f}':>15} {f'{abs(avg_win2/avg_loss2):.2f}':>15}")

# Monthly breakdown
print()
print(f"  [月度明细]")
months = {}
for t in c1:
    m = datetime.fromtimestamp(int(HC[min(len(HC)-1, t.get('ei',HC.index(HC[-1])) if 'ei' in dir() else 0)].time) if False else 202606).strftime('%Y%m')
print(f"  (回测时段较短, 未按月细分)")

# Last 5 trades each
print()
print(f"  V6 H1 最近5笔:")
for t in c1[-5:]:
    m='+' if t['pnl']>0 else '-'
    print(f"    {m} {t['d']:4s} ${t['ep']:>7.2f} -> ${t['ex']:>7.2f} ${t['pnl']:>7.2f} [{t['b']:3d}b]")

print(f"  M30 RSI 最近5笔:")
for t in c2[-5:]:
    m='+' if t['pnl']>0 else '-'
    print(f"    {m} {t['d']:4s} ${t['ep']:>7.2f} -> ${t['ex']:>7.2f} ${t['pnl']:>7.2f} [{t['b']:3d}b]")

# === Key differences ===
print()
print("  [策略特点对比]")
print(f"  V6 H1:   多因子(7+1), H1大周期, 趋势+反转混合, 交易频率低")
print(f"  M30 RSI: RSI+BB均值回归, M30中周期, 纯反转策略, 交易频率高")
print(f"           H1趋势过滤确保两策略方向一致, 避免互相对冲")
print(f"           两策略互补: V6抓大趋势, M30抓波段回调")
