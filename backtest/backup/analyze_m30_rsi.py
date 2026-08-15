"""
Analyze M30 RSI strategy and test improvements
"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.database import init_db, get_conn
from core.bridge import Candle

init_db()
conn = get_conn()
m30_rows = conn.execute(
    "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
).fetchall()
h1_rows = conn.execute(
    "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='H1' ORDER BY timestamp"
).fetchall()
conn.close()

MC = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in m30_rows]
HC = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in h1_rows]
MP = [c.close for c in MC]
HP = [c.close for c in HC]

def calc_rsi(closes, period=14):
    if len(closes) < period+1: return None
    gains, losses = [], []
    for i in range(1, period+1):
        d = closes[i] - closes[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag = sum(gains)/period; al = sum(losses)/period
    for i in range(period+1, len(closes)):
        d = closes[i] - closes[i-1]
        ag = (ag*(period-1)+max(d,0))/period
        al = (al*(period-1)+max(-d,0))/period
    return 100.0 if al==0 else 100.0-100.0/(1.0+ag/al)

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
    idx = -1
    for j in range(len(HC)-1, -1, -1):
        if int(HC[j].time) <= m30_ts:
            idx = j; break
    if idx < 200: return 'NEUTRAL'
    sub = HP[:idx+1]
    sma200 = sum(sub[-200:])/200
    return 'UP' if sub[-1] > sma200 else 'DOWN'

COMMISSION = 0.5

# ============================================================
# 1) Original RSIBollingerM30 logic
# ============================================================
print("=" * 65)
print("  [原始] M30 RSI+BB: 触轨+RSI极端+L/M30 RSI方向(3-bar)")
print("=" * 65)

trades = []; pos = None; ep = 0; ei = 0
for i in range(60, len(MC)):
    close = MP[i]; sc = MP[:i+1]
    bb = calc_bb(sc); rsi_val = calc_rsi(sc)
    if bb is None or rsi_val is None: continue

    if i >= 19:
        ro = calc_rsi(sc[:-2]); rm = calc_rsi(sc[:-1]); rn = calc_rsi(sc)
        m30d = 'up' if(ro and rm and rn and ro<rm<rn) else 'down' if(ro and rm and rn and ro>rm>rn) else 'flat'
    else: m30d = 'flat'

    sig = None
    if close <= bb['lower'] and rsi_val < 30 and m30d == 'up': sig = 'BUY'
    elif close >= bb['upper'] and rsi_val > 70 and m30d == 'down': sig = 'SELL'

    if sig and pos is None: pos=sig; ep=close; ei=i
    elif sig and sig!=pos and pos:
        pnl = (close-ep)*1.0-COMMISSION if pos=='BUY' else (ep-close)*1.0-COMMISSION
        trades.append({'dir':pos,'entry':ep,'exit':close,'pnl':pnl,'bars':i-ei})
        pos=sig; ep=close; ei=i
if pos:
    pnl = (MP[-1]-ep)*1.0-0.5 if pos=='BUY' else (ep-MP[-1])*1.0-0.5
    trades.append({'dir':pos,'entry':ep,'exit':MP[-1],'pnl':pnl,'bars':len(MC)-1-ei})

closed = trades
if closed:
    tp = sum(t['pnl'] for t in closed)
    w=[t for t in closed if t['pnl']>0]; l=[t for t in closed if t['pnl']<=0]
    print(f"  交易: {len(closed)}  盈亏: ${tp:.2f}  胜率: {len(w)/len(closed)*100:.1f}%")
    if w: print(f"  均赢: ${sum(t['pnl'] for t in w)/len(w):.2f}")
    if l: print(f"  均亏: ${sum(t['pnl'] for t in l)/len(l):.2f}")
else:
    print("  无交易")

# ============================================================
# 2) Improved: ATR trailing exit + H1 trend filter + scoring
# ============================================================
print()
print("=" * 65)
print("  [改进] M30 RSI: 评分制+ATR出场+H1趋势+波动率过滤")
print("=" * 65)

trades2 = []; pos2 = None; ep2 = 0; ei2 = 0
trail_high = {}; trail_low = {}

for i in range(60, len(MC)):
    c = MC[i]; close = c.close; low = c.low; high = c.high
    ts = int(c.time); sc = MP[:i+1]; sca = MC[:i+1]
    bb = calc_bb(sc); rsi_val = calc_rsi(sc); atr_val = calc_atr(sca)
    ema20 = calc_ema(sc, 20)
    if bb is None or rsi_val is None or atr_val is None or ema20 is None: continue
    h1_trend = get_h1_trend_at(ts)
    h1_up = h1_trend=='UP'; h1_down = h1_trend=='DOWN'

    # Vol filter
    vol_recent = sum(MP[max(0,i-9):i+1])/min(10,i+1)
    low_vol = atr_val < vol_recent * 0.025

    # RSI direction (2-bar, more responsive)
    if i >= 19:
        rm = calc_rsi(sc[:-1]); rn = calc_rsi(sc)
        m30d = 'up' if(rm and rn and rm<rn) else 'down' if(rm and rn and rm>rn) else 'flat'
    else: m30d = 'flat'

    # === EXIT (before entry logic) ===
    if pos2 == 'BUY' and ei2 >= 0 and i > ei2 + 4:
        tid = f"{ts}_{ep2}"
        trail_high[tid] = max(trail_high.get(tid, ep2), high)
        trail_stop = trail_high[tid] - atr_val * 3.0
        if close < trail_stop:
            pnl = (close-ep2)*1.0-COMMISSION
            trades2.append({'dir':pos2,'entry':ep2,'exit':close,'pnl':pnl,'bars':i-ei2,'why':'trail'})
            pos2=None; ei2=-1
            # continue to allow immediate reverse
    elif pos2 == 'SELL' and ei2 >= 0 and i > ei2 + 4:
        tid = f"{ts}_{ep2}"
        trail_low[tid] = min(trail_low.get(tid, ep2), low)
        trail_stop = trail_low[tid] + atr_val * 3.0
        if close > trail_stop:
            pnl = (ep2-close)*1.0-COMMISSION
            trades2.append({'dir':pos2,'entry':ep2,'exit':close,'pnl':pnl,'bars':i-ei2,'why':'trail'})
            pos2=None; ei2=-1

    # Hard stop
    if pos2 == 'BUY' and (ep2-close) > atr_val*5.0:
        pnl = (close-ep2)*1.0-COMMISSION
        trades2.append({'dir':pos2,'entry':ep2,'exit':close,'pnl':pnl,'bars':i-ei2,'why':'hard'})
        pos2=None; ei2=-1
    elif pos2 == 'SELL' and (close-ep2) > atr_val*5.0:
        pnl = (ep2-close)*1.0-COMMISSION
        trades2.append({'dir':pos2,'entry':ep2,'exit':close,'pnl':pnl,'bars':i-ei2,'why':'hard'})
        pos2=None; ei2=-1

    # === ENTRY (scoring) ===
    long_score=0; short_score=0
    ld=[]; sd=[]

    if h1_up: long_score+=1; ld.append('TREND+')
    if close <= bb['lower'] and rsi_val < 35:
        long_score += 1; ld.append('BB-RSI')
    if m30d == 'up': long_score+=1; ld.append('RSI-UP')
    if low_vol: long_score+=1; ld.append('LOW-VOL')

    if h1_down:
        if close >= bb['upper'] and rsi_val > 65:
            short_score += 1; sd.append('BB-RSI')
        if m30d == 'down': short_score+=1; sd.append('RSI-DN')
        if low_vol: short_score+=1; sd.append('LOW-VOL')

    sig = None
    if long_score >= 2: sig='BUY'
    elif short_score >= 2: sig='SELL'

    if sig and pos2 is None:
        pos2=sig; ep2=close; ei2=i
    elif sig and sig != pos2 and pos2:
        pnl = (close-ep2)*1.0-COMMISSION if pos2=='BUY' else (ep2-close)*1.0-COMMISSION
        trades2.append({'dir':pos2,'entry':ep2,'exit':close,'pnl':pnl,'bars':i-ei2,'why':'rev'})
        pos2=sig; ep2=close; ei2=i

if pos2:
    pnl = (MP[-1]-ep2)*1.0-0.5 if pos2=='BUY' else (ep2-MP[-1])*1.0-0.5
    trades2.append({'dir':pos2,'entry':ep2,'exit':MP[-1],'pnl':pnl,'bars':len(MC)-1-ei2,'why':'open'})

closed2 = [t for t in trades2]
if closed2:
    tp2 = sum(t['pnl'] for t in closed2)
    w2=[t for t in closed2 if t['pnl']>0]; l2=[t for t in closed2 if t['pnl']<=0]
    print(f"  交易: {len(closed2)}  盈亏: ${tp2:.2f}  胜率: {len(w2)/len(closed2)*100:.1f}%")
    if w2: print(f"  均赢: ${sum(t['pnl'] for t in w2)/len(w2):.2f}")
    if l2: print(f"  均亏: ${sum(t['pnl'] for t in l2)/len(l2):.2f}")
    print(f"  详细:")
    for t in closed2[-15:]:
        m='+' if t['pnl']>0 else '-'
        print(f"    {m} {t['dir']:4s} {t['entry']:>7.2f} -> {t['exit']:>7.2f} ${t['pnl']:>7.2f} [{t['bars']:3d}b] [{t.get('why','')}]")
else:
    print("  无交易")

# ============================================================
# 3) V6-style scoring on M30 with all V6 factors
# ============================================================
print()
print("=" * 65)
print("  [V6-M30] V6评分移植到M30: 多因子+ATR出场")
print("=" * 65)

def calc_sma(closes, p):
    if len(closes)<p: return None
    return sum(closes[-p:])/p

def calc_stoch(candles, kp=9, slowing=3, dp=3):
    n=len(candles)
    if n<kp+slowing+dp+1: return None
    rk=[]
    for j in range(kp-1,n):
        w=candles[j-kp+1:j+1]
        hi=max(x.high for x in w); lo=min(x.low for x in w); cl=w[-1].close
        rk.append(50.0 if hi==lo else (cl-lo)/(hi-lo)*100)
    if len(rk)<slowing+dp+1: return None
    sk=[sum(rk[j-slowing+1:j+1])/slowing for j in range(slowing-1,len(rk))]
    if len(sk)<dp+1: return None
    return {'prev_k':sk[-2],'curr_k':sk[-1],'prev_d':sum(sk[-(dp+1):-1])/dp,'curr_d':sum(sk[-dp:])/dp}

def calc_macd(closes):
    if len(closes)<35: return None
    k12,k26,k9=2.0/13,2.0/27,2.0/10
    e12=closes[0];e26=closes[0];ml=[]
    for p in closes:
        e12=(p-e12)*k12+e12;e26=(p-e26)*k26+e26;ml.append(e12-e26)
    sig=[ml[0]]
    for v in ml[1:]: sig.append((v-sig[-1])*k9+sig[-1])
    return {'hist_values':[ml[j]-sig[j] for j in range(len(ml))]}

def check_bottom_div(hist, lb=10):
    n=len(hist);s=n-lb*2
    if s<1: return False
    lows=[]
    for j in range(s+1,n-1):
        if hist[j]<hist[j-1] and hist[j]<hist[j+1]: lows.append((j,hist[j]))
    return len(lows)>=2 and lows[-1][1]>lows[-2][1]

def check_top_div(hist, lb=10):
    n=len(hist);s=n-lb*2
    if s<1: return False
    highs=[]
    for j in range(s+1,n-1):
        if hist[j]>hist[j-1] and hist[j]>hist[j+1]: highs.append((j,hist[j]))
    return len(highs)>=2 and highs[-1][1]<highs[-2][1]

def calc_keltner(closes, atr_val, period=20, mult=2.5):
    ema20=calc_ema(closes,period)
    if ema20 is None or atr_val is None: return None
    return {'ema':ema20,'upper':ema20+atr_val*mult,'lower':ema20-atr_val*mult}

trades3=[]; pos3=None; ep3=0; ei3=0
trail_h3={}; trail_l3={}

for i in range(250, len(MC)):
    c=MC[i]; close=c.close; low=c.low; high=c.high
    ts=int(c.time); sc=MP[:i+1]; sca=MC[:i+1]

    sma200=calc_sma(sc,200)
    if sma200 is None: continue
    stoch=calc_stoch(sca)
    if stoch is None: continue
    rsi_val=calc_rsi(sc)
    if rsi_val is None: continue
    bb=calc_bb(sc,20,2.5)
    if bb is None: continue
    atr_val=calc_atr(sca,20)
    if atr_val is None: continue
    kc=calc_keltner(sc,atr_val,20,2.5)
    if kc is None: continue

    macd=calc_macd(sc)
    bdiv=check_bottom_div(macd['hist_values'],10) if macd else False
    tdiv=check_top_div(macd['hist_values'],10) if macd else False

    vol_recent=sum(MP[max(0,i-9):i+1])/min(10,i+1)
    low_vol=atr_val<vol_recent*0.02

    # V6 scoring
    ls=0; ss=0
    if close>sma200: ls+=1
    if stoch['curr_k']<30 or stoch['prev_k']<30: ls+=1
    if low<=bb['lower']: ls+=1
    if low<=kc['lower']: ls+=1
    if bdiv: ls+=2
    if rsi_val<30: ls+=1
    if low_vol: ls+=1

    if close<=sma200:
        if stoch['curr_k']>65: ss+=1
        if high>=kc['upper']: ss+=1
        if tdiv: ss+=2
        if rsi_val>70: ss+=1

    sig=None
    if ls>=3: sig='BUY'
    elif ss>=3: sig='SELL'

    # ATR trail exit
    if pos3=='BUY' and i>ei3+4:
        tid=f"{ts}_{ep3}"
        trail_h3[tid]=max(trail_h3.get(tid,ep3),high)
        ts_=trail_h3[tid]-atr_val*3.0
        if close<ts_:
            pnl=(close-ep3)*1.0-COMMISSION
            trades3.append({'dir':pos3,'entry':ep3,'exit':close,'pnl':pnl,'bars':i-ei3,'why':'trail'})
            pos3=None;ei3=-1
    elif pos3=='SELL' and i>ei3+4:
        tid=f"{ts}_{ep3}"
        trail_l3[tid]=min(trail_l3.get(tid,ep3),low)
        ts_=trail_l3[tid]+atr_val*3.0
        if close>ts_:
            pnl=(ep3-close)*1.0-COMMISSION
            trades3.append({'dir':pos3,'entry':ep3,'exit':close,'pnl':pnl,'bars':i-ei3,'why':'trail'})
            pos3=None;ei3=-1

    if pos3=='BUY' and (ep3-close)>atr_val*5.0:
        pnl=(close-ep3)*1.0-COMMISSION
        trades3.append({'dir':pos3,'entry':ep3,'exit':close,'pnl':pnl,'bars':i-ei3,'why':'hard'})
        pos3=None;ei3=-1
    elif pos3=='SELL' and (close-ep3)>atr_val*5.0:
        pnl=(ep3-close)*1.0-COMMISSION
        trades3.append({'dir':pos3,'entry':ep3,'exit':close,'pnl':pnl,'bars':i-ei3,'why':'hard'})
        pos3=None;ei3=-1

    if sig and pos3 is None:
        pos3=sig;ep3=close;ei3=i
    elif sig and sig!=pos3 and pos3:
        pnl=(close-ep3)*1.0-COMMISSION if pos3=='BUY' else (ep3-close)*1.0-COMMISSION
        trades3.append({'dir':pos3,'entry':ep3,'exit':close,'pnl':pnl,'bars':i-ei3,'why':'rev'})
        pos3=sig;ep3=close;ei3=i

if pos3:
    pnl=(MP[-1]-ep3)*1.0-0.5 if pos3=='BUY' else (ep3-MP[-1])*1.0-0.5
    trades3.append({'dir':pos3,'entry':ep3,'exit':MP[-1],'pnl':pnl,'bars':len(MC)-1-ei3,'why':'open'})

closed3=[t for t in trades3]
if closed3:
    tp3=sum(t['pnl'] for t in closed3)
    w3=[t for t in closed3 if t['pnl']>0]; l3=[t for t in closed3 if t['pnl']<=0]
    print(f"  交易: {len(closed3)}  盈亏: ${tp3:.2f}  胜率: {len(w3)/len(closed3)*100:.1f}%")
    if w3: print(f"  均赢: ${sum(t['pnl'] for t in w3)/len(w3):.2f}")
    if l3: print(f"  均亏: ${sum(t['pnl'] for t in l3)/len(l3):.2f}")
    for t in closed3[-15:]:
        m='+' if t['pnl']>0 else '-'
        print(f"    {m} {t['dir']:4s} {t['entry']:>7.2f} -> {t['exit']:>7.2f} ${t['pnl']:>7.2f} [{t['bars']:3d}b] [{t.get('why','')}]")
else:
    print("  无交易")

# ============================================================
print()
print("=" * 65)
print("  分析总结")
print("=" * 65)
print(f"  M30数据: {len(MC)}根K线 ({len(MP)//30//24:.0f}天)")
print()
print("  原始RSI+BB策略问题:")
print("  - 入场条件太严格: BB触轨+RSI极端+3-bar RSI方向")
print("  - RSI反转出场太敏感: 2根K线RSI掉头即平仓")
print("  - 波动大时频繁震仓: 无波动率过滤")
print("  - 局限于M30单一周期: 无大周期趋势判断")
print()
print("  改进方向:")
print("  1. 评分制入场: 多因子打分(趋势/RSI/布林/波动率),≥2分开仓")
print("  2. ATR动态出场: 3倍ATR追踪止损,不再靠RSI掉头判断")
print("  3. H1趋势过滤: 多头只在大周期上升趋势,空头相反")
print("  4. 波动率过滤: 高波动时不开仓,减少震仓")
