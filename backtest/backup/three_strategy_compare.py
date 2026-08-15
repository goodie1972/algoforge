"""
三策略对比回测: V6v1(当前) vs V6v2(M30硬过滤) vs M30 RSI
使用 SQLite 真实数据，结果同时保存到 dashboard 回测系统
"""
import sys, os, math, json, uuid
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

print(f"M30: {len(MC)} candles ({datetime.fromtimestamp(int(MC[0].time)).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(int(MC[-1].time)).strftime('%Y-%m-%d')})")
print(f"H1:  {len(HC)} candles ({datetime.fromtimestamp(int(HC[0].time)).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(int(HC[-1].time)).strftime('%Y-%m-%d')})")

# === Common indicator functions ===
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

def calc_ema_series(closes, p):
    if len(closes) < p: return None
    k=2.0/(p+1); e=closes[0]; r=[e]
    for v in closes[1:]: e=(v-e)*k+e; r.append(e)
    return r

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
    ema=calc_ema(closes,period)
    if ema is None or atr_val is None: return None
    return {'lower':ema-atr_val*mult, 'upper':ema+atr_val*mult}

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
    sig=[ml[0]]
    for v in ml[1:]: sig.append((v-sig[-1])*k9+sig[-1])
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

# === M30 trend for V6 ===
def calc_m30_trend_at(m30_closes, m30_idx):
    """UP/DOWN/NEUTRAL based on EMA20 slope + SMA50"""
    if m30_idx < 0 or len(m30_closes) < 60:
        return 'NEUTRAL', 0
    sub = m30_closes[:m30_idx+1]
    if len(sub) < 60: return 'NEUTRAL', 0
    ema = calc_ema_series(sub, 20)
    if ema is None or len(ema) < 6: return 'NEUTRAL', 0
    slope = ema[-1] - ema[-6]
    sma50 = calc_sma(sub, 50)
    if sma50 is None: return 'NEUTRAL', 0
    price = sub[-1]
    if slope > 0 and price > sma50: return 'UP', 1
    if slope < 0 and price < sma50: return 'DOWN', -1
    if slope > 0: return 'UP', 1
    if slope < 0: return 'DOWN', -1
    return 'NEUTRAL', 0

def find_m30_at_h1(h1_ts, m30_ts_list):
    lo,hi=0,len(m30_ts_list)-1
    while lo<=hi:
        mid=(lo+hi)//2
        if m30_ts_list[mid]<=h1_ts: lo=mid+1
        else: hi=mid-1
    return hi

m30_ts_list = [int(c.time) for c in MC]

