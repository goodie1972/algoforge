"""
时间周期对比回测 v2 — 排除过滤条件干扰，只看纯周期影响
"""
import math, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.database import get_candles
from datetime import datetime

BB_PERIOD = 20; BB_STD = 2.0; RSI_PERIOD = 14
RSI_OVERSOLD = 30; RSI_OVERBOUGHT = 70
STOCH_K=8; STOCH_SLOWING=3; STOCH_D=3
STOCH_OVERSOLD=20; STOCH_OVERBOUGHT=80
LOT=0.01; CONTRACT=100; COMM=0.5

def calc_rsi(closes, p=14):
    if len(closes) < p+1: return None
    g=l=0
    for i in range(1,p+1):
        d=closes[i]-closes[i-1]
        g+=max(d,0); l+=max(-d,0)
    ag=g/p; al=l/p
    for i in range(p+1,len(closes)):
        d=closes[i]-closes[i-1]
        ag=(ag*(p-1)+max(d,0))/p; al=(al*(p-1)+max(-d,0))/p
    return 100-100/(1+ag/al) if al>0 else 100

def calc_ema(c, p):
    if len(c)<p: return None
    k=2/(p+1); e=c[0]
    for v in c[1:]: e=(v-e)*k+e
    return e

def calc_bb(c, p, m):
    if len(c)<p: return None,None,None
    s=sum(c[-p:])/p
    v=sum((x-s)**2 for x in c[-p:])/p
    std=math.sqrt(v)
    return s,std*m,std

def calc_stoch(cd, kp, sp, dp):
    n=len(cd)
    if n<kp+sp+dp+1: return None
    rk=[]
    for i in range(kp-1,n):
        w=cd[i-kp+1:i+1]; h=max(x['high'] for x in w); l=min(x['low'] for x in w)
        cl=w[-1]['close']
        rk.append(50 if h==l else (cl-l)/(h-l)*100)
    if len(rk)<sp+dp+1: return None
    sk=[sum(rk[i-sp+1:i+1])/sp for i in range(sp-1,len(rk))]
    if len(sk)<dp+1: return None
    return sk[-2],sk[-1],sum(sk[-dp:])/dp,sum(sk[-(dp+1):-1])/dp

# ========== RSI Bollinger (无M30过滤, EMA20出场) ==========
def run_rsi(candles, label):
    pos=[]; act=[]; tp=0; w=l=lw=lt=sw=st=0
    for i in range(max(BB_PERIOD,RSI_PERIOD)+10,len(candles)):
        cu=candles[i]; cl=cu['close']; hi=cu['high']; lo=cu['low']
        cs=[x['close'] for x in candles[:i+1]]
        sma,bw,_=calc_bb(cs,BB_PERIOD,BB_STD); rsi=calc_rsi(cs,RSI_PERIOD)
        ema20=calc_ema(cs,20)
        if sma is None: continue
        up=sma+bw; lo_bb=sma-bw; sd=bw*0.35

        # exit
        cl2=[]; st2=[]
        for p in act:
            b=p.direction=='BUY'
            if p.sl>0:
                if b and lo<=p.sl: p.exit_price=p.sl; p.exit_reason='SL'; cl2.append(p); continue
                if not b and hi>=p.sl: p.exit_price=p.sl; p.exit_reason='SL'; cl2.append(p); continue
            if ema20 is not None:
                if b:
                    if ema20>p.trail_sl and ema20<cl: p.trail_sl=ema20; p.sl=ema20
                    if lo<=p.trail_sl: p.exit_price=p.trail_sl; p.exit_reason='EMA20'; cl2.append(p); continue
                else:
                    if ema20<p.trail_sl and ema20>cl: p.trail_sl=ema20; p.sl=ema20
                    if hi>=p.trail_sl: p.exit_price=p.trail_sl; p.exit_reason='EMA20'; cl2.append(p); continue
            st2.append(p)
        for p in cl2:
            p.pnl=(p.exit_price-p.entry_price)*CONTRACT*LOT-COMM if p.direction=='BUY' else (p.entry_price-p.exit_price)*CONTRACT*LOT-COMM
            tp+=p.pnl; w+=p.pnl>0; l+=p.pnl<=0
            if p.direction=='BUY': lt+=1; lw+=p.pnl>0
            else: st+=1; sw+=p.pnl>0
            pos.append(p)
        act=st2
        if len(act)>=1: continue

        sig=None
        if cl<=lo_bb and rsi<RSI_OVERSOLD: sig='BUY'
        elif cl>=up and rsi>RSI_OVERBOUGHT: sig='SELL'
        if sig is None: continue
        sl=round(cl-sd if sig=='BUY' else cl+sd,2)
        if sl<=0: continue
        act.append(type('P',(),{'entry_price':cl,'direction':sig,'sl':sl,'trail_sl':sl,'exit_price':0,'exit_reason':'','pnl':0})())

    for p in act:
        lst=candles[-1]; last=lst['close']
        p.pnl=(last-p.entry_price)*CONTRACT*LOT-COMM if p.direction=='BUY' else (p.entry_price-last)*CONTRACT*LOT-COMM
        p.exit_reason='EXPIRY'; tp+=p.pnl; w+=p.pnl>0; l+=p.pnl<=0
        if p.direction=='BUY': lt+=1; lw+=p.pnl>0
        else: st+=1; sw+=p.pnl>0
        pos.append(p)

    t=w+l; wr=round(w/t*100,1) if t else 0
    return f'{label:22s} {t:>3}笔  \${tp:>8.2f}  {wr:>5.1f}%  (多{lt}笔/{round(lw/lt*100,1) if lt else 0}% 空{st}笔/{round(sw/st*100,1) if st else 0}%)'

