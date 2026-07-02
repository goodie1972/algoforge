"""
M30 RSI v8 回测
═══════════════
5因子阶梯评分:
  ① MA14回归: <MA14->ls+1, >MA14->ss+1
  ② BB通道:  下轨->ls+1, 上轨->ss+1
  ③ RSI值:   <30->+2, 30-50->ls+1, 50-70->ss+1, >70->+2
  ④ RSI交叉(6/13/27): 6>13>27->ls+2, 6>13->ls+1, 6<13->ss+1, 6<13<27->ss+2
  ⑤ DI强弱:  +DI>2x-DI->ls+2, +DI>-DI->ls+1, -DI>+DI->ss+1, -DI>2x+DI->ss+2
进场: ls-ss >= +门槛 做多, <= -门槛 做空 (无DI门禁)
出场: ATR trailing + hard stop
"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.database import init_db, get_conn
from core.bridge import Candle

init_db()
conn = get_conn()
TF_QUERIES = {
    'M30': "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp",
    'M15': "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M15' ORDER BY timestamp",
    'H1':  "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='H1' ORDER BY timestamp",
    'GC_M30': "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='GC_M30' ORDER BY timestamp",
    'GC_M15': "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='GC_M15' ORDER BY timestamp",
    'GC_H1':  "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='GC_H1' ORDER BY timestamp",
}
ALL_DATA = {}
for tf, sql in TF_QUERIES.items():
    rows = conn.execute(sql).fetchall()
    ALL_DATA[tf] = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in rows]
conn.close()

# ── 指标函数 ──
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

def calc_adx(highs, lows, closes, period=14):
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
    atr=[sum(tr_list[:period])/period]
    sp=[sum(pdm[:period])/period]
    sm_=[sum(mdm[:period])/period]
    for j in range(period,len(tr_list)):
        atr.append((atr[-1]*(period-1)+tr_list[j])/period)
        sp.append((sp[-1]*(period-1)+pdm[j])/period)
        sm_.append((sm_[-1]*(period-1)+mdm[j])/period)
    dx_list=[]
    for j in range(len(atr)):
        p=100*sp[j]/atr[j] if atr[j]>0 else 0
        n_=100*sm_[j]/atr[j] if atr[j]>0 else 0
        dx=abs(p-n_)/(p+n_)*100 if(p+n_)>0 else 0
        dx_list.append(dx)
    adx_val=sum(dx_list[:period])/period
    for j in range(period,len(dx_list)):
        adx_val=(adx_val*(period-1)+dx_list[j])/period
    pdi_f=100*sp[-1]/atr[-1] if atr[-1]>0 else 0
    ndi_f=100*sm_[-1]/atr[-1] if atr[-1]>0 else 0
    return {'adx':adx_val,'pdi':pdi_f,'ndi':ndi_f}

COMMISSION=0.5
LOT=0.01

def score_v8(sc, highs, lows, rsi6, rsi13, rsi27, bb, ma14, pdi, ndi, mode='v1', ma_as_trend=False, use_ma=True, use_di=False):
    """5因子评分
    mode='v1': 原始阶梯分 (+1/+2)
    mode='v2': 全部+-2分 (弱信号从+1改为+2)
    mode='v3': 简化版 - MA14方向 + BB碰轨 + RSI极限 + RSI金叉(6/13) + DI(可选)
             所有因子±1, RSI值改用极限(<30/+1, >70/+1), RSI交叉只用6/13
    ma_as_trend: True=MA14做趋势(close>MA14->ls+1), False=做回归(close<MA14->ls+1)
    use_ma: False=去掉MA14因子
    use_di: True=加入DI评分(+DI>-DI->ls+1, -DI>+DI->ss+1)
    """
    if mode == 'v3':
        # ── v3 简化版 ──
        # ① MA14方向
        if use_ma:
            ma_ls = 1 if sc[-1] > ma14 else 0
            ma_ss = 1 if sc[-1] < ma14 else 0
        else:
            ma_ls, ma_ss = 0, 0

        # ② BB碰轨
        bb_ls = 1 if sc[-1] <= bb['lower'] else 0
        bb_ss = 1 if sc[-1] >= bb['upper'] else 0

        # ③ RSI极限 (<30->+1, >70->+1, 中间=0)
        rsi = rsi6
        if rsi is None:
            rsi_ls, rsi_ss = 0, 0
        elif rsi < 30:
            rsi_ls, rsi_ss = 1, 0
        elif rsi > 70:
            rsi_ls, rsi_ss = 0, 1
        else:
            rsi_ls, rsi_ss = 0, 0

        # ④ RSI金叉(6/13) — 只用简单交叉, 不用27
        if rsi6 is None or rsi13 is None:
            cross_ls, cross_ss = 0, 0
        elif rsi6 > rsi13:
            cross_ls, cross_ss = 1, 0
        elif rsi6 < rsi13:
            cross_ls, cross_ss = 0, 1
        else:
            cross_ls, cross_ss = 0, 0

        # ⑤ DI (可选)
        if use_di:
            if pdi > ndi:
                di_ls, di_ss = 1, 0
            elif ndi > pdi:
                di_ls, di_ss = 0, 1
            else:
                di_ls, di_ss = 0, 0
        else:
            di_ls, di_ss = 0, 0

        ls = ma_ls + bb_ls + rsi_ls + cross_ls + di_ls
        ss = ma_ss + bb_ss + rsi_ss + cross_ss + di_ss
        return ls, ss

    # ── v1/v2 原版逻辑 ──
    # ① MA14 (趋势 or 回归)
    """5因子评分
    mode='v1': 原始阶梯分 (+1/+2)
    mode='v2': 全部+-2分 (弱信号从+1改为+2)
    ma_as_trend: True=MA14做趋势(close>MA14->ls+1), False=做回归(close<MA14->ls+1)
    use_ma: False=去掉MA14因子
    """
    # ① MA14 (趋势 or 回归)
    if use_ma:
        if ma_as_trend:
            ma_ls = 1 if sc[-1] > ma14 else 0  # 趋势: 价格>MA14 -> ls+1
            ma_ss = 1 if sc[-1] < ma14 else 0  # 趋势: 价格<MA14 -> ss+1
        else:
            ma_ls = 1 if ma14 < sc[-1] else 0  # 回归: close<MA14 -> ls+1
            ma_ss = 1 if ma14 > sc[-1] else 0  # 回归: close>MA14 -> ss+1
    else:
        ma_ls, ma_ss = 0, 0

    # ② BB
    bb_ls = 1 if sc[-1] <= bb['lower'] else 0
    bb_ss = 1 if sc[-1] >= bb['upper'] else 0

    # ③ RSI值
    rsi = rsi6  # 用6RSI作为RSI值
    if rsi is None:
        rsi_ls, rsi_ss = 0, 0
    elif rsi < 30:
        rsi_ls, rsi_ss = 2, 0
    elif rsi < 50:
        rsi_ls, rsi_ss = 1, 0
    elif rsi < 70:
        rsi_ls, rsi_ss = 0, 1
    else:
        rsi_ls, rsi_ss = 0, 2

    # ④ RSI交叉(6/13/27) — 强优先于弱
    if rsi6 is None or rsi13 is None or rsi27 is None:
        cross_ls, cross_ss = 0, 0
    elif rsi6 > rsi13 > rsi27:
        cross_ls, cross_ss = 2, 0
    elif rsi6 < rsi13 < rsi27:
        cross_ls, cross_ss = 0, 2
    elif rsi6 > rsi13:
        cross_ls, cross_ss = 1, 0
    elif rsi6 < rsi13:
        cross_ls, cross_ss = 0, 1
    else:
        cross_ls, cross_ss = 0, 0

    # ⑤ DI强弱 — 强优先于弱
    if pdi > 2*ndi:
        di_ls, di_ss = 2, 0
    elif ndi > 2*pdi:
        di_ls, di_ss = 0, 2
    elif pdi > ndi:
        di_ls, di_ss = 1, 0
    elif ndi > pdi:
        di_ls, di_ss = 0, 1
    else:
        di_ls, di_ss = 0, 0

    if mode == 'v2':
        # 所有+-1提升为+-2
        ma_ls = 2 if ma_ls else 0
        ma_ss = 2 if ma_ss else 0
        bb_ls = 2 if bb_ls else 0
        bb_ss = 2 if bb_ss else 0
        rsi_ls = 2 if rsi_ls == 1 else rsi_ls
        rsi_ss = 2 if rsi_ss == 1 else rsi_ss
        cross_ls = 2 if cross_ls == 1 else cross_ls
        cross_ss = 2 if cross_ss == 1 else cross_ss
        di_ls = 2 if di_ls == 1 else di_ls
        di_ss = 2 if di_ss == 1 else di_ss

    ls = ma_ls + bb_ls + rsi_ls + cross_ls + di_ls
    ss = ma_ss + bb_ss + rsi_ss + cross_ss + di_ss
    return ls, ss


def run_backtest(candles, mode='v1', trail_atr=1.0, hard_atr=2.0, min_bars=100, entry_threshold=3,
                 ma_as_trend=False, use_ma=True, di_gate=False, use_di=False):
    trades=[]; pos=None; ep=0; ei=0
    trail_h={}; trail_l={}
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
        atr_val=calc_atr(sub,20)
        if atr_val is None: continue
        ma14=sum(sc[-14:])/14 if len(sc)>=14 else None
        if ma14 is None: continue

        # ADX (for +/-DI)
        adx_data=calc_adx(highs,lows,sc,14)
        pdi=adx_data['pdi'] if adx_data else 0
        ndi=adx_data['ndi'] if adx_data else 0

        # RSI多周期
        rsi6=calc_rsi(sc,6)
        rsi13=calc_rsi(sc,13)
        rsi27=calc_rsi(sc,27)

        # 5因子评分
        ls, ss = score_v8(sc, highs, lows, rsi6, rsi13, rsi27, bb, ma14, pdi, ndi, mode,
                          ma_as_trend=ma_as_trend, use_ma=use_ma, use_di=use_di)
        net = ls - ss

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

        # ── DI门禁 (硬拦截, 不是加分) ──
        di_allow_long = True; di_allow_short = True
        if di_gate:
            if pdi > ndi:     # 上升趋势 -> 禁空
                di_allow_short = False
            elif ndi > pdi:   # 下降趋势 -> 禁多
                di_allow_long = False

        # ── Entry (净得分 + DI门禁) ──
        sig=None
        if net >= entry_threshold and di_allow_long: sig='BUY'
        elif net <= -entry_threshold and di_allow_short: sig='SELL'

        if sig and pos is None:
            pos=sig; ep=close; ei=i
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-close)*10*LOT-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'flip'});
            pos=sig; ep=close; ei=i

    if pos:
        pnl=(candles[-1].close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-candles[-1].close)*10*LOT-COMMISSION
        trades.append({'d':pos,'ep':ep,'ex':candles[-1].close,'pnl':pnl,'b':n-1-ei,'exit':'eod'})

    closed=[t for t in trades if t['exit']!='eod']
    if not closed:
        return {'trades':0,'wins':0,'total_pnl':0,'win_rate':0,'pf':0,'max_dd':0,'avg_pnl':0,
                'longs':0,'shorts':0,'long_pnl':0,'short_pnl':0}
    wins=[t for t in closed if t['pnl']>0]
    losses=[t for t in closed if t['pnl']<=0]
    tp=sum(t['pnl'] for t in closed)
    gp=sum(t['pnl'] for t in wins)
    gl=abs(sum(t['pnl'] for t in losses))
    longs=sum(1 for t in closed if t['d']=='BUY')
    shorts=sum(1 for t in closed if t['d']=='SELL')
    long_pnl=sum(t['pnl'] for t in closed if t['d']=='BUY')
    short_pnl=sum(t['pnl'] for t in closed if t['d']=='SELL')
    cum,peak,mdd=0,0,0
    for t in closed:
        cum+=t['pnl']; peak=max(peak,cum); mdd=max(mdd,peak-cum)
    return {
        'trades':len(closed),'wins':len(wins),
        'total_pnl':round(tp,2),'win_rate':round(len(wins)/len(closed)*100,1),
        'pf':round(gp/gl,2) if gl>0 else 0,
        'max_dd':round(mdd,2),'avg_pnl':round(tp/len(closed),2),
        'longs':longs,'shorts':shorts,'long_pnl':round(long_pnl,2),'short_pnl':round(short_pnl,2),
    }


# ═══════════════ Run ═══════════════
print("="*110)
print("  M30 RSI 简化版回测 (0.01 lot)")
print("  因子: MA14方向 + BB碰轨 + RSI极限 + RSI金叉(6/13) +/- DI")
print("  所有因子±1分, ls-ss >=门槛做多 / <=-门槛做空")
print("  Config A: 4因子 门槛±3 无DI")
print("  Config B: 4因子+DI 门槛±4")
print("="*110)
print()

# (name, mode, threshold, ma_as_trend, use_ma, di_gate, use_di)
CONFIGS = [
    ("A: MA14+BB+RSI极+金叉 +-3",  "v3", 3, True, True, False, False),
    ("A: +MA14+BB+RSI极+金叉 +-4",  "v3", 4, True, True, False, False),
    ("B: +DI +-4",                   "v3", 4, True, True, False, True),
    ("B: +DI +-3",                   "v3", 3, True, True, False, True),
    ("B: +DI +-5",                   "v3", 5, True, True, False, True),
]

for label in ['M30', 'M15', 'H1']:
    data = ALL_DATA.get(label)
    if not data:
        continue
    print(f"  ---- {label} ({len(data):,}根K线) ----")
    print(f"  {'配置':<26} {'交易数':>6} {'胜率':>7} {'P/L':>10} {'PF':>7} "
          f"{'DD':>8} {'多':>4} {'空':>4} {'多P/L':>9} {'空P/L':>9}")
    print("  "+"-"*95)
    for cfg in CONFIGS:
        name, mode, thr, ma_trend, use_ma, di_g, use_di = cfg
        r = run_backtest(data, mode=mode, entry_threshold=thr,
                         ma_as_trend=ma_trend, use_ma=use_ma, di_gate=di_g, use_di=use_di)
        m = 'V' if r['total_pnl'] > 0 else 'X'
        print(f"  {name:<26} {r['trades']:>6}  {r['win_rate']:>5.1f}% "
              f"${r['total_pnl']:>+8.2f}  {r['pf']:>5.2f}  "
              f"${r['max_dd']:>6.2f}  {r['longs']:>4} {r['shorts']:>4} "
              f"${r['long_pnl']:>+8.2f} ${r['short_pnl']:>+8.2f}  {m}")
    print()

print("="*110)
print("  双品种对比 (XAUUSD vs GC)")
print("="*110)
for tf in ['M30', 'M15', 'H1']:
    xau = ALL_DATA.get(tf)
    gc_key = 'GC_' + tf
    gc  = ALL_DATA.get(gc_key)
    if not xau or not gc:
        continue
    print()
    print(f"  ---- {tf}: XAUUSD({len(xau):,}) vs {gc_key}({len(gc):,}) ----")
    print(f"  {'配置':<26}  {'XAU P/L':>10}  {'XAU胜率':>8}  {'XAU PF':>7}  | "
          f"{'GC P/L':>10}  {'GC胜率':>8}  {'GC PF':>7}  {'结果'}")
    print("  "+"-"*90)
    for cfg in CONFIGS:
        name, mode, thr, ma_trend, use_ma, di_g, use_di = cfg
        xr = run_backtest(xau, mode=mode, entry_threshold=thr,
                          ma_as_trend=ma_trend, use_ma=use_ma, di_gate=di_g, use_di=use_di)
        gr = run_backtest(gc,  mode=mode, entry_threshold=thr,
                          ma_as_trend=ma_trend, use_ma=use_ma, di_gate=di_g, use_di=use_di)
        both = 'VV' if(xr['total_pnl']>0 and gr['total_pnl']>0) else ('V--' if xr['total_pnl']>0 else ('--V' if gr['total_pnl']>0 else '----'))
        print(f"  {name:<26}  ${xr['total_pnl']:>+8.2f}  {xr['win_rate']:>6.1f}%  "
              f"{xr['pf']:>6.2f}  | ${gr['total_pnl']:>+8.2f}  {gr['win_rate']:>6.1f}%  "
              f"{gr['pf']:>6.2f}  {both}")
    print()