# ================================================================
# V6v1: Current V6 (M30 direction as scoring factor)
# ================================================================
def run_v6v1():
    trades=[]; pos=None; ep=0; ei=0
    trail_h={}; trail_l={}
    for i in range(250, len(HC)):
        c=HC[i]; close=c.close; low=c.low; high=c.high
        sc=HP[:i+1]; sca=HC[:i+1]
        sma200=calc_sma(sc,200)
        if sma200 is None: continue
        stoch=calc_stoch(sca)
        if stoch is None: continue
        rsi_val=calc_rsi(sc)
        if rsi_val is None: continue
        bb=calc_bb(sc)
        if bb is None: continue
        atr_val=calc_atr(sca)
        if atr_val is None: continue
        kc=calc_keltner(sc,atr_val)
        if kc is None: continue
        macd=calc_macd(sc)
        bdiv=check_bottom_div(macd['hist_values']) if macd else False
        tdiv=check_top_div(macd['hist_values']) if macd else False
        vr=sum(HP[max(0,i-9):i+1])/min(10,i+1)
        lv=atr_val<vr*0.02

        # M30 trend (for scoring)
        m30_idx = find_m30_at_h1(int(c.time), m30_ts_list)
        m30_dir, m30_val = calc_m30_trend_at(MP, m30_idx)

        ls=0; ss=0
        if close>sma200: ls+=1
        if stoch['curr_k']<30 or stoch['prev_k']<30: ls+=1
        if low<=bb['lower']: ls+=1
        if low<=kc['lower']: ls+=1
        if bdiv: ls+=2
        if rsi_val<30: ls+=1
        if lv: ls+=1
        if m30_val>0: ls+=1
        elif m30_val<0: ls-=1

        if close<=sma200:
            if stoch['curr_k']>65: ss+=1
            if high>=kc['upper']: ss+=1
            if tdiv: ss+=2
            if rsi_val>70: ss+=1
            if m30_val<0: ss+=1
            elif m30_val>0: ss-=1

        sig=None
        if ls>=3: sig='BUY'
        elif ss>=3: sig='SELL'

        # ATR trail exit
        if pos=='BUY' and i>ei+4:
            th=trail_h.get('h',ep); th=max(th,high); trail_h['h']=th
            if close<th-atr_val*4.0:
                pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and i>ei+4:
            tl=trail_l.get('l',ep); tl=min(tl,low); trail_l['l']=tl
            if close>tl+atr_val*4.0:
                pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        if pos=='BUY' and (ep-close)>atr_val*2.0:
            pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and (close-ep)>atr_val*2.0:
            pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue

        if sig and pos is None: pos=sig; ep=close; ei=i
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*1.0-COMMISSION if pos=='BUY' else (ep-close)*1.0-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=sig; ep=close; ei=i

    if pos:
        pnl=(HP[-1]-ep)*1.0-0.5 if pos=='BUY' else (ep-HP[-1])*1.0-0.5
        trades.append({'d':pos,'ep':ep,'ex':HP[-1],'pnl':pnl,'b':len(HC)-1-ei})

    return trades

# ================================================================
# V6v2: V6 with M30 hard filter (BUY only when M30 UP, SELL only when M30 DOWN)
# ================================================================
def run_v6v2():
    trades=[]; pos=None; ep=0; ei=0
    trail_h={}; trail_l={}
    for i in range(250, len(HC)):
        c=HC[i]; close=c.close; low=c.low; high=c.high
        sc=HP[:i+1]; sca=HC[:i+1]
        sma200=calc_sma(sc,200)
        if sma200 is None: continue
        stoch=calc_stoch(sca)
        if stoch is None: continue
        rsi_val=calc_rsi(sc)
        if rsi_val is None: continue
        bb=calc_bb(sc)
        if bb is None: continue
        atr_val=calc_atr(sca)
        if atr_val is None: continue
        kc=calc_keltner(sc,atr_val)
        if kc is None: continue
        macd=calc_macd(sc)
        bdiv=check_bottom_div(macd['hist_values']) if macd else False
        tdiv=check_top_div(macd['hist_values']) if macd else False
        vr=sum(HP[max(0,i-9):i+1])/min(10,i+1)
        lv=atr_val<vr*0.02

        # M30 trend
        m30_idx = find_m30_at_h1(int(c.time), m30_ts_list)
        m30_dir, _ = calc_m30_trend_at(MP, m30_idx)

        ls=0; ss=0
        if close>sma200: ls+=1
        if stoch['curr_k']<30 or stoch['prev_k']<30: ls+=1
        if low<=bb['lower']: ls+=1
        if low<=kc['lower']: ls+=1
        if bdiv: ls+=2
        if rsi_val<30: ls+=1
        if lv: ls+=1
        if m30_dir=='UP': ls+=1
        elif m30_dir=='DOWN': ls-=1

        if close<=sma200:
            if stoch['curr_k']>65: ss+=1
            if high>=kc['upper']: ss+=1
            if tdiv: ss+=2
            if rsi_val>70: ss+=1
            if m30_dir=='DOWN': ss+=1
            elif m30_dir=='UP': ss-=1

        # KEY DIFFERENCE: M30 hard gate
        sig=None
        if m30_dir=='UP' and ls>=3: sig='BUY'
        elif m30_dir=='DOWN' and ss>=3: sig='SELL'
        # Fallback: no clear M30 direction, use scoring only
        if m30_dir=='NEUTRAL' or m30_dir=='NEUTRAL':
            if ls>=3: sig='BUY'
            elif ss>=3: sig='SELL'

        # ATR trail exit (same as V6v1)
        if pos=='BUY' and i>ei+4:
            th=trail_h.get('h',ep); th=max(th,high); trail_h['h']=th
            if close<th-atr_val*4.0:
                pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and i>ei+4:
            tl=trail_l.get('l',ep); tl=min(tl,low); trail_l['l']=tl
            if close>tl+atr_val*4.0:
                pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        if pos=='BUY' and (ep-close)>atr_val*2.0:
            pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and (close-ep)>atr_val*2.0:
            pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue

        if sig and pos is None: pos=sig; ep=close; ei=i
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*1.0-COMMISSION if pos=='BUY' else (ep-close)*1.0-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=sig; ep=close; ei=i

    if pos:
        pnl=(HP[-1]-ep)*1.0-0.5 if pos=='BUY' else (ep-HP[-1])*1.0-0.5
        trades.append({'d':pos,'ep':ep,'ex':HP[-1],'pnl':pnl,'b':len(HC)-1-ei})

    return trades

