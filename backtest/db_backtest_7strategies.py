"""
7 策略数据库全量回测 v3 (端口偏移 +100)
ORB / GoldTraderEA / SMC-ICT / Stochastic / RSI-MR / Grid / ML-Score
"""
import math, os, sys, time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config.settings as _settings
_settings.FREEMT4_PORT = 23332
import logging; logging.basicConfig(level=logging.CRITICAL)

from data.database import get_conn
from core.bridge import Candle

COMMISSION = 0.50; LOT = 0.01; CONTRACT = 100; INITIAL = 10000.0
MIN_BARS = 260

conn = get_conn()
h1 = conn.execute("SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='H1' ORDER BY timestamp").fetchall()
conn.close()
H1 = [Candle(time=str(r[0]),open=r[1],high=r[2],low=r[3],close=r[4],volume=r[5]) for r in h1]
CL = [c.close for c in H1]; HI = [c.high for c in H1]; LO = [c.low for c in H1]
OP = [c.open for c in H1]; TS = [int(c.time) for c in H1]
N = len(H1)

# ── 预计算所有指标 ──
sma200 = [None]*N
for i in range(199,N):
    sma200[i]=sum(CL[i-199:i+1])/200

ema20 = [None]*N
k20=2/21
for i in range(N):
    ema20[i]=CL[0] if i==0 else (CL[i]-ema20[i-1])*k20+ema20[i-1]

ema50 = [None]*N
k50=2/51
for i in range(N):
    ema50[i]=CL[0] if i==0 else (CL[i]-ema50[i-1])*k50+ema50[i-1]

rsi14 = [None]*N
for i in range(14,N):
    g=l=0
    for j in range(i-13,i+1):
        d=CL[j]-CL[j-1]
        g+=max(d,0)
        l+=max(-d,0)
    ag=g/14
    al=l/14
    rsi14[i]=100 if al==0 else 100-100/(1+ag/al)

atr14 = [None]*N
for i in range(1,N):
    tr=max(HI[i]-LO[i],abs(HI[i]-CL[i-1]),abs(LO[i]-CL[i-1]))
    if i==15:
        atr14[i]=sum(max(HI[j]-LO[j],abs(HI[j]-CL[j-1]),abs(LO[j]-CL[j-1])) for j in range(1,16))/14
    elif i>15:
        atr14[i]=(atr14[i-1]*13+tr)/14

bbu=[None]*N
bbl=[None]*N
for i in range(19,N):
    r=CL[i-19:i+1]
    s=sum(r)/20
    v=sum((c-s)**2 for c in r)/20
    d=math.sqrt(v)
    bbu[i]=s+2.5*d
    bbl[i]=s-2.5*d

kcu=[None]*N
kcl=[None]*N
for i in range(N):
    if ema20[i] is None or atr14[i] is None: continue
    kcu[i]=ema20[i]+atr14[i]*2.5
    kcl[i]=ema20[i]-atr14[i]*2.5

macdh=[None]*N
k12=2/13;k26=2/27;k9=2/10
e12=e26=CL[0]
ml=[]
for i in range(N):
    e12=(CL[i]-e12)*k12+e12
    e26=(CL[i]-e26)*k26+e26
    ml.append(e12-e26)
sg=[ml[0]]
for v in ml[1:]:
    sg.append((v-sg[-1])*k9+sg[-1])
for i in range(N):
    macdh[i]=ml[i]-sg[i]

stk=[None]*N
std=[None]*N
for i in range(8,N):
    w=H1[i-8:i+1]
    hi=max(c.high for c in w)
    lo=min(c.low for c in w)
    stk[i]=50 if hi==lo else (w[-1].close-lo)/(hi-lo)*100
for i in range(10,N):
    std[i]=sum(stk[i-2:i+1])/3

