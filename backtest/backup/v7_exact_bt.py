"""
v7 策略 4因子评分回测 — 精确复制 v7 逻辑
=========================================
评分: MA14(±1) + BB碰轨(±1) + RSI极限(±1) + RSI方向(±1), threshold=3
出场: profit_drawdown + ATR trail + hard, trend-aware multipliers
"""
import sys, os, math, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.database import init_db, get_conn
from core.bridge import Candle

init_db()
conn = get_conn()
TF_QUERIES = {
    'M30': "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp",
    'M15': "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M15' ORDER BY timestamp",
    'H1':  "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='H1' ORDER BY timestamp",
}
ALL_DATA = {}
for tf, sql in TF_QUERIES.items():
    rows = conn.execute(sql).fetchall()
    ALL_DATA[tf] = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in rows]
conn.close()

COMMISSION = 0.5
LOT = 0.01

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

def calc_bb(closes, p=20, std_mul=2.0):
    if len(closes) < p+1: return None
    r=closes[-p:]; s=sum(r)/p; v=sum((c-s)**2 for c in r)/p
    return {'sma':s,'upper':s+std_mul*math.sqrt(v),'lower':s-std_mul*math.sqrt(v)}

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

def calc_sma(closes, p):
    if len(closes) < p: return None
    return sum(closes[-p:])/p

def get_exit_mult(is_buy, trend):
    if trend == 'UP':
        return (1.5, 3.0) if is_buy else (1.0, 2.0)
    elif trend == 'DOWN':
        return (1.0, 2.0) if is_buy else (1.5, 3.0)
    else:
        return (1.2, 2.5)