# ================================================================
# V6v4: Restrictive Longs — SMA200 hard gate for longs (same as shorts)
#       "让多头管住腿"
# ================================================================
def run_v6v4():
    trades=[]; pos=None; ep=0; ei=0
    trail_h={}; trail_l={}
    for i in range(250, len(HC)):
        c=HC[i]; close=c.close; low=c.low; high=c.high
        sc=HP[:i+1]; sca=HC[:i+1]
        sma200=calc_sma(sc,200)
        if sma200 is None: continue
        stoch=calc_stoch(sca)
        if stoch is None: continue
        rsi_val=calc_rsi(sc)
        if rsi_val is None: continue
        bb=calc_bb(sc)
        if bb is None: continue
        atr_val=calc_atr(sca)
        if atr_val is None: continue
        kc=calc_keltner(sc,atr_val)
        if kc is None: continue
        macd=calc_macd(sc)
        bdiv=check_bottom_div(macd['hist_values']) if macd else False
        tdiv=check_top_div(macd['hist_values']) if macd else False
        vr=sum(HP[max(0,i-9):i+1])/min(10,i+1)
        lv=atr_val<vr*0.02

        m30_idx = find_m30_at_h1(int(c.time), m30_ts_list)
        m30_dir, m30_val = calc_m30_trend_at(MP, m30_idx)

        ls=0; ss=0; sig=None

        # === Long: SMA200 HARD GATE (same as short) ===
        if close > sma200:
            if stoch['curr_k']<30 or stoch['prev_k']<30: ls+=1
            if low<=bb['lower']: ls+=1
            if low<=kc['lower']: ls+=1
            if bdiv: ls+=2
            if rsi_val<30: ls+=1
            if lv: ls+=1
            if m30_val>0: ls+=1
            elif m30_val<0: ls-=1
            if ls>=3: sig='BUY'

        # === Short: unchanged from V6v1 ===
        if close <= sma200:
            if stoch['curr_k']>65: ss+=1
            if high>=kc['upper']: ss+=1
            if tdiv: ss+=2
            if rsi_val>70: ss+=1
            if m30_val<0: ss+=1
            elif m30_val>0: ss-=1
            if ss>=3 and sig is None: sig='SELL'

        # ATR trail exit (same as V6v1)
        if pos=='BUY' and i>ei+4:
            th=trail_h.get('h',ep); th=max(th,high); trail_h['h']=th
            if close<th-atr_val*4.0:
                pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and i>ei+4:
            tl=trail_l.get('l',ep); tl=min(tl,low); trail_l['l']=tl
            if close>tl+atr_val*4.0:
                pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        if pos=='BUY' and (ep-close)>atr_val*2.0:
            pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and (close-ep)>atr_val*2.0:
            pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue

        if sig and pos is None: pos=sig; ep=close; ei=i
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*1.0-COMMISSION if pos=='BUY' else (ep-close)*1.0-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=sig; ep=close; ei=i

    if pos:
        pnl=(HP[-1]-ep)*1.0-0.5 if pos=='BUY' else (ep-HP[-1])*1.0-0.5
        trades.append({'d':pos,'ep':ep,'ex':HP[-1],'pnl':pnl,'b':len(HC)-1-ei})

    return trades