# ── 回测引擎 (修复版本) ──
def run(name, entry_fn, sl_mult=2.0, trail_mult=0):
    trades=[];pnl=0.0;peak=0.0;mdd=0.0
    ipos=False;entry=0;d_=None;th=0;tl=0
    for i in range(MIN_BARS, N):
        atr=atr14[i]
        if atr is None or atr==0: continue
        cl=CL[i]
        closed=False
        if ipos and entry>0:
            sl_dist=atr*sl_mult
            if d_=="BUY":
                th=max(th,cl)
                if trail_mult>0 and th-cl>atr*trail_mult:
                    pp=(cl-entry)*CONTRACT*LOT-COMMISSION;trades.append({'d':'B','ep':entry,'ex':cl,'p':round(pp,2),'r':'TR'});pnl+=pp;closed=True
            else:
                tl=min(tl,cl)
                if trail_mult>0 and cl-tl>atr*trail_mult:
                    pp=(entry-cl)*CONTRACT*LOT-COMMISSION;trades.append({'d':'S','ep':entry,'ex':cl,'p':round(pp,2),'r':'TR'});pnl+=pp;closed=True
            if not closed:
                if d_=="BUY" and cl<entry-sl_dist:
                    pp=(cl-entry)*CONTRACT*LOT-COMMISSION;trades.append({'d':'B','ep':entry,'ex':cl,'p':round(pp,2),'r':'SL'});pnl+=pp;closed=True
                elif d_=="SELL" and cl>entry+sl_dist:
                    pp=(entry-cl)*CONTRACT*LOT-COMMISSION;trades.append({'d':'S','ep':entry,'ex':cl,'p':round(pp,2),'r':'SL'});pnl+=pp;closed=True
            if closed:
                if pnl>peak:peak=pnl
                mdd=max(mdd,peak-pnl)
                ipos=False;entry=0
                continue  # 同一根 K 线不再开新仓
        if not ipos:
            sig,side=entry_fn(i)
            if sig:
                ipos=True;d_=side;th=cl;tl=cl
                entry=cl+(0.2 if side=="BUY" else 0)
    if ipos:
        lc=CL[-1];pp=(lc-entry)*CONTRACT*LOT-COMMISSION if d_=="BUY" else (entry-lc)*CONTRACT*LOT-COMMISSION
        trades.append({'d':d_[0],'ep':entry,'ex':lc,'p':round(pp,2),'r':'END'});pnl+=pp
        if pnl>peak:peak=pnl;mdd=max(mdd,peak-pnl)
    return trades,round(pnl,2),mdd

# ══════ 策略信号 ══════

# 1. ORB: 日开盘区间突破 + 趋势过滤
def orb(i):
    dt=datetime.fromtimestamp(TS[i])
    if dt.hour>=12: return False,None
    j=i
    while j>MIN_BARS and datetime.fromtimestamp(TS[j-1]).date()==dt.date(): j-=1
    if j==i: return False,None
    rng=max(HI[j]-LO[j],2.0)
    e20=ema20[i]
    if e20 is None: return False,None
    if CL[i]>HI[j]+rng and CL[i]>e20: return True,"BUY"
    if CL[i]<LO[j]-rng and CL[i]<e20: return True,"SELL"
    return False,None

# 2. GoldTraderEA: BB + MA 过滤
def gt(i):
    if any(x is None for x in [bbu[i],bbl[i],ema50[i],atr14[i]]): return False,None
    if CL[i]>bbu[i] and CL[i]>ema50[i]: return True,"BUY"
    if CL[i]<bbl[i] and CL[i]<ema50[i]: return True,"SELL"
    return False,None

# 3. SMC-ICT: 流动性狩猎
def smc(i):
    if i<25 or atr14[i] is None: return False,None
    ll=min(LO[i-20:i]);hh=max(HI[i-20:i])
    if LO[i]<=ll*1.001 and LO[i]>=ll*0.995 and CL[i]>ll: return True,"BUY"
    if HI[i]>=hh*0.999 and HI[i]<=hh*1.005 and CL[i]<hh: return True,"SELL"
    return False,None

# 4. Stochastic K/D交叉
def stoch(i):
    stk_i=stk[i];std_i=std[i]
    if any(x is None for x in [stk_i,std_i,ema50[i]]): return False,None
    pk=stk[i-1] if i>0 and stk[i-1] is not None else 50
    if stk_i<20 and stk_i>pk and CL[i]>ema50[i]: return True,"BUY"
    if stk_i>80 and stk_i<pk and CL[i]<ema50[i]: return True,"SELL"
    return False,None