def run_v7_bt(candles, min_bars=100, score_threshold=3,
              profit_drawdown_pct=0.25, use_exit=True):
    """精确复制 v7 逻辑"""
    trades=[]; pos=None; ep=0; ei=0
    trail_h, trail_l = {}, {}
    # 盈利平仓冷却
    last_profit_exit = {"BUY": 0.0, "SELL": 0.0}
    cooldown = 1800  # 30分钟

    n=len(candles)

    for i in range(min_bars, n):
        c=candles[i]; close=c.close; low=c.low; high=c.high
        ts=int(c.time)
        sub=candles[:i+1]
        sc=[x.close for x in sub]
        highs=[x.high for x in sub]
        lows=[x.low for x in sub]

        bb=calc_bb(sc,20,2.0)
        if bb is None: continue
        atr_val=calc_atr(sub,20)
        if atr_val is None: continue
        ma14=calc_sma(sc,14)
        if ma14 is None: continue

        rsi_val=calc_rsi(sc,14)
        if rsi_val is None: continue

        # RSI方向: 比较最后两根完整K线的RSI
        rsi_prev = calc_rsi(sc[:-1], 14)
        rsi_dir = 'flat'
        if rsi_prev is not None:
            if rsi_prev < rsi_val: rsi_dir = 'up'
            elif rsi_prev > rsi_val: rsi_dir = 'down'

        # 趋势
        trend = 'UP' if close > ma14 else 'DOWN'

        # ── v7 4因子评分 ──
        long_score, short_score = 0, 0

        # ① MA14趋势
        if trend == 'UP': long_score += 1
        else: short_score += 1

        # ② BB碰轨
        if close <= bb['lower']: long_score += 1
        if close >= bb['upper']: short_score += 1

        # ③ RSI极限
        if rsi_val < 30: long_score += 1
        if rsi_val > 65: short_score += 1

        # ④ RSI方向
        if rsi_dir == 'up': long_score += 1
        elif rsi_dir == 'down': short_score += 1

        # ── Exit (v7 logic) ──
        tid = f"{ts}_{ep}" if pos else ""
        if pos and use_exit and i > ei + 4:
            is_buy = pos == 'BUY'
            trail_mult, hard_mult = get_exit_mult(is_buy, trend)

            if is_buy:
                trail_h[tid] = max(trail_h.get(tid, ep), high)
                current_profit = close - ep
                loss = ep - close
                peak_profit = max(0, current_profit)

                if current_profit > 0:
                    # 利润回撤止盈 (25%)
                    if peak_profit > atr_val * 0.5:
                        profit_ratio = current_profit / peak_profit
                        if profit_ratio < (1 - profit_drawdown_pct):
                            pnl = (close-ep)*10*LOT-COMMISSION
                            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'pdd'})
                            last_profit_exit['BUY'] = ts
                            pos=None; ei=-1; continue
                    # ATR trail
                    drawdown = trail_h[tid] - close
                    if drawdown > atr_val * trail_mult:
                        pnl = (close-ep)*10*LOT-COMMISSION
                        trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'trail'})
                        last_profit_exit['BUY'] = ts
                        pos=None; ei=-1; continue
                else:
                    # 硬止损
                    if loss > atr_val * hard_mult:
                        pnl = (close-ep)*10*LOT-COMMISSION
                        trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'hard'})
                        pos=None; ei=-1; continue
            else:  # SELL
                trail_l[tid] = min(trail_l.get(tid, ep), low)
                current_profit = ep - close
                loss = close - ep
                peak_profit = max(0, current_profit)

                if current_profit > 0:
                    if peak_profit > atr_val * 0.5:
                        profit_ratio = current_profit / peak_profit
                        if profit_ratio < (1 - profit_drawdown_pct):
                            pnl = (ep-close)*10*LOT-COMMISSION
                            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'pdd'})
                            last_profit_exit['SELL'] = ts
                            pos=None; ei=-1; continue
                    rally = close - trail_l[tid]
                    if rally > atr_val * trail_mult:
                        pnl = (ep-close)*10*LOT-COMMISSION
                        trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'trail'})
                        last_profit_exit['SELL'] = ts
                        pos=None; ei=-1; continue
                else:
                    if loss > atr_val * hard_mult:
                        pnl = (ep-close)*10*LOT-COMMISSION
                        trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'hard'})
                        pos=None; ei=-1; continue

        # ── Entry ──
        # 盈利平仓冷却
        if long_score >= score_threshold:
            remaining = cooldown - (ts - last_profit_exit.get("BUY", 0))
            if remaining > 0: long_score = 0
        if short_score >= score_threshold:
            remaining = cooldown - (ts - last_profit_exit.get("SELL", 0))
            if remaining > 0: short_score = 0

        sig = None
        if long_score >= score_threshold:
            sig = 'BUY'
        elif short_score >= score_threshold:
            # RSI空头限制
            if rsi_val < 20:
                sig = None  # 完全禁空
            elif rsi_val < 30:
                short_score -= 1
                if short_score >= score_threshold:
                    sig = 'SELL'
            else:
                sig = 'SELL'

        if sig and pos is None:
            pos=sig; ep=close; ei=i
        elif sig and sig!=pos and pos:
            pnl=(close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-close)*10*LOT-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'flip'})
            pos=sig; ep=close; ei=i

    if pos:
        pnl=(candles[-1].close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-candles[-1].close)*10*LOT-COMMISSION
        trades.append({'d':pos,'ep':ep,'ex':candles[-1].close,'pnl':pnl,'b':n-1-ei,'exit':'eod'})

    closed=[t for t in trades if t['exit']!='eod']
    if not closed: return None
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
    avg_win=round(gp/len(wins),2) if wins else 0
    avg_loss=round(gl/len(losses),2) if losses else 0
    exit_stats={}
    for e in ['trail','hard','pdd','flip']:
        n_exit=sum(1 for t in closed if t['exit']==e)
        if n_exit: exit_stats[e]=n_exit
    return {
        'trades':len(closed),'wins':len(wins),'total_pnl':round(tp,2),
        'win_rate':round(len(wins)/len(closed)*100,1),
        'pf':round(gp/gl,2) if gl>0 else 0,
        'max_dd':round(mdd,2),'avg_pnl':round(tp/len(closed),2),
        'longs':longs,'shorts':shorts,'long_pnl':round(long_pnl,2),'short_pnl':round(short_pnl,2),
        'avg_win':avg_win,'avg_loss':avg_loss,'exits':exit_stats,
    }

def p(res, tag=''):
    if res is None:
        print(f"    {tag}: 无交易")
        return
    m='V' if res['total_pnl']>0 else 'X'
    exits_str = ' '.join(f"{k}={v}" for k,v in res.get('exits',{}).items())
    avg_w = res.get('avg_win', 0)
    avg_l = res.get('avg_loss', 0)
    print(f"    {tag}: {res['trades']}笔 ${res['total_pnl']} PF={res['pf']} "
          f"WR={res['win_rate']}% DD=${res['max_dd']} "
          f"avgW=${avg_w} avgL=${avg_l} "
          f"多${res['long_pnl']} 空${res['short_pnl']} [{exits_str}] {m}")

# ═════════ 运行 ═════════
print("="*120)
print("  v7 4因子评分回测 — 精确复制 v7 逻辑 (0.01 lot)")
print("  评分: MA14(±1)+BB碰轨(±1)+RSI极限(±1)+RSI方向(±1), threshold=3")
print("  出场: profit_drawdown(25%) + ATR trail + hard, trend-aware")
print("="*120)