# ================================================================
# V6v5: Trend hard alignment — H1 trend gate (对称, 像M30 RSI那样)
#        Long only when close>SMA200, Short only when close<=SMA200
# ================================================================
def run_v6v5():
    trades=[]; pos=None; ep=0; ei=0
    trail_h={}; trail_l={}
    for i in range(250, len(HC)):
        c=HC[i]; close=c.close; low=c.low; high=c.high
        sc=HP[:i+1]; sca=HC[:i+1]
        sma200=calc_sma(sc,200)
        if sma200 is None: continue
        stoch=calc_stoch(sca)
        if stoch is None: continue
        rsi_val=calc_rsi(sc)
        if rsi_val is None: continue
        bb=calc_bb(sc)
        if bb is None: continue
        atr_val=calc_atr(sca)
        if atr_val is None: continue
        kc=calc_keltner(sc,atr_val)
        if kc is None: continue
        macd=calc_macd(sc)
        bdiv=check_bottom_div(macd['hist_values']) if macd else False
        tdiv=check_top_div(macd['hist_values']) if macd else False
        vr=sum(HP[max(0,i-9):i+1])/min(10,i+1)
        lv=atr_val<vr*0.02
        m30_idx = find_m30_at_h1(int(c.time), m30_ts_list)
        m30_dir, m30_val = calc_m30_trend_at(MP, m30_idx)

        # Trend: symmetric gate — long only above SMA200, short only below
        h1_trend_up = close > sma200
        h1_trend_dn = close < sma200  # not <=, equal = no trade

        ls=0; ss=0; sig=None

        if h1_trend_up:
            if stoch['curr_k']<30 or stoch['prev_k']<30: ls+=1
            if low<=bb['lower']: ls+=1
            if low<=kc['lower']: ls+=1
            if bdiv: ls+=2
            if rsi_val<30: ls+=1
            if lv: ls+=1
            if m30_val>0: ls+=1
            elif m30_val<0: ls-=1
            if ls>=3: sig='BUY'

        if h1_trend_dn:
            if stoch['curr_k']>65: ss+=1
            if high>=kc['upper']: ss+=1
            if tdiv: ss+=2
            if rsi_val>70: ss+=1
            if m30_val<0: ss+=1
            elif m30_val>0: ss-=1
            if ss>=3: sig='SELL'

        # ATR trail exit (same as V6v1)
        if pos=='BUY' and i>ei+4:
            th=trail_h.get('h',ep); th=max(th,high); trail_h['h']=th
            if close<th-atr_val*4.0:
                pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and i>ei+4:
            tl=trail_l.get('l',ep); tl=min(tl,low); trail_l['l']=tl
            if close>tl+atr_val*4.0:
                pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        if pos=='BUY' and (ep-close)>atr_val*2.0:
            pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and (close-ep)>atr_val*2.0:
            pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue

        if sig and pos is None: pos=sig; ep=close; ei=i
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*1.0-COMMISSION if pos=='BUY' else (ep-close)*1.0-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=sig; ep=close; ei=i

    if pos:
        pnl=(HP[-1]-ep)*1.0-0.5 if pos=='BUY' else (ep-HP[-1])*1.0-0.5
        trades.append({'d':pos,'ep':ep,'ex':HP[-1],'pnl':pnl,'b':len(HC)-1-ei})

    return trades