# 5. RSI Mean Reversion
def rsi_mr(i):
    r=rsi14[i];e=ema20[i]
    if r is None or e is None: return False,None
    if r<25 and CL[i]<e: return True,"BUY"
    if r>75 and CL[i]>e: return True,"SELL"
    return False,None

# 6. Grid (独立实现)
def grid_run():
    t=[];pnl=0.0;peak=0.0;mdd=0.0;lyrs=[];lk=0;step=25;ml=3;tp=12;sl_=50
    for i in range(MIN_BARS,N):
        atr=atr14[i];cl=CL[i]
        if atr is None: continue
        if len(lyrs)==0 and i>lk+5:
            lyrs=[cl];lk=i;continue
        if len(lyrs)>0 and len(lyrs)<ml and cl<lyrs[-1]-step:
            lyrs.append(cl);lk=i
        if len(lyrs)>0:
            tp_pnl=sum((cl-l)*CONTRACT*LOT-COMMISSION for l in lyrs) if len(lyrs)==1 else (cl-lyrs[0])*CONTRACT*LOT*0.5*len(lyrs)
            if lyrs[0] and cl>lyrs[0]+tp:
                pp=sum((cl-l)*CONTRACT*LOT-COMMISSION for l in lyrs)
                t.append({'d':'B','ep':lyrs[0],'ex':cl,'p':round(pp,2),'r':'TP'});pnl+=pp;lyrs=[];lk=i
            elif lyrs[-1] and cl<lyrs[-1]-sl_:
                pp=sum((cl-l)*CONTRACT*LOT-COMMISSION for l in lyrs)
                t.append({'d':'B','ep':lyrs[0],'ex':cl,'p':round(pp,2),'r':'SL'});pnl+=pp;lyrs=[];lk=i
        if pnl>peak:peak=pnl;mdd=max(mdd,peak-pnl)
    if lyrs:
        lc=CL[-1];pp=sum((lc-l)*CONTRACT*LOT-COMMISSION for l in lyrs)
        t.append({'d':'B','ep':lyrs[0],'ex':lc,'p':round(pp,2),'r':'END'});pnl+=pp
    return t,round(pnl,2),mdd

# 7. ML-Score: 多因子评分
def ml(i):
    items=[sma200[i],ema50[i],rsi14[i],macdh[i],stk[i],bbu[i],bbl[i],atr14[i],kcu[i],kcl[i]]
    if any(x is None for x in items): return False,None
    cl=CL[i];ls=ss=0
    if cl>sma200[i]: ls+=2
    else: ss+=2
    if macdh[i]>0: ls+=1
    else: ss+=1
    if stk[i]<25: ls+=2
    if stk[i]>75: ss+=2
    if rsi14[i]<30: ls+=2
    if rsi14[i]>70: ss+=2
    if cl<=bbl[i]: ls+=2
    if cl>=bbu[i]: ss+=2
    if cl<=kcl[i]: ls+=1
    if cl>=kcu[i]: ss+=1
    r10=max(HI[i-9:i+1])-min(LO[i-9:i+1])
    if r10>0:
        pos=(cl-min(LO[i-9:i+1]))/r10
        pk=stk[i-1] if i>0 and stk[i-1] is not None else stk[i]
        if pos<0.25 and stk[i]>pk: ls+=1
        if pos>0.75 and stk[i]<pk: ss+=1
    if ls>=5 and ls>ss: return True,"BUY"
    if ss>=5 and ss>ls: return True,"SELL"
    return False,None

# ══════ 运行 ══════
STRATS = [
    ("ORB",orb,2.0,0),("GoldTraderEA",gt,2.5,3.0),
    ("SMC-ICT",smc,2.0,0),("Stochastic",stoch,2.0,0),
    ("RSI-MR",rsi_mr,2.0,0),("ML-Score",ml,2.5,3.0),
]

