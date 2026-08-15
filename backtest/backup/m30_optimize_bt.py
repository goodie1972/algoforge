"""
M30 v7 优化 — 增加交易频率 + 出场优化
=========================================
v7 exact M30: 17笔 $19.84 PF=1.64 (好但太少)
目标: 增加交易笔数到30-50笔, 保持PF>1.5

测试:
  A) 出场优化 (宽止损)
  B) RSI分级加权 (<20→+2,20-30→+1,>70→+2,65-70→+1)
  C) RSI方向 + RSI分级(去掉RSI极限)
  D) threshold=2 + RSI方向(仅做确认,不评分)
"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.database import init_db, get_conn
from core.bridge import Candle

init_db(); conn = get_conn()
rows = conn.execute("SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp").fetchall()
conn.close()
candles = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in rows]
COMMISSION = 0.5; LOT = 0.01

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

def run_custom(candles, score_fn, thr=3, trail=1.0, hard=2.0):
    """Generic runner with custom scoring function"""
    trades=[]; pos=None; ep=0; ei=0
    trail_h, trail_l = {}, {}
    n=len(candles)
    for i in range(100, n):
        c=candles[i]; close=c.close; low=c.low; high=c.high; ts=int(c.time)
        sub=candles[:i+1]; sc=[x.close for x in sub]; highs=[x.high for x in sub]; lows=[x.low for x in sub]
        bb=calc_bb(sc); atr_val=calc_atr(sub)
        if bb is None or atr_val is None: continue
        ma14=sum(sc[-14:])/14 if len(sc)>=14 else None
        if ma14 is None: continue
        rsi_val=calc_rsi(sc); rsi_prev=calc_rsi(sc[:-1])
        if rsi_val is None: continue
        trend = 'UP' if close > ma14 else 'DOWN'
        rsi_dir = 'up' if (rsi_prev is not None and rsi_prev < rsi_val) else ('down' if (rsi_prev is not None and rsi_prev > rsi_val) else 'flat')

        ls, ss = score_fn(close, ma14, bb, rsi_val, rsi_dir, trend)
        net = ls - ss

        # Exit
        tid = f"{ts}_{ep}" if pos else ""
        if pos and i > ei+4:
            is_buy = pos == 'BUY'
            if is_buy:
                trail_h[tid]=max(trail_h.get(tid,ep), high)
                if close < trail_h[tid]-atr_val*trail:
                    pnl=(close-ep)*10*LOT-COMMISSION; trades.append({'d':pos,'pnl':pnl,'exit':'trail'}); pos=None; ei=-1; continue
                if (ep-close)>atr_val*hard:
                    pnl=(close-ep)*10*LOT-COMMISSION; trades.append({'d':pos,'pnl':pnl,'exit':'hard'}); pos=None; ei=-1; continue
            else:
                trail_l[tid]=min(trail_l.get(tid,ep), low)
                if close > trail_l[tid]+atr_val*trail:
                    pnl=(ep-close)*10*LOT-COMMISSION; trades.append({'d':pos,'pnl':pnl,'exit':'trail'}); pos=None; ei=-1; continue
                if (close-ep)>atr_val*hard:
                    pnl=(ep-close)*10*LOT-COMMISSION; trades.append({'d':pos,'pnl':pnl,'exit':'hard'}); pos=None; ei=-1; continue

        # Entry
        sig=None
        if net >= thr: sig='BUY'
        elif net <= -thr:
            if rsi_val < 20: sig=None
            elif rsi_val < 30:
                if (net+1) <= -thr: sig='SELL'
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
            'long_pnl':round(long_pnl,2),'short_pnl':round(short_pnl,2),
            'avg_win':round(gp/len(wins),2) if wins else 0,
            'avg_loss':round(gl/len(losses),2) if losses else 0}

def p(res, tag=''):
    if not res: print(f"    {tag}: 无交易"); return
    m='V' if res['total_pnl']>0 else 'X'
    print(f"    {tag}: {res['trades']}笔 ${res['total_pnl']} PF={res['pf']} WR={res['win_rate']}% "
          f"DD=${res['max_dd']} avgW=${res['avg_win']} avgL=${res['avg_loss']} "
          f"多${res['long_pnl']} 空${res['short_pnl']} {m}")

# ═══════ 评分函数定义 ═══════

def score_v7_exact(close, ma14, bb, rsi_val, rsi_dir, trend):
    """v7 exact: 4因子±1, threshold=3"""
    ls, ss = 0, 0
    if trend == 'UP': ls+=1; ss+=0
    else: ls+=0; ss+=1
    if close <= bb['lower']: ls+=1
    if close >= bb['upper']: ss+=1
    if rsi_val < 30: ls+=1
    if rsi_val > 65: ss+=1
    if rsi_dir == 'up': ls+=1
    elif rsi_dir == 'down': ss+=1
    return ls, ss

def score_rsi_tiered(close, ma14, bb, rsi_val, rsi_dir, trend):
    """RSI分级: <20→+2,20-30→+1,>70→+2,65-70→+1"""
    ls, ss = 0, 0
    if trend == 'UP': ls+=1
    else: ss+=1
    if close <= bb['lower']: ls+=1
    if close >= bb['upper']: ss+=1
    if rsi_val < 20: ls+=2
    elif rsi_val < 30: ls+=1
    if rsi_val > 70: ss+=2
    elif rsi_val > 65: ss+=1
    if rsi_dir == 'up': ls+=1
    elif rsi_dir == 'down': ss+=1
    return ls, ss

def score_rsi_tiered_no_dir(close, ma14, bb, rsi_val, rsi_dir, trend):
    """RSI分级 + MA14 + BB (无RSI方向)"""
    ls, ss = 0, 0
    if trend == 'UP': ls+=1
    else: ss+=1
    if close <= bb['lower']: ls+=1
    if close >= bb['upper']: ss+=1
    if rsi_val < 20: ls+=2
    elif rsi_val < 30: ls+=1
    if rsi_val > 70: ss+=2
    elif rsi_val > 65: ss+=1
    return ls, ss

def score_rsi_plus_dir(close, ma14, bb, rsi_val, rsi_dir, trend):
    """RSI±1 + MA14±1 + RSI方向±1 (无BB)"""
    ls, ss = 0, 0
    if trend == 'UP': ls+=1
    else: ss+=1
    if rsi_val < 30: ls+=1
    if rsi_val > 65: ss+=1
    if rsi_dir == 'up': ls+=1
    elif rsi_dir == 'down': ss+=1
    return ls, ss

def score_bb_rsi(close, ma14, bb, rsi_val, rsi_dir, trend):
    """BB±1 + RSI分级±2 (无MA14, 无RSI方向)"""
    ls, ss = 0, 0
    if close <= bb['lower']: ls+=1
    if close >= bb['upper']: ss+=1
    if rsi_val < 20: ls+=2
    elif rsi_val < 30: ls+=1
    if rsi_val > 70: ss+=2
    elif rsi_val > 65: ss+=1
    return ls, ss

# ═══════ 运行 ═══════

print("="*110)
print("  M30 v7优化 — 增加交易频率 + 出场优化 (0.01 lot)")
print(f"  M30数据: {len(candles):,}根K线")
print("="*110)

# 基线
print("\n  ── 基线: v7 exact ──")
for thr in [2, 3, 4]:
    res = run_custom(candles, score_v7_exact, thr=thr)
    p(res, f"thr={thr}")
for tr, hd in [(1.0, 2.0), (1.5, 2.0), (2.0, 3.0), (1.5, 3.0)]:
    res = run_custom(candles, score_v7_exact, thr=3, trail=tr, hard=hd)
    p(res, f"thr=3 trail={tr} hard={hd}")

# A: RSI分级
print("\n  ── A: RSI分级 (<20→+2, 20-30→+1, >70→+2, 65-70→+1) ──")
for thr in [2, 3, 4]:
    res = run_custom(candles, score_rsi_tiered, thr=thr)
    p(res, f"thr={thr}")
for tr, hd in [(1.5, 3.0), (2.0, 3.0)]:
    res = run_custom(candles, score_rsi_tiered, thr=2, trail=tr, hard=hd)
    p(res, f"thr=2 trail={tr} hard={hd}")

# B: RSI分级 + 无RSI方向
print("\n  ── B: RSI分级 + MA14 + BB (无RSI方向) ──")
for thr in [2, 3]:
    res = run_custom(candles, score_rsi_tiered_no_dir, thr=thr)
    p(res, f"thr={thr}")

# C: RSI+MA14+RSI方向 (无BB)
print("\n  ── C: RSI+MA14+RSI方向 (无BB) ──")
for thr in [2, 3]:
    res = run_custom(candles, score_rsi_plus_dir, thr=thr)
    p(res, f"thr={thr}")

# D: 仅BB+RSI分级 (无MA14)
print("\n  ── D: BB碰轨 + RSI分级 (无MA14) ──")
for thr in [2]:
    res = run_custom(candles, score_bb_rsi, thr=thr)
    p(res, f"thr={thr}")

# E: v7 exact + hold-only (无trail, 仅hard)
print("\n  ── E: v7 exact 各种出场 ──")
for tr, hd in [(1.0, 2.0), (1.0, 3.0), (1.5, 3.0), (2.0, 3.0), (3.0, 4.0), (999, 999)]:
    res = run_custom(candles, score_v7_exact, thr=3, trail=tr, hard=hd)
    if hd == 999:
        p(res, f"仅flip出场(无止损)")
    else:
        p(res, f"trail={tr} hard={hd}")

print("\n" + "="*110)
print("  完成")
print("="*110)