# ================================================================
# V6v6: De-weighted mean reversion — remove BB/KC touch signals
# ================================================================
def run_v6v6():
    trades=[]; pos=None; ep=0; ei=0
    trail_h={}; trail_l={}
    for i in range(250, len(HC)):
        c=HC[i]; close=c.close; low=c.low; high=c.high
        sc=HP[:i+1]; sca=HC[:i+1]
        sma200=calc_sma(sc,200)
        if sma200 is None: continue
        stoch=calc_stoch(sca)
        if stoch is None: continue
        rsi_val=calc_rsi(sc)
        if rsi_val is None: continue
        atr_val=calc_atr(sca)
        if atr_val is None: continue
        macd=calc_macd(sc)
        bdiv=check_bottom_div(macd['hist_values']) if macd else False
        tdiv=check_top_div(macd['hist_values']) if macd else False
        vr=sum(HP[max(0,i-9):i+1])/min(10,i+1)
        lv=atr_val<vr*0.02
        m30_idx = find_m30_at_h1(int(c.time), m30_ts_list)
        m30_dir, m30_val = calc_m30_trend_at(MP, m30_idx)

        ls=0; ss=0
        if close>sma200: ls+=1

        # KDJ and RSI only (removed BB/KC touch for longs)
        if stoch['curr_k']<30 or stoch['prev_k']<30: ls+=1
        if bdiv: ls+=2
        if rsi_val<30: ls+=1
        if lv: ls+=1
        if m30_val>0: ls+=1
        elif m30_val<0: ls-=1

        # Short (same reduction: no KC upper)
        if close<=sma200:
            if stoch['curr_k']>65: ss+=1
            if tdiv: ss+=2
            if rsi_val>70: ss+=1
            if m30_val<0: ss+=1
            elif m30_val>0: ss-=1

        sig=None
        if ls>=3: sig='BUY'
        elif ss>=3: sig='SELL'

        # ATR trail exit (same as V6v1)
        if pos=='BUY' and i>ei+4:
            th=trail_h.get('h',ep); th=max(th,high); trail_h['h']=th
            if close<th-atr_val*4.0:
                pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and i>ei+4:
            tl=trail_l.get('l',ep); tl=min(tl,low); trail_l['l']=tl
            if close>tl+atr_val*4.0:
                pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        if pos=='BUY' and (ep-close)>atr_val*2.0:
            pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and (close-ep)>atr_val*2.0:
            pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue

        if sig and pos is None: pos=sig; ep=close; ei=i
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*1.0-COMMISSION if pos=='BUY' else (ep-close)*1.0-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=sig; ep=close; ei=i

    if pos:
        pnl=(HP[-1]-ep)*1.0-0.5 if pos=='BUY' else (ep-HP[-1])*1.0-0.5
        trades.append({'d':pos,'ep':ep,'ex':HP[-1],'pnl':pnl,'b':len(HC)-1-ei})

    return trades