def main():
    t0=time.time()
    dt0=datetime.fromtimestamp(TS[0]);dt1=datetime.fromtimestamp(TS[-1])
    print(f"\n  {'='*78}")
    print(f"  7 策略全量数据库回测 (端口偏移 +100)")
    print(f"  H1: {N} 根 ({dt0.strftime('%Y-%m-%d')} ~ {dt1.strftime('%Y-%m-%d')})")
    print(f"  LOT: 0.01  佣金: $0.50  期初: ${INITIAL}")
    print(f"  {'='*78}")
    hdr=f"  {'策略':<14} {'交易':>5} {'总盈亏':>10} {'收益率':>8} {'胜率':>6} {'均盈':>8} {'均亏':>8} {'PF':>5} {'最大回撤':>13}"
    print(hdr);print(f"  {'-'*14} {'-'*5} {'-'*10} {'-'*8} {'-'*6} {'-'*8} {'-'*8} {'-'*5} {'-'*13}")

    rows=[]
    for name,fn,sl,tr in STRATS:
        trades,pnl,mdd=run(name,fn,sl,tr)
        n=len(trades);wins=[t for t in trades if t['p']>0];losses=[t for t in trades if t['p']<=0]
        wr=len(wins)/n*100 if n else 0;aw=sum(t['p'] for t in wins)/len(wins) if wins else 0
        al=sum(t['p'] for t in losses)/len(losses) if losses else 0
        gp=sum(t['p'] for t in wins);gm=abs(sum(t['p'] for t in losses));pf=gp/gm if gm else 999
        rows.append((name,n,pnl,pnl/INITIAL*100,wr,aw,al,pf,mdd))
    for r in rows:
        print(f"  {r[0]:<14} {r[1]:>5} {r[2]:>+10.2f} {r[3]:>+7.2f}% {r[4]:>5.1f}% {r[5]:>8.2f} {r[6]:>8.2f} {r[7]:>5.2f} {r[8]:>8.2f} ({r[8]/INITIAL*100:.1f}%)")

    # Grid
    gpnl,gt_,gm=0,None,0
    try:
        gt_,gpnl,gm=grid_run()
    except Exception as e:
        print(f"  Grid ERROR: {e}")
    gn=len(gt_ if gt_ else [])
    if gn:
        gtrades=gt_;gpnl_r=gpnl;gmdd=gm
        gwins=[t for t in gtrades if t['p']>0];gloss=[t for t in gtrades if t['p']<=0]
        gwr=len(gwins)/gn*100 if gn else 0;gaw=sum(t['p'] for t in gwins)/len(gwins) if gwins else 0
        gal=sum(t['p'] for t in gloss)/len(gloss) if gloss else 0
        ggp=sum(t['p'] for t in gwins);ggm=abs(sum(t['p'] for t in gloss));gpf=ggp/ggm if ggm else 999
        rows.append(("Grid",gn,gpnl_r,gpnl_r/INITIAL*100,gwr,gaw,gal,gpf,gmdd))
        r=rows[-1]
        print(f"  {'Grid':<14} {r[1]:>5} {r[2]:>+10.2f} {r[3]:>+7.2f}% {r[4]:>5.1f}% {r[5]:>8.2f} {r[6]:>8.2f} {r[7]:>5.2f} {r[8]:>8.2f} ({r[8]/INITIAL*100:.1f}%)")

    print(f"  {'='*78}")
    print(f"  耗时: {time.time()-t0:.1f}s")
    print(f"  {'='*78}")

    best=max(rows,key=lambda x:x[2])
    print(f"\n  最佳: {best[0]} (${best[2]:+.2f} / {best[3]:+.2f}%)")
    sorted_r=sorted(rows,key=lambda x:x[2],reverse=True)
    if len(sorted_r)>1:
        print(f"  次佳: {sorted_r[1][0]} (${sorted_r[1][2]:+.2f})")

    # 最佳策略最近交易
    best_trades=None
    for name,fn,sl,tr in STRATS:
        if name==best[0]:
            best_trades,_1,_2=run(name,fn,sl,tr)
            break
    if not best_trades: best_trades,_,_=run("ORB",orb,2.0,0)
    if best_trades:
        n=len(best_trades)
        print(f"\n  最佳({best[0]})最近{min(10,n)}笔:")
        for t in best_trades[-10:]:
            sgn="+" if t['p']>0 else ""
            print(f"    {t['d']:>3} EP:{t['ep']:>9.2f} EX:{t['ex']:>9.2f}  {sgn}${t['p']:>+7.2f}  #{t['r']}")

if __name__=="__main__":
    main()
