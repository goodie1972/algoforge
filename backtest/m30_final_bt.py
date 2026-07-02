"""
M30 最终优化 — RSI分级评分 + 出场精细调优
============================================
基线: RSI分级 (<20→+2, 20-30→+1, >70→+2, 65-70→+1)
      + MA14(±1) + BB(±1) + RSI方向(±1)
      无RSI方向变体 thr=2: 35笔 $8.69 PF=1.18

目标: 找最佳参数组合
"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.database import init_db, get_conn
from core.bridge import Candle

init_db(); conn = get_conn()
rows = conn.execute("SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp").fetchall()
conn.close()
candles = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in rows]
COMMISSION = 0.5; LOT = 0.01; n = len(candles)
print(f"M30: {n:,}根K线\n")

def calc_rsi(closes, p=14):
    if len(closes) < p+1: return None
    g,l=[],[]
    for i in range(1,p+1): d=closes[i]-closes[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g)/p; al=sum(l)/p
    for i in range(p+1,len(closes)): d=closes[i]-closes[i-1]; ag=(ag*(p-1)+max(d,0))/p; al=(al*(p-1)+max(-d,0))/p
    return 100.0 if al==0 else 100.0-100.0/(1.0+ag/al)

def calc_bb(closes, p=20, s=2.0):
    if len(closes) < p+1: return None
    r=closes[-p:]; sm=sum(r)/p; v=sum((c-sm)**2 for c in r)/p
    return {'sma':sm,'upper':sm+s*math.sqrt(v),'lower':sm-s*math.sqrt(v)}

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

def run(thr, trail, hard, min_bars=100,
        rsi_os=30, rsi_ob=65, rsi_deep_os=20, rsi_deep_ob=70,
        use_ma14=True, use_bb=True, use_rsi_dir=True,
        profit_drawdown=0.25, max_hold=9999):
    """RSI分级评分 + 可选因子 + 出场组合"""
    trades=[]; pos=None; ep=0; ei=0; trail_h, trail_l = {}, {}
    for i in range(min_bars, n):
        c=candles[i]; close=c.close; low=c.low; high=c.high; ts=int(c.time)
        sub=candles[:i+1]; sc=[x.close for x in sub]
        bb=calc_bb(sc); atr_val=calc_atr(sub)
        if bb is None or atr_val is None: continue
        ma14=sum(sc[-14:])/14
        rsi_val=calc_rsi(sc); rsi_prev=calc_rsi(sc[:-1])
        if rsi_val is None: continue
        trend='UP' if close>ma14 else 'DOWN'
        rsi_dir='up' if(rsi_prev is not None and rsi_prev<rsi_val)else('down' if(rsi_prev is not None and rsi_prev>rsi_val)else'flat')

        ls, ss = 0, 0
        if use_ma14:
            if trend=='UP': ls+=1
            else: ss+=1
        if use_bb:
            if close<=bb['lower']: ls+=1
            if close>=bb['upper']: ss+=1
        # RSI分级
        if rsi_val<rsi_deep_os: ls+=2
        elif rsi_val<rsi_os: ls+=1
        if rsi_val>rsi_deep_ob: ss+=2
        elif rsi_val>rsi_ob: ss+=1
        if use_rsi_dir:
            if rsi_dir=='up': ls+=1
            elif rsi_dir=='down': ss+=1

        net = ls - ss

        # Exit (with profit drawdown)
        tid=f"{ts}_{ep}" if pos else ""
        if pos and i>ei+4:
            is_buy=pos=='BUY'
            if is_buy:
                trail_h[tid]=max(trail_h.get(tid,ep),high)
                # profit drawdown
                if profit_drawdown>0 and (close-ep)>atr_val*0.5:
                    peak=trail_h[tid]; drawdown=peak-close
                    if drawdown>0 and drawdown/(peak-ep+0.01)>profit_drawdown:
                        pnl=(close-ep)*10*LOT-COMMISSION; trades.append({'d':pos,'pnl':pnl,'exit':'pdd'}); pos=None; ei=-1; continue
                if close<trail_h[tid]-atr_val*trail:
                    pnl=(close-ep)*10*LOT-COMMISSION; trades.append({'d':pos,'pnl':pnl,'exit':'trail'}); pos=None; ei=-1; continue
                if (ep-close)>atr_val*hard:
                    pnl=(close-ep)*10*LOT-COMMISSION; trades.append({'d':pos,'pnl':pnl,'exit':'hard'}); pos=None; ei=-1; continue
            else:
                trail_l[tid]=min(trail_l.get(tid,ep),low)
                if profit_drawdown>0 and (ep-close)>atr_val*0.5:
                    peak_diff=close-trail_l[tid]; drawdown=ep-close
                    if peak_diff>0 and drawdown/(peak_diff+0.01)>profit_drawdown:
                        pnl=(ep-close)*10*LOT-COMMISSION; trades.append({'d':pos,'pnl':pnl,'exit':'pdd'}); pos=None; ei=-1; continue
                if close>trail_l[tid]+atr_val*trail:
                    pnl=(ep-close)*10*LOT-COMMISSION; trades.append({'d':pos,'pnl':pnl,'exit':'trail'}); pos=None; ei=-1; continue
                if (close-ep)>atr_val*hard:
                    pnl=(ep-close)*10*LOT-COMMISSION; trades.append({'d':pos,'pnl':pnl,'exit':'hard'}); pos=None; ei=-1; continue
            if i-ei>max_hold:
                pnl=(close-ep)*10*LOT-COMMISSION if is_buy else (ep-close)*10*LOT-COMMISSION
                trades.append({'d':pos,'pnl':pnl,'exit':'maxhold'}); pos=None; ei=-1; continue

        # Entry
        sig=None
        if net>=thr: sig='BUY'
        elif net<=-thr:
            if rsi_val<20: sig=None
            elif rsi_val<30:
                if (net+1)<=-thr: sig='SELL'
            else: sig='SELL'

        if sig and pos is None: pos=sig; ep=close; ei=i
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-close)*10*LOT-COMMISSION
            trades.append({'d':pos,'pnl':pnl,'exit':'flip'}); pos=sig; ep=close; ei=i

    if pos:
        pnl=(candles[-1].close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-candles[-1].close)*10*LOT-COMMISSION
        trades.append({'d':pos,'pnl':pnl,'exit':'eod'})
    closed=[t for t in trades if t['exit']!='eod']
    if not closed: return None
    wins=[t for t in closed if t['pnl']>0]; losses=[t for t in closed if t['pnl']<=0]
    tp=sum(t['pnl'] for t in closed); gp=sum(t['pnl'] for t in wins); gl=abs(sum(t['pnl'] for t in losses))
    longs=sum(1 for t in closed if t['d']=='BUY'); shorts=sum(1 for t in closed if t['d']=='SELL')
    long_pnl=sum(t['pnl'] for t in closed if t['d']=='BUY'); short_pnl=sum(t['pnl'] for t in closed if t['d']=='SELL')
    cum,peak,mdd=0,0,0
    for t in closed: cum+=t['pnl']; peak=max(peak,cum); mdd=max(mdd,peak-cum)
    return {'trades':len(closed),'wins':len(wins),'total_pnl':round(tp,2),
            'win_rate':round(len(wins)/len(closed)*100,1),'pf':round(gp/gl,2) if gl>0 else 0,
            'max_dd':round(mdd,2),'longs':longs,'shorts':shorts,
            'long_pnl':round(long_pnl,2),'short_pnl':round(short_pnl,2)}

def p(res, tag=''):
    if not res: print(f"    {tag}: -\t无交易"); return
    m='V' if res['total_pnl']>0 else 'X'
    print(f"    {tag}: {res['trades']:>3}笔 ${res['total_pnl']:>+7.2f} PF={res['pf']:.2f} WR={res['win_rate']:.0f}% DD=${res['max_dd']:.1f} 多${res['long_pnl']:+.1f} 空${res['short_pnl']:+.1f} {m}")

# ════════ 配置定义 ════════
CONFIGS = [
    # (name, dict)
]

print("  ── 1: 基线 v7 exact ──")
p(run(thr=3, trail=1.0, hard=2.0, use_ma14=True, use_bb=True, use_rsi_dir=True, rsi_os=30, rsi_ob=65, rsi_deep_os=20, rsi_deep_ob=70, profit_drawdown=0), "v7 exact thr=3")

print("\n  ── 2: RSI分级 因子组合 ──")
for thr in [2, 3]:
    p(run(thr=thr, trail=1.0, hard=2.0, rsi_os=30, rsi_ob=65, rsi_deep_os=20, rsi_deep_ob=70, use_rsi_dir=True, profit_drawdown=0), f"全因子 thr={thr}")
    p(run(thr=thr, trail=1.0, hard=2.0, rsi_os=30, rsi_ob=65, rsi_deep_os=20, rsi_deep_ob=70, use_rsi_dir=False, profit_drawdown=0), f"去RSI方向 thr={thr}")
    # 只MA14+RSI
    p(run(thr=thr, trail=1.0, hard=2.0, rsi_os=30, rsi_ob=65, rsi_deep_os=20, rsi_deep_ob=70, use_ma14=True, use_bb=False, use_rsi_dir=False, profit_drawdown=0), f"仅MA14+RSI thr={thr}")
    # 只BB+RSI
    p(run(thr=thr, trail=1.0, hard=2.0, rsi_os=30, rsi_ob=65, rsi_deep_os=20, rsi_deep_ob=70, use_ma14=False, use_bb=True, use_rsi_dir=False, profit_drawdown=0), f"仅BB+RSI thr={thr}")

print("\n  ── 3: 出场精细调优 (全因子 thr=2) ──")
for tr, hd in [(1.0,2.0), (1.0,3.0), (1.5,2.0), (1.5,3.0), (2.0,3.0), (2.0,4.0), (3.0,5.0)]:
    p(run(thr=2, trail=tr, hard=hd, profit_drawdown=0), f"trail={tr} hard={hd}")
# Profit drawdown variants
for pdd in [0.15, 0.25, 0.35]:
    p(run(thr=2, trail=1.0, hard=2.0, profit_drawdown=pdd), f"trail=1 hard=2 pdd={pdd}")

print("\n  ── 4: 去RSI方向 出场调优 (thr=2) ──")
for tr, hd in [(1.0,2.0), (1.5,2.0), (1.5,3.0), (2.0,3.0), (3.0,5.0)]:
    p(run(thr=2, trail=tr, hard=hd, use_rsi_dir=False, profit_drawdown=0), f"trail={tr} hard={hd}")

print("\n  ── 5: 仅MA14+RSI 出场调优 (thr=2) ──")
for tr, hd in [(1.0,2.0), (1.5,3.0), (2.0,3.0)]:
    p(run(thr=2, trail=tr, hard=hd, use_ma14=True, use_bb=False, use_rsi_dir=False, profit_drawdown=0), f"trail={tr} hard={hd}")

print("\n  ── 6: RSI阈值变体 (全因子 thr=2, trail=1.5 hard=3.0) ──")
for os, ob, dos, dob in [(30,65,20,70), (25,70,15,80), (35,60,25,75), (20,70,10,80)]:
    p(run(thr=2, trail=1.5, hard=3.0, rsi_os=os, rsi_ob=ob, rsi_deep_os=dos, rsi_deep_ob=dob, profit_drawdown=0),
      f"RSI<{os}/{ob} deep<{dos}/{dob}")

print("\n  ── 7: 最佳配置验证 ──")
# 从上面选最好的几个配置
best = [
    (2, 1.5, 3.0, True, True, True, 30, 65, 20, 70, 0, "全因子 trail=1.5 hard=3"),
    (2, 2.0, 3.0, True, True, True, 30, 65, 20, 70, 0, "全因子 trail=2 hard=3"),
    (2, 1.5, 3.0, True, True, False, 30, 65, 20, 70, 0, "去RSI方向 trail=1.5 hard=3"),
    (2, 2.0, 3.0, True, False, False, 30, 65, 20, 70, 0, "仅MA14+RSI trail=2 hard=3"),
    (2, 1.5, 3.0, True, False, False, 30, 65, 20, 70, 0, "仅MA14+RSI trail=1.5 hard=3"),
    (2, 1.5, 3.0, True, True, True, 25, 70, 15, 80, 0, "RSI<25/70 deep<15/80"),
]
for cfg in best:
    thr, tr, hd, ma, bb, rd, os, ob, dos, dob, pdd, tag = cfg
    p(run(thr=thr, trail=tr, hard=hd, use_ma14=ma, use_bb=bb, use_rsi_dir=rd,
          rsi_os=os, rsi_ob=ob, rsi_deep_os=dos, rsi_deep_ob=dob, profit_drawdown=pdd), tag)

print("\n完成")