# ================================================================
# V6v3: Balanced scoring — remove SMA200 hard gate, add BB upper
# ================================================================
def run_v6v3():
    trades=[]; pos=None; ep=0; ei=0
    trail_h={}; trail_l={}
    for i in range(250, len(HC)):
        c=HC[i]; close=c.close; low=c.low; high=c.high
        sc=HP[:i+1]; sca=HC[:i+1]
        sma200=calc_sma(sc,200)
        if sma200 is None: continue
        stoch=calc_stoch(sca)
        if stoch is None: continue
        rsi_val=calc_rsi(sc)
        if rsi_val is None: continue
        bb=calc_bb(sc)
        if bb is None: continue
        atr_val=calc_atr(sca)
        if atr_val is None: continue
        kc=calc_keltner(sc,atr_val)
        if kc is None: continue
        macd=calc_macd(sc)
        bdiv=check_bottom_div(macd['hist_values']) if macd else False
        tdiv=check_top_div(macd['hist_values']) if macd else False
        vr=sum(HP[max(0,i-9):i+1])/min(10,i+1)
        lv=atr_val<vr*0.02

        m30_idx = find_m30_at_h1(int(c.time), m30_ts_list)
        m30_dir, m30_val = calc_m30_trend_at(MP, m30_idx)

        # === Symmetric long/short scoring ===
        ls=0; ss=0

        # ① Trend (both sides)
        if close>sma200: ls+=1
        elif close<sma200: ss+=1

        # ② KDJ extremes
        if stoch['curr_k']<30 or stoch['prev_k']<30: ls+=1
        if stoch['curr_k']>65: ss+=1

        # ③ Bollinger touch (BOTH sides)
        if low<=bb['lower']: ls+=1
        if high>=bb['upper']: ss+=1     # <-- ADDED

        # ④ Keltner touch (BOTH sides)
        if low<=kc['lower']: ls+=1
        if high>=kc['upper']: ss+=1

        # ⑤ MACD divergence
        if bdiv: ls+=2
        if tdiv: ss+=2

        # ⑥ RSI extremes
        if rsi_val<30: ls+=1
        if rsi_val>70: ss+=1

        # ⑦ Low volatility (bullish only)
        if lv: ls+=1

        # ⑧ M30 direction
        if m30_val>0: ls+=1
        elif m30_val<0: ls-=1
        if m30_val<0: ss+=1
        elif m30_val>0: ss-=1

        sig=None
        if ls>=3: sig='BUY'
        elif ss>=3: sig='SELL'

        # ATR trail exit (same as V6v1)
        if pos=='BUY' and i>ei+4:
            th=trail_h.get('h',ep); th=max(th,high); trail_h['h']=th
            if close<th-atr_val*4.0:
                pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and i>ei+4:
            tl=trail_l.get('l',ep); tl=min(tl,low); trail_l['l']=tl
            if close>tl+atr_val*4.0:
                pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        if pos=='BUY' and (ep-close)>atr_val*2.0:
            pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and (close-ep)>atr_val*2.0:
            pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue

        if sig and pos is None: pos=sig; ep=close; ei=i
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*1.0-COMMISSION if pos=='BUY' else (ep-close)*1.0-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=sig; ep=close; ei=i

    if pos:
        pnl=(HP[-1]-ep)*1.0-0.5 if pos=='BUY' else (ep-HP[-1])*1.0-0.5
        trades.append({'d':pos,'ep':ep,'ex':HP[-1],'pnl':pnl,'b':len(HC)-1-ei})

    return trades

# ================================================================
# M30 RSI: current live strategy
# ================================================================
def run_m30rsi():
    def get_h1_trend_at(m30_ts):
        idx=-1
        for j in range(len(HC)-1,-1,-1):
            if int(HC[j].time) <= m30_ts: idx=j; break
        if idx<200: return 'NEUTRAL'
        sub=HP[:idx+1]; sma200=sum(sub[-200:])/200
        return 'UP' if sub[-1]>sma200 else 'DOWN'

    trades=[]; pos=None; ep=0; ei=0
    trail_h={}; trail_l={}
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
        if pos=='BUY' and i>ei+4:
            th=trail_h.get('h',ep); th=max(th,high); trail_h['h']=th
            if close<th-atr_val*4.0:
                pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and i>ei+4:
            tl=trail_l.get('l',ep); tl=min(tl,low); trail_l['l']=tl
            if close>tl+atr_val*4.0:
                pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        if pos=='BUY' and (ep-close)>atr_val*3.0:
            pnl=(close-ep)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue
        elif pos=='SELL' and (close-ep)>atr_val*3.0:
            pnl=(ep-close)*1.0-COMMISSION; trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=None; ei=-1;continue

        sig=None
        if ls>=3 and h1_trend=='UP': sig='BUY'
        elif ss>=3 and h1_trend=='DOWN': sig='SELL'

        if sig and pos is None: pos=sig; ep=close; ei=i
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*1.0-COMMISSION if pos=='BUY' else (ep-close)*1.0-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei}); pos=sig; ep=close; ei=i

    if pos:
        pnl=(MP[-1]-ep)*1.0-0.5 if pos=='BUY' else (ep-MP[-1])*1.0-0.5
        trades.append({'d':pos,'ep':ep,'ex':MP[-1],'pnl':pnl,'b':len(MC)-1-ei})

    return trades


