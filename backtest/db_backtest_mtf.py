"""
7 策略多周期 (M30/H1/H4) 数据库全量回测 (端口偏移 +100)
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

# ── 数据加载 ──
def load_tf(tf):
    conn=get_conn()
    rows=conn.execute("SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe=? ORDER BY timestamp", (tf,)).fetchall()
    conn.close()
    if not rows: return None,None,None,None,None,None
    h1=[Candle(time=str(r[0]),open=r[1],high=r[2],low=r[3],close=r[4],volume=r[5]) for r in rows]
    cl=[c.close for c in h1]; hi=[c.high for c in h1]; lo=[c.low for c in h1]; op=[c.open for c in h1]; ts=[int(c.time) for c in h1]
    return h1,cl,hi,lo,op,ts

# ── 指标预计算 ──
def calc_indicators(cl,hi,lo,h1,n):
    sma200=[None]*n
    for i in range(199,n): sma200[i]=sum(cl[i-199:i+1])/200
    ema20=[None]*n;k20=2/21
    for i in range(n): ema20[i]=cl[0] if i==0 else (cl[i]-ema20[i-1])*k20+ema20[i-1]
    ema50=[None]*n;k50=2/51
    for i in range(n): ema50[i]=cl[0] if i==0 else (cl[i]-ema50[i-1])*k50+ema50[i-1]
    rsi14=[None]*n
    for i in range(14,n):
        g=l=0
        for j in range(i-13,i+1): d=cl[j]-cl[j-1];g+=max(d,0);l+=max(-d,0)
        ag=g/14;al=l/14;rsi14[i]=100 if al==0 else 100-100/(1+ag/al)
    atr14=[None]*n
    for i in range(1,n):
        tr=max(hi[i]-lo[i],abs(hi[i]-cl[i-1]),abs(lo[i]-cl[i-1]))
        if i==15: atr14[i]=sum(max(hi[j]-lo[j],abs(hi[j]-cl[j-1]),abs(lo[j]-cl[j-1])) for j in range(1,16))/14
        elif i>15: atr14[i]=(atr14[i-1]*13+tr)/14
    bbu=[None]*n;bbl=[None]*n
    for i in range(19,n):
        r=cl[i-19:i+1];s=sum(r)/20;v=sum((c-s)**2 for c in r)/20;d=math.sqrt(v)
        bbu[i]=s+2.5*d;bbl[i]=s-2.5*d
    kcu=[None]*n;kcl=[None]*n
    for i in range(n):
        if ema20[i] is None or atr14[i] is None: continue
        kcu[i]=ema20[i]+atr14[i]*2.5;kcl[i]=ema20[i]-atr14[i]*2.5
    macdh=[None]*n;k12=2/13;k26=2/27;k9=2/10;e12=e26=cl[0];ml=[]
    for i in range(n): e12=(cl[i]-e12)*k12+e12;e26=(cl[i]-e26)*k26+e26;ml.append(e12-e26)
    sg=[ml[0]]
    for v in ml[1:]:
        sg.append((v-sg[-1])*k9+sg[-1])
    for i in range(n):
        macdh[i]=ml[i]-sg[i]
    stk=[None]*n;std=[None]*n
    for i in range(8,n):
        w=h1[i-8:i+1];hx=max(c.high for c in w);lx=min(c.low for c in w)
        stk[i]=50 if hx==lx else (w[-1].close-lx)/(hx-lx)*100
    for i in range(10,n): std[i]=sum(stk[i-2:i+1])/3
    return {'sma200':sma200,'ema20':ema20,'ema50':ema50,'rsi14':rsi14,'atr14':atr14,
            'bbu':bbu,'bbl':bbl,'kcu':kcu,'kcl':kcl,'macdh':macdh,'stk':stk,'std':std,'n':n}

# ── 信号函数工厂 ──
def make_signals(I,CL,HI,LO,OP,TS,MIN_B,TF):

    def orb(i):
        dt=datetime.fromtimestamp(TS[i])
        if dt.hour>=12: return False,None
        j=i
        while j>MIN_B and datetime.fromtimestamp(TS[j-1]).date()==dt.date(): j-=1
        if j==i: return False,None
        rng=max(HI[j]-LO[j],2.0);e20=I['ema20'][i]
        if e20 is None: return False,None
        if CL[i]>HI[j]+rng and CL[i]>e20: return True,"BUY"
        if CL[i]<LO[j]-rng and CL[i]<e20: return True,"SELL"
        return False,None

    def gt(i):
        if any(x is None for x in [I['bbu'][i],I['bbl'][i],I['ema50'][i],I['atr14'][i]]): return False,None
        if CL[i]>I['bbu'][i] and CL[i]>I['ema50'][i]: return True,"BUY"
        if CL[i]<I['bbl'][i] and CL[i]<I['ema50'][i]: return True,"SELL"
        return False,None

    def smc(i):
        if i<25 or I['atr14'][i] is None: return False,None
        ll=min(LO[i-20:i]);hh=max(HI[i-20:i])
        if LO[i]<=ll*1.001 and LO[i]>=ll*0.995 and CL[i]>ll: return True,"BUY"
        if HI[i]>=hh*0.999 and HI[i]<=hh*1.005 and CL[i]<hh: return True,"SELL"
        return False,None

    def stoch(i):
        stk_i=I['stk'][i];std_i=I['std'][i]
        if any(x is None for x in [stk_i,std_i,I['ema50'][i]]): return False,None
        pk=I['stk'][i-1] if i>0 and I['stk'][i-1] is not None else 50
        if stk_i<20 and stk_i>pk and CL[i]>I['ema50'][i]: return True,"BUY"
        if stk_i>80 and stk_i<pk and CL[i]<I['ema50'][i]: return True,"SELL"
        return False,None

    def rsi_mr(i):
        r=I['rsi14'][i];e=I['ema20'][i]
        if r is None or e is None: return False,None
        if r<25 and CL[i]<e: return True,"BUY"
        if r>75 and CL[i]>e: return True,"SELL"
        return False,None

    def ml(i):
        items=[I['sma200'][i],I['ema50'][i],I['rsi14'][i],I['macdh'][i],I['stk'][i],I['bbu'][i],I['bbl'][i],I['atr14'][i],I['kcu'][i],I['kcl'][i]]
        if any(x is None for x in items): return False,None
        cl=CL[i];ls=ss=0
        if cl>I['sma200'][i]: ls+=2
        else: ss+=2
        if I['macdh'][i]>0: ls+=1
        else: ss+=1
        if I['stk'][i]<25: ls+=2
        if I['stk'][i]>75: ss+=2
        if I['rsi14'][i]<30: ls+=2
        if I['rsi14'][i]>70: ss+=2
        if cl<=I['bbl'][i]: ls+=2
        if cl>=I['bbu'][i]: ss+=2
        if cl<=I['kcl'][i]: ls+=1
        if cl>=I['kcu'][i]: ss+=1
        r10=max(HI[i-9:i+1])-min(LO[i-9:i+1])
        if r10>0:
            pos=(cl-min(LO[i-9:i+1]))/r10
            pk_=I['stk'][i-1] if i>0 and I['stk'][i-1] is not None else I['stk'][i]
            if pos<0.25 and I['stk'][i]>pk_: ls+=1
            if pos>0.75 and I['stk'][i]<pk_: ss+=1
        if ls>=5 and ls>ss: return True,"BUY"
        if ss>=5 and ss>ls: return True,"SELL"
        return False,None

    def grid_run():
        t=[];pnl=0.0;peak=0.0;mdd=0.0;lyrs=[];lk=0
        step=25;ml_=3;tp=12;sl_=50
        if TF=="M30": step=12;tp=6;sl_=25
        elif TF=="H4": step=50;tp=24;sl_=100
        for i in range(MIN_B,I['n']):
            atr=I['atr14'][i];cl=CL[i]
            if atr is None: continue
            if len(lyrs)==0 and i>lk+5:
                lyrs=[cl];lk=i;continue
            if len(lyrs)>0 and len(lyrs)<ml_ and cl<lyrs[-1]-step:
                lyrs.append(cl);lk=i
            if len(lyrs)>0:
                tp_pnl=(cl-lyrs[0])*CONTRACT*LOT if lyrs else 0
                if tp_pnl>tp:
                    pp=sum((cl-l)*CONTRACT*LOT-COMMISSION for l in lyrs)
                    t.append({'d':'G','ep':lyrs[0],'ex':cl,'p':round(pp,2),'r':'TP'});pnl+=pp;lyrs=[];lk=i
                elif tp_pnl<-sl_:
                    pp=sum((cl-l)*CONTRACT*LOT-COMMISSION for l in lyrs)
                    t.append({'d':'G','ep':lyrs[0],'ex':cl,'p':round(pp,2),'r':'SL'});pnl+=pp;lyrs=[];lk=i
            if pnl>peak:peak=pnl;mdd=max(mdd,peak-pnl)
        if lyrs:
            lc=CL[-1];pp=sum((lc-l)*CONTRACT*LOT-COMMISSION for l in lyrs)
            t.append({'d':'G','ep':lyrs[0],'ex':lc,'p':round(pp,2),'r':'END'});pnl+=pp
        return t,round(pnl,2),mdd

    return orb,gt,smc,stoch,rsi_mr,ml,grid_run

# ── 回测引擎 ──
def run(entry_fn,n,cl,atr14,sl_mult=2.0,trail_mult=0,MIN_B=260):
    trades=[];pnl=0.0;peak=0.0;mdd=0.0;ipos=False;entry=0;d_=None;th=0;tl=0
    for i in range(MIN_B,n):
        atr=atr14[i]
        if atr is None or atr==0: continue
        clv=cl[i];closed=False
        if ipos and entry>0:
            sl_dist=atr*sl_mult
            if d_=="BUY":
                th=max(th,clv)
                if trail_mult>0 and th-clv>atr*trail_mult:
                    pp=(clv-entry)*CONTRACT*LOT-COMMISSION;trades.append({'d':'B','ep':entry,'ex':clv,'p':round(pp,2),'r':'TR'});pnl+=pp;closed=True
            else:
                tl=min(tl,clv)
                if trail_mult>0 and clv-tl>atr*trail_mult:
                    pp=(entry-clv)*CONTRACT*LOT-COMMISSION;trades.append({'d':'S','ep':entry,'ex':clv,'p':round(pp,2),'r':'TR'});pnl+=pp;closed=True
            if not closed:
                if d_=="BUY" and clv<entry-sl_dist:
                    pp=(clv-entry)*CONTRACT*LOT-COMMISSION;trades.append({'d':'B','ep':entry,'ex':clv,'p':round(pp,2),'r':'SL'});pnl+=pp;closed=True
                elif d_=="SELL" and clv>entry+sl_dist:
                    pp=(entry-clv)*CONTRACT*LOT-COMMISSION;trades.append({'d':'S','ep':entry,'ex':clv,'p':round(pp,2),'r':'SL'});pnl+=pp;closed=True
            if closed:
                if pnl>peak:peak=pnl
                mdd=max(mdd,peak-pnl);ipos=False;entry=0;continue
        if not ipos:
            sig,side=entry_fn(i)
            if sig:
                ipos=True;d_=side;th=clv;tl=clv;entry=clv+(0.2 if side=="BUY" else 0)
    if ipos:
        lc=cl[-1];pp=(lc-entry)*CONTRACT*LOT-COMMISSION if d_=="BUY" else (entry-lc)*CONTRACT*LOT-COMMISSION
        trades.append({'d':d_[0],'ep':entry,'ex':lc,'p':round(pp,2),'r':'END'});pnl+=pp
        if pnl>peak:peak=pnl;mdd=max(mdd,peak-pnl)
    return trades,round(pnl,2),mdd

# ── 策略配置 (名称, sl_mult, trail_mult) ──
STRAT_CONF = [
    ("ORB",2.0,0),("GoldTraderEA",2.5,3.0),("SMC-ICT",2.0,0),
    ("Stochastic",2.0,0),("RSI-MR",2.0,0),("ML-Score",2.5,3.0),
]

def test_tf(tf,label):
    print(f"\n  [{label}] 加载数据...",end=" ",flush=True)
    h1,cl,hi,lo,op,ts=load_tf(tf)
    if h1 is None: print("无数据");return
    n=len(h1);MIN_B=min(260,n//3)
    dt0=datetime.fromtimestamp(ts[0]);dt1=datetime.fromtimestamp(ts[-1])
    print(f"{n} 根 ({dt0.strftime('%Y-%m-%d')} ~ {dt1.strftime('%Y-%m-%d')}), 预热 {MIN_B}",flush=True)
    I=calc_indicators(cl,hi,lo,h1,n)
    orb,gt,smc,stoch,rsi_mr,ml,grid_fn=make_signals(I,cl,hi,lo,op,ts,MIN_B,tf)
    fns=[orb,gt,smc,stoch,rsi_mr,ml]

    print(f"  {'='*70}")
    print(f"  {label} 回测结果")
    print(f"  {'='*70}")
    hdr=f"  {'策略':<14} {'交易':>5} {'总盈亏':>10} {'收益率':>8} {'胜率':>6} {'均盈':>8} {'均亏':>8} {'PF':>5} {'最大回撤':>13}"
    print(hdr);print(f"  {'-'*14} {'-'*5} {'-'*10} {'-'*8} {'-'*6} {'-'*8} {'-'*8} {'-'*5} {'-'*13}")

    rows=[]
    for idx,(name,sl,tr) in enumerate(STRAT_CONF):
        fn=fns[idx]
        trades,pnl,mdd=run(fn,n,cl,I['atr14'],sl,tr,MIN_B)
        n_t=len(trades);wins=[t for t in trades if t['p']>0];losses=[t for t in trades if t['p']<=0]
        wr=len(wins)/n_t*100 if n_t else 0;aw=sum(t['p'] for t in wins)/len(wins) if wins else 0
        al=sum(t['p'] for t in losses)/len(losses) if losses else 0
        gp=sum(t['p'] for t in wins);gm=abs(sum(t['p'] for t in losses));pf=gp/gm if gm else 999
        rows.append((name,n_t,pnl,pnl/INITIAL*100,wr,aw,al,pf,mdd))
        pnl_s=f"{pnl:+.2f}";pct_s=f"{pnl/INITIAL*100:+.2f}%"
        print(f"  {name:<14} {n_t:>5} {pnl:>+10.2f} {pct_s:>8} {wr:>5.1f}% {aw:>8.2f} {al:>8.2f} {pf:>5.2f} {mdd:>8.2f} ({mdd/INITIAL*100:.1f}%)")

    # Grid
    gtrades,gpnl,gmdd=grid_fn()
    gn=len(gtrades);gwins=[t for t in gtrades if t['p']>0];gloss=[t for t in gtrades if t['p']<=0]
    gwr=len(gwins)/gn*100 if gn else 0;gaw=sum(t['p'] for t in gwins)/len(gwins) if gwins else 0
    gal=sum(t['p'] for t in gloss)/len(gloss) if gloss else 0
    ggp=sum(t['p'] for t in gwins);ggm=abs(sum(t['p'] for t in gloss));gpf=ggp/ggm if ggm else 999
    rows.append(("Grid",gn,gpnl,gpnl/INITIAL*100,gwr,gaw,gal,gpf,gmdd))
    pnl_s=f"{gpnl:+.2f}";pct_s=f"{gpnl/INITIAL*100:+.2f}%"
    print(f"  {'Grid':<14} {gn:>5} {gpnl:>+10.2f} {pct_s:>8} {gwr:>5.1f}% {gaw:>8.2f} {gal:>8.2f} {gpf:>5.2f} {gmdd:>8.2f} ({gmdd/INITIAL*100:.1f}%)")
    print(f"  {'='*70}")
    return rows

def main():
    t0=time.time()
    all_r={}
    for tf,lb in [("M30","M30 (2445 根)"),("H1","H1 (8645 根)"),("H4","H4 (2095 根)")]:
        all_r[tf]=test_tf(tf,lb)
    # 汇总
    print(f"\n\n  {'='*90}")
    print(f"  多周期汇总 (总耗时: {time.time()-t0:.1f}s)")
    print(f"  {'='*90}")
    hdr=f"  {'策略':<12} {'M30交易':>7} {'M30盈亏':>9} {'M30收益':>7} | {'H1交易':>6} {'H1盈亏':>9} {'H1收益':>7} | {'H4交易':>6} {'H4盈亏':>9} {'H4收益':>7}"
    print(hdr)
    print(f"  {'-'*12} {'-'*7} {'-'*9} {'-'*7} {'-'*1} {'-'*6} {'-'*9} {'-'*7} {'-'*1} {'-'*6} {'-'*9} {'-'*7}")
    for i in range(7):
        name=STRAT_CONF[i][0] if i<6 else "Grid"
        parts=[]
        for tf in ["M30","H1","H4"]:
            r=all_r.get(tf,[])
            if i<len(r):
                parts.append((r[i][1],r[i][2],r[i][3]))
            else:
                parts.append((0,0,0))
        print(f"  {name:<12} {parts[0][0]:>7} {parts[0][1]:>+9.2f} {parts[0][2]:>+6.2f}% | {parts[1][0]:>6} {parts[1][1]:>+9.2f} {parts[1][2]:>+6.2f}% | {parts[2][0]:>6} {parts[2][1]:>+9.2f} {parts[2][2]:>+6.2f}%")
    # 最佳策略
    print(f"\n  各周期最佳:")
    for tf in ["M30","H1","H4"]:
        r=all_r.get(tf,[])
        if r:
            best=max(r,key=lambda x:x[2])
            print(f"    {tf}: {best[0]}  +${best[2]:.2f} ({best[3]:+.2f}%)")

if __name__=="__main__":
    main()