# ========== Stoch Bollinger (无MACD过滤, EMA20出场) ==========
def run_stoch(candles, label):
    positions=[]; active=[]; total_pnl=0
    wins=losses=long_wins=long_total=short_wins=short_total=0
    prev_k=prev_d=None
    for i in range(50,len(candles)):
        cu=candles[i]; cl=cu['close']; hi=cu['high']; lo=cu['low']
        cs=[x['close'] for x in candles[:i+1]]
        sma,bw,_=calc_bb(cs,BB_PERIOD,BB_STD); ema20=calc_ema(cs,20)
        if sma is None: continue
        sd=bw*0.35
        stoch_v=calc_stoch(candles[:i+1],STOCH_K,STOCH_SLOWING,STOCH_D)
        if stoch_v is None: continue
        _,k,_,d=stoch_v
        gc=dc=False
        if prev_k is not None and prev_d is not None:
            gc=prev_k<=prev_d and k>d; dc=prev_k>=prev_d and k<d
        prev_k=k; prev_d=d

        closed=[]; still=[]
        for p in active:
            b=p.direction=='BUY'
            if p.sl>0:
                if b and lo<=p.sl: p.exit_price=p.sl; p.exit_reason='SL'; closed.append(p); continue
                if not b and hi>=p.sl: p.exit_price=p.sl; p.exit_reason='SL'; closed.append(p); continue
            if ema20 is not None:
                if b:
                    if ema20>p.trail_sl and ema20<cl: p.trail_sl=ema20; p.sl=ema20
                    if lo<=p.trail_sl: p.exit_price=p.trail_sl; p.exit_reason='EMA20'; closed.append(p); continue
                else:
                    if ema20<p.trail_sl and ema20>cl: p.trail_sl=ema20; p.sl=ema20
                    if hi>=p.trail_sl: p.exit_price=p.trail_sl; p.exit_reason='EMA20'; closed.append(p); continue
            still.append(p)
        for p in closed:
            p.pnl=(p.exit_price-p.entry_price)*CONTRACT*LOT-COMM if p.direction=='BUY' else (p.entry_price-p.exit_price)*CONTRACT*LOT-COMM
            total_pnl+=p.pnl; wins+=p.pnl>0; losses+=p.pnl<=0
            if p.direction=='BUY': long_total+=1; long_wins+=p.pnl>0
            else: short_total+=1; short_wins+=p.pnl>0
            positions.append(p)
        active=still
        if len(active)>=1: continue

        sig=None
        if gc and k<STOCH_OVERSOLD: sig='BUY'
        elif dc and k>STOCH_OVERBOUGHT: sig='SELL'
        if sig is None: continue
        sl=round(cl-sd if sig=='BUY' else cl+sd,2)
        if sl<=0: continue
        active.append(type('P',(),{'entry_price':cl,'direction':sig,'sl':sl,'trail_sl':sl,'exit_price':0,'exit_reason':'','pnl':0})())

    for p in active:
        lst=candles[-1]; last=lst['close']
        p.pnl=(last-p.entry_price)*CONTRACT*LOT-COMM if p.direction=='BUY' else (p.entry_price-last)*CONTRACT*LOT-COMM
        p.exit_reason='EXPIRY'; total_pnl+=p.pnl; wins+=p.pnl>0; losses+=p.pnl<=0
        if p.direction=='BUY': long_total+=1; long_wins+=p.pnl>0
        else: short_total+=1; short_wins+=p.pnl>0
        positions.append(p)

    t=wins+losses; wr=round(wins/t*100,1) if t else 0
    return f'{label:22s} {t:>3}笔  \${total_pnl:>8.2f}  {wr:>5.1f}%  (多{long_total}笔/{round(long_wins/long_total*100,1) if long_total else 0}% 空{short_total}笔/{round(short_wins/short_total*100,1) if short_total else 0}%)'

# ========== Main ==========
m30 = get_candles('M30', limit=2000)
h1 = get_candles('H1', limit=1000)
h4 = get_candles('H4', limit=800)

print('='*75)
print('Stoch Bollinger — 纯周期对比 (无MACD过滤, EMA20出场)')
print('='*75)
print(run_stoch(h1, 'Stoch_H1'))
print(run_stoch(h4, 'Stoch_H4'))

print()
print('='*75)
print('RSI Bollinger — 纯周期对比 (无M30过滤, EMA20出场)')
print('='*75)
print(run_rsi(m30, 'RSIBB_M30'))
print(run_rsi(h1, 'RSIBB_H1'))