# ================================================================
# Run all three
# ================================================================
print()
print("="*75)
print("  三策略对比回测")
print("="*75)

results = {}
for name, fn, label in [
    ("V6v1", run_v6v1, "V6 H1 (当前-M30评分)"),
    ("V6v2", run_v6v2, "V6 H1 (优化-M30硬过滤)"),
    ("V6v4", run_v6v4, "V6 H1 (管住腿-SMA闸门)"),
    ("V6v5", run_v6v5, "V6 H1 (趋势硬对齐-对称闸门)"),
    ("V6v6", run_v6v6, "V6 H1 (减逆势-BB/KC去除)"),
    ("V6v3", run_v6v3, "V6 H1 (平衡-去SMA闸门+BB上轨)"),
    ("M30_RSI", run_m30rsi, "M30 RSI+BB"),
]:
    trades = fn()
    closed = [t for t in trades]
    if not closed:
        results[name] = {"trades": 0, "pnl": 0, "wr": 0, "avg_w": 0, "avg_l": 0, "best": 0, "worst": 0}
        print(f"\n  [{label}]")
        print(f"  无交易")
        continue

    tp = sum(t['pnl'] for t in closed)
    w=[t for t in closed if t['pnl']>0]; l=[t for t in closed if t['pnl']<=0]
    aw=sum(t['pnl'] for t in w)/len(w) if w else 0
    al=sum(t['pnl'] for t in l)/len(l) if l else 0
    bt=max(t['pnl'] for t in w) if w else 0
    wt=min(t['pnl'] for t in l) if l else 0
    wr=len(w)/len(closed)*100

    results[name] = {
        "trades": len(closed), "pnl": round(tp,2), "wr": round(wr,1),
        "avg_w": round(aw,2), "avg_l": round(al,2),
        "best": round(bt,2), "worst": round(wt,2),
        "sample_trades": closed[-5:],
    }

    print(f"\n  [{label}]")
    print(f"  交易: {len(closed)}  盈亏: ${tp:.2f}  胜率: {wr:.1f}%")
    print(f"  均盈: ${aw:.2f}  均亏: ${al:.2f}  最好: ${bt:.2f}  最差: ${wt:.2f}")
    print(f"  最近几笔:")
    for t in closed[-5:]:
        m='+' if t['pnl']>0 else '-'
        print(f"    {m} {t['d']:4s} ${t['ep']:>7.2f} -> ${t['ex']:>7.2f} ${t['pnl']:>7.2f} [{t['b']:3d}b]")

# === Comparison Table ===
print()
print("="*75)
print("  对比总表")
print("="*75)
print(f"{'策略':<25} {'交易':>6} {'盈亏':>10} {'胜率':>7} {'均盈':>7} {'均亏':>7} {'最好':>8} {'最差':>8}")
print("-"*75)
for name, r in results.items():
    print(f"{name:<25} {r['trades']:>6} ${r['pnl']:>8.2f} {r['wr']:>6.1f}% ${r['avg_w']:>6.2f} ${r['avg_l']:>6.2f} ${r['best']:>7.2f} ${r['worst']:>7.2f}")

# V6v3 vs V6v1 comparison (printed after detail is populated)