for label in ['M30', 'M15', 'H1']:
    data = ALL_DATA.get(label)
    if not data: continue
    print(f"\n{'#'*80}")
    print(f"  ## {label} ({len(data):,}根K线)")
    print(f"{'#'*80}")

    # 基线: v7 exact
    res = run_v7_bt(data)
    p(res, "v7 exact")

    # 阈值扫描
    for thr in [2, 3, 4]:
        res = run_v7_bt(data, score_threshold=thr)
        p(res, f"thr={thr}")

    # 出场组合
    res = run_v7_bt(data, use_exit=False)
    p(res, "无出场(仅硬止)")

    # 不同利润回撤
    for pct in [0.15, 0.25, 0.35, 0.50]:
        res = run_v7_bt(data, profit_drawdown_pct=pct)
        p(res, f"pdd={pct}")

    # 不同RSI极限阈值
    # 改为: RSI极限 <25/>70
    def run_v7_mod(candles, rsi_os=30, rsi_ob=65, **kw):
        """Modified v7 with custom RSI thresholds"""
        # 直接修改内部逻辑困难, 重新跑
        return run_v7_bt(candles, **kw)

    # 测试不同RSI极限值 和 评分权重
    # 方案1: RSI<25 / >70
    # 方案2: RSI<20 => ls+2, RSI 20-30 => ls+1, RSI<20禁空
    # 方案3: RSI(+2) + BB(+1) + MA14(+1), thr=3 (v2的B/C, 相当于去掉了RSI方向)

    print("\n  ── 变体测试 ──")

    # 变体A: 去掉RSI方向 (4因子→3因子)
    def run_v7_norsidir(candles, thr=3):
        trades=[]; pos=None; ep=0; ei=0
        trail_h, trail_l = {}, {}
        last_profit_exit = {"BUY": 0.0, "SELL": 0.0}
        cooldown = 1800
        n=len(candles)
        for i in range(100, n):
            c=candles[i]; close=c.close; low=c.low; high=c.high
            ts=int(c.time)
            sub=candles[:i+1]; sc=[x.close for x in sub]
            highs=[x.high for x in sub]; lows=[x.low for x in sub]
            bb=calc_bb(sc,20,2.0)
            if bb is None: continue
            atr_val=calc_atr(sub,20)
            if atr_val is None: continue
            ma14=calc_sma(sc,14)
            if ma14 is None: continue
            rsi_val=calc_rsi(sc,14)
            if rsi_val is None: continue
            trend = 'UP' if close > ma14 else 'DOWN'

            ls, ss = 0, 0
            if trend == 'UP': ls+=1
            else: ss+=1
            if close <= bb['lower']: ls+=1
            if close >= bb['upper']: ss+=1
            if rsi_val < 30: ls+=1
            if rsi_val > 65: ss+=1

            tid = f"{ts}_{ep}" if pos else ""
            if pos and i > ei+4:
                is_buy = pos == 'BUY'
                tm, hm = get_exit_mult(is_buy, trend)
                if is_buy:
                    trail_h[tid] = max(trail_h.get(tid,ep), high)
                    if close < trail_h[tid]-atr_val*tm:
                        pnl = (close-ep)*10*LOT-COMMISSION
                        trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'trail'})
                        pos=None; ei=-1; continue
                    if (ep-close)>atr_val*hm:
                        pnl = (close-ep)*10*LOT-COMMISSION
                        trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'hard'})
                        pos=None; ei=-1; continue
                else:
                    trail_l[tid] = min(trail_l.get(tid,ep), low)
                    if close > trail_l[tid]+atr_val*tm:
                        pnl = (ep-close)*10*LOT-COMMISSION
                        trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'trail'})
                        pos=None; ei=-1; continue
                    if (close-ep)>atr_val*hm:
                        pnl = (ep-close)*10*LOT-COMMISSION
                        trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'hard'})
                        pos=None; ei=-1; continue

            sig = None
            if ls >= thr: sig = 'BUY'
            elif ss >= thr:
                if rsi_val < 20: sig = None
                elif rsi_val < 30:
                    ss -= 1
                    if ss >= thr: sig = 'SELL'
                else: sig = 'SELL'
            if sig and pos is None:
                pos=sig; ep=close; ei=i
            elif sig and sig!=pos and pos:
                pnl=(close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-close)*10*LOT-COMMISSION
                trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'flip'})
                pos=sig; ep=close; ei=i
        if pos:
            pnl=(candles[-1].close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-candles[-1].close)*10*LOT-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':candles[-1].close,'pnl':pnl,'b':n-1-ei,'exit':'eod'})
        closed=[t for t in trades if t['exit']!='eod']
        if not closed: return None
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
        return {'trades':len(closed),'wins':len(wins),'total_pnl':round(tp,2),
                'win_rate':round(len(wins)/len(closed)*100,1),'pf':round(gp/gl,2) if gl>0 else 0,
                'max_dd':round(mdd,2),'longs':longs,'shorts':shorts,
                'long_pnl':round(long_pnl,2),'short_pnl':round(short_pnl,2),
                'avg_win':round(gp/len(wins),2) if wins else 0,
                'avg_loss':round(gl/len(losses),2) if losses else 0}

    res = run_v7_norsidir(data, 3)
    p(res, "去RSI方向 thr=3")
    res = run_v7_norsidir(data, 2)
    p(res, "去RSI方向 thr=2")

    # 变体B: RSI加权 (RSI<20→+2, RSI>70→+2)
    def run_v7_rsi2(candles, thr=3):
        trades=[]; pos=None; ep=0; ei=0
        trail_h, trail_l = {}, {}
        last_profit_exit = {"BUY": 0.0, "SELL": 0.0}
        cooldown = 1800
        n=len(candles)
        for i in range(100, n):
            c=candles[i]; close=c.close; low=c.low; high=c.high
            ts=int(c.time)
            sub=candles[:i+1]; sc=[x.close for x in sub]
            highs=[x.high for x in sub]; lows=[x.low for x in sub]
            bb=calc_bb(sc,20,2.0)
            if bb is None: continue
            atr_val=calc_atr(sub,20)
            if atr_val is None: continue
            ma14=calc_sma(sc,14)
            if ma14 is None: continue
            rsi_val=calc_rsi(sc,14)
            if rsi_val is None: continue
            trend = 'UP' if close > ma14 else 'DOWN'

            ls, ss = 0, 0
            if trend == 'UP': ls+=1
            else: ss+=1
            if close <= bb['lower']: ls+=1
            if close >= bb['upper']: ss+=1
            # RSI tiered: <20→+2, 20-30→+1, >70→+2, 65-70→+1
            if rsi_val < 20: ls+=2
            elif rsi_val < 30: ls+=1
            if rsi_val > 70: ss+=2
            elif rsi_val > 65: ss+=1

            tid = f"{ts}_{ep}" if pos else ""
            if pos and i > ei+4:
                is_buy = pos == 'BUY'
                tm, hm = get_exit_mult(is_buy, trend)
                if is_buy:
                    trail_h[tid] = max(trail_h.get(tid,ep), high)
                    if close < trail_h[tid]-atr_val*tm:
                        pnl = (close-ep)*10*LOT-COMMISSION
                        trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'trail'})
                        pos=None; ei=-1; continue
                    if (ep-close)>atr_val*hm:
                        pnl = (close-ep)*10*LOT-COMMISSION
                        trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'hard'})
                        pos=None; ei=-1; continue
                else:
                    trail_l[tid] = min(trail_l.get(tid,ep), low)
                    if close > trail_l[tid]+atr_val*tm:
                        pnl = (ep-close)*10*LOT-COMMISSION
                        trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'trail'})
                        pos=None; ei=-1; continue
                    if (close-ep)>atr_val*hm:
                        pnl = (ep-close)*10*LOT-COMMISSION
                        trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'hard'})
                        pos=None; ei=-1; continue

            sig = None
            net = ls - ss
            if net >= thr: sig = 'BUY'
            elif net <= -thr:
                if rsi_val < 20: sig = None
                elif rsi_val < 30: sig = 'SELL' if (net + 1) <= -thr else None
                else: sig = 'SELL'
            if sig and pos is None:
                pos=sig; ep=close; ei=i
            elif sig and sig!=pos and pos:
                pnl=(close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-close)*10*LOT-COMMISSION
                trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'flip'})
                pos=sig; ep=close; ei=i
        if pos:
            pnl=(candles[-1].close-ep)*10*LOT-COMMISSION if pos=='BUY' else (ep-candles[-1].close)*10*LOT-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':candles[-1].close,'pnl':pnl,'b':n-1-ei,'exit':'eod'})
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
    for thr in [2, 3, 4]:
        res = run_v7_rsi2(data, thr)
        p(res, f"RSI分级(20->2,70->2) thr={thr}")

print("\n" + "="*120)
print("  完成")
print("="*120)