# Save to file
output = {
    "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    "comparison": {
        name: {k:v for k,v in r.items() if k != 'sample_trades'}
        for name, r in results.items()
    },
    "detail": {}
}
for name, fn in [("V6v1", run_v6v1), ("V6v2", run_v6v2), ("V6v4", run_v6v4), ("V6v5", run_v6v5), ("V6v6", run_v6v6), ("V6v3", run_v6v3), ("M30_RSI", run_m30rsi)]:
    trades = fn()
    output["detail"][name] = [{"d":t['d'],"entry":t['ep'],"exit":t['ex'],"pnl":t['pnl'],"bars":t['b']} for t in trades]

with open("backtest/three_strategy_compare.json", "w") as f:
    json.dump(output, f, indent=2)
print(f"\n  结果已保存到 backtest/three_strategy_compare.json")

# V6v3 and V6v4 direction breakdown & comparison
if 'V6v1' in results and 'V6v3' in results:
    v1, v3 = results['V6v1'], results['V6v3']
    d1 = output["detail"]["V6v1"]; d3 = output["detail"]["V6v3"]
    b1=sum(1 for t in d1 if t['d']=='BUY'); s1=sum(1 for t in d1 if t['d']=='SELL')
    b3=sum(1 for t in d3 if t['d']=='BUY'); s3=sum(1 for t in d3 if t['d']=='SELL')
    print()
    print(f"  [V6v3 平衡版 vs V6v1 当前版]")
    print(f"  PnL: ${v1['pnl']:+.2f} → ${v3['pnl']:+.2f} (${v3['pnl']-v1['pnl']:+.2f})")
    print(f"  方向 {b1}/{s1} ({b1/(s1 or 1):.1f}:1) → {b3}/{s3} ({b3/(s3 or 1):.1f}:1)")

if 'V6v1' in results and 'V6v4' in results:
    v1, v4 = results['V6v1'], results['V6v4']
    d4 = output["detail"]["V6v4"]
    b4=sum(1 for t in d4 if t['d']=='BUY'); s4=sum(1 for t in d4 if t['d']=='SELL')
    print()
    print(f"  [V6v4 管住腿 vs V6v1 当前版]")
    print(f"  PnL: ${v1['pnl']:+.2f} → ${v4['pnl']:+.2f} (${v4['pnl']-v1['pnl']:+.2f})")
    print(f"  胜率: {v1['wr']}% → {v4['wr']}%")
    print(f"  交易数: {v1['trades']} → {v4['trades']}")
    print(f"  方向 {b4}/{s4} ({b4/(s4 or 1):.1f}:1)")

# ================================================================
# Also save to dashboard backtest jobs (so it shows in UI history)
# ================================================================
try:
    # Load dashboard backtest module and inject result
    dashboard_jobs_path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "backend", "routes", "backtest.py")
    if os.path.exists(dashboard_jobs_path):
        # Read the in-memory _jobs dict by importing the module
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from dashboard.backend.routes import backtest as bt_module
        job_id = "compare_" + uuid.uuid4().hex[:8]
        summary = {
            "total_return": sum(r['pnl'] for r in results.values()),
            "total_return_pct": 0,
            "total_trades": sum(r['trades'] for r in results.values()),
            "win_rate": sum(r['wr'] for r in results.values())/len(results),
            "max_drawdown": 0,
            "trades": [],
            "by_strategy": {},
        }
        for name, r in results.items():
            summary["by_strategy"][name] = {
                "total_pnl": r['pnl'],
                "total_trades": r['trades'],
                "win_rate": r['wr'],
            }
        with bt_module._lock:
            bt_module._jobs[job_id] = {
                "job_id": job_id,
                "status": "completed",
                "params": {
                    "strategies": list(results.keys()),
                    "timeframe": "multi",
                    "start_date": "2024-01-01",
                    "end_date": "2026-06-06",
                },
                "result": summary,
                "created_at": datetime.now().isoformat(),
                "completed_at": datetime.now().isoformat(),
                "progress": "完成(CLI) - 三策略对比",
            }
        print(f"  结果已注入 dashboard 回测系统 job_id={job_id}")
except Exception as e:
    print(f"  保存到 dashboard 失败(非关键): {e}")
