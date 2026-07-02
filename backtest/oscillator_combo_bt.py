"""
震荡指标组合策略回测 (RSI + Williams %R + CCI + ADX)
=====================================================
核心逻辑:
  三个超卖/超买指标(RSI, Williams, CCI) 评分系统 ±1
  ADX 判断市场状态:
    ADX < 阈值 → 震荡模式, 双向可做
    ADX > 阈值 → 趋势模式, 只做 DI 方向
  出场: ATR trail + hard stop
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
    'GC_M30': "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='GC_M30' ORDER BY timestamp",
    'GC_M15': "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='GC_M15' ORDER BY timestamp",
    'GC_H1':  "SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='GC_H1' ORDER BY timestamp",
}
ALL_DATA = {}
for tf, sql in TF_QUERIES.items():
    rows = conn.execute(sql).fetchall()
    ALL_DATA[tf] = [Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in rows]
conn.close()

COMMISSION = 0.5
LOT = 0.01

# ═══════════════════ 指标函数 ═══════════════════

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

def calc_williams_r(highs, lows, closes, period=14):
    """Williams %R = -100 × (最高价-收盘价)/(最高价-最低价), 范围-100~0"""
    if len(closes) < period: return None
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh == ll: return -50.0
    return -100.0 * (hh - closes[-1]) / (hh - ll)

def calc_cci(highs, lows, closes, period=20):
    """CCI = (TP - SMA(TP)) / (0.015 × Mean Deviation), TP = (H+L+C)/3"""
    if len(closes) < period+1: return None
    tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(-period, 0)]
    sma = sum(tp) / period
    md = sum(abs(t - sma) for t in tp) / period
    if md == 0: return 0.0
    return (tp[-1] - sma) / (0.015 * md)

def calc_ema(closes, p):
    if len(closes) < p: return None
    k = 2.0/(p+1); e = closes[0]
    for v in closes[1:]: e = (v-e)*k+e
    return e

def calc_atr(candles, p=20):
    if len(candles) < p+2: return None
    tr = []
    for i in range(1, len(candles)):
        h=candles[i].high; l=candles[i].low; pc=candles[i-1].close
        tr.append(max(h-l, abs(h-pc), abs(l-pc)))
    if len(tr) < p: return None
    atr = [sum(tr[:p])/p]
    for i in range(p, len(tr)): atr.append((atr[-1]*(p-1)+tr[i])/p)
    return atr[-1]

def calc_bb(closes, p=20, std_mul=2.0):
    if len(closes) < p+1: return None
    r = closes[-p:]; s = sum(r)/p
    v = sum((c-s)**2 for c in r)/p
    return {'sma': s, 'upper': s+std_mul*math.sqrt(v), 'lower': s-std_mul*math.sqrt(v)}

def calc_adx(highs, lows, closes, period=14):
    n = len(highs)
    if n < period+2: return None
    tr_list, pdm, mdm = [], [], []
    for i in range(1, n):
        h,l,pc = highs[i],lows[i],closes[i-1]
        ph,pl = highs[i-1], lows[i-1]
        tr_list.append(max(h-l, abs(h-pc), abs(l-pc)))
        up = h-ph; down = pl-l
        pdm.append(up if(up>down and up>0) else 0)
        mdm.append(down if(down>up and down>0) else 0)
    if len(tr_list) < period: return None
    atr = [sum(tr_list[:period])/period]
    sp = [sum(pdm[:period])/period]
    sm_ = [sum(mdm[:period])/period]
    for j in range(period, len(tr_list)):
        atr.append((atr[-1]*(period-1)+tr_list[j])/period)
        sp.append((sp[-1]*(period-1)+pdm[j])/period)
        sm_.append((sm_[-1]*(period-1)+mdm[j])/period)
    dx_list = []
    for j in range(len(atr)):
        p = 100*sp[j]/atr[j] if atr[j]>0 else 0
        n_ = 100*sm_[j]/atr[j] if atr[j]>0 else 0
        dx = abs(p-n_)/(p+n_)*100 if(p+n_)>0 else 0
        dx_list.append(dx)
    adx_val = sum(dx_list[:period])/period
    for j in range(period, len(dx_list)):
        adx_val = (adx_val*(period-1)+dx_list[j])/period
    pdi_f = 100*sp[-1]/atr[-1] if atr[-1]>0 else 0
    ndi_f = 100*sm_[-1]/atr[-1] if atr[-1]>0 else 0
    return {'adx': adx_val, 'pdi': pdi_f, 'ndi': ndi_f}

# ═══════════════════ 评分函数 ═══════════════════

def score_triple(rsi, williams, cci, adx_data, close, ma14,
                 rsi_os=30, rsi_ob=70,
                 wil_os=-80, wil_ob=-20,
                 cci_os=-100, cci_ob=100,
                 adx_range=20, adx_trend=25,
                 use_ma14=True, use_bb_filter=False, bb=None):
    """
    三震荡指标评分 + ADX模式判断
    返回: (ls, ss, mode)
      mode: 'range' / 'trend_bull' / 'trend_bear' / 'neutral'
    """
    ls = 0; ss = 0

    # ① RSI
    if rsi is not None:
        if rsi < rsi_os: ls += 1
        elif rsi > rsi_ob: ss += 1

    # ② Williams %R
    if williams is not None:
        if williams < wil_os: ls += 1
        elif williams > wil_ob: ss += 1

    # ③ CCI
    if cci is not None:
        if cci < cci_os: ls += 1
        elif cci > cci_ob: ss += 1

    # ④ MA14 趋势背景
    if use_ma14 and ma14 is not None:
        if close > ma14: ls += 1
        elif close < ma14: ss += 1

    # ⑤ BB 极端附加
    if use_bb_filter and bb is not None:
        if close <= bb['lower']: ls += 1
        elif close >= bb['upper']: ss += 1

    # ADX 模式判断
    mode = 'neutral'
    if adx_data:
        adx_val = adx_data['adx']
        pdi = adx_data['pdi']
        ndi = adx_data['ndi']
        if adx_val < adx_range:
            mode = 'range'
        elif adx_val > adx_trend:
            if pdi > ndi: mode = 'trend_bull'
            elif ndi > pdi: mode = 'trend_bear'
            else: mode = 'neutral'

    return ls, ss, mode

# ═══════════════════ 回测函数 ═══════════════════

def run_backtest(candles, trail_atr=1.0, hard_atr=2.0, min_bars=100,
                 entry_threshold=2, use_ma14=True, use_bb_filter=False,
                 rsi_os=30, rsi_ob=70, wil_os=-80, wil_ob=-20,
                 cci_os=-100, cci_ob=100, adx_range=20, adx_trend=25,
                 require_bb=False, weak_ls=0, weak_ss=0):
    """
    require_bb: 要求BB碰轨才入场 (附加硬条件)
    weak_ls/weak_ss: 弱信号± (例: RSI 30-40给+0.5, 这里不用小数用额外参数)
    """
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
        if ma14 is None and use_ma14: continue

        # ADX
        adx_data=calc_adx(highs, lows, sc, 14)
        if adx_data is None: continue

        # 震荡指标
        rsi_val=calc_rsi(sc, 14)
        williams=calc_williams_r(highs, lows, sc, 14)
        cci_val=calc_cci(highs, lows, sc, 20)

        # Scoring
        ls, ss, mode = score_triple(
            rsi_val, williams, cci_val, adx_data, close, ma14,
            rsi_os=rsi_os, rsi_ob=rsi_ob,
            wil_os=wil_os, wil_ob=wil_ob,
            cci_os=cci_os, cci_ob=cci_ob,
            adx_range=adx_range, adx_trend=adx_trend,
            use_ma14=use_ma14, use_bb_filter=use_bb_filter, bb=bb
        )
        net = ls - ss

        # ── ADX 模式门禁 ──
        allow_long = True; allow_short = True
        if mode == 'trend_bull':
            allow_short = False  # 上升趋势禁空
        elif mode == 'trend_bear':
            allow_long = False   # 下降趋势禁多

        # BB 硬条件
        bb_long_ok = not require_bb or (close <= bb['lower'])
        bb_short_ok = not require_bb or (close >= bb['upper'])

        # ── Exit (同v7) ──
        tid=f"{ts}_{ep}" if pos else ""
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
        if pos=='BUY' and (ep-close)>atr_val*hard_atr:
            pnl=(close-ep)*10*LOT-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'hard'});
            pos=None;ei=-1;continue
        elif pos=='SELL' and (close-ep)>atr_val*hard_atr:
            pnl=(ep-close)*10*LOT-COMMISSION
            trades.append({'d':pos,'ep':ep,'ex':close,'pnl':pnl,'b':i-ei,'exit':'hard'});
            pos=None;ei=-1;continue

        # ── Entry ──
        sig=None
        if net >= entry_threshold and allow_long and bb_long_ok: sig='BUY'
        elif net <= -entry_threshold and allow_short and bb_short_ok: sig='SELL'

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
        return None
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


# ═══════════════════ 参数扫描 ═══════════════════

def sweep(label, base_params, param_name, values, fixed_name=None, fixed_val=None):
    """扫描单个参数, 固定另一个参数"""
    results = []
    for v in values:
        p = dict(base_params)
        p[param_name] = v
        if fixed_name and fixed_val is not None:
            p[fixed_name] = fixed_val
        r = run_backtest(ALL_DATA[label], **p)
        if r:
            results.append((v, r))
        else:
            results.append((v, None))
    return results

def print_results(label, title, results, val_name='参数'):
    """打印扫描结果"""
    print(f"\n  {title}")
    print(f"  {'':->75}")
    print(f"  {val_name:<12} {'交易数':>6} {'胜率':>7} {'P/L':>10} {'PF':>7} {'DD':>8} {'多P/L':>9} {'空P/L':>9}")
    print(f"  {'':->75}")
    for v, r in results:
        if r:
            m = 'V' if r['total_pnl'] > 0 else 'X'
            print(f"  {str(v):<12} {r['trades']:>6}  {r['win_rate']:>5.1f}% "
                  f"${r['total_pnl']:>+8.2f}  {r['pf']:>5.2f}  "
                  f"${r['max_dd']:>6.2f}  "
                  f"${r['long_pnl']:>+8.2f} ${r['short_pnl']:>+8.2f}  {m}")
        else:
            print(f"  {str(v):<12} {'—':>6} {'—':>7} {'—':>10} {'—':>7} {'—':>8} {'—':>9} {'—':>9}")


# ═══════════════════ 运行 ═══════════════════

BASE = dict(
    trail_atr=1.0, hard_atr=2.0, min_bars=100,
    entry_threshold=2, use_ma14=True, use_bb_filter=False,
    rsi_os=30, rsi_ob=70, wil_os=-80, wil_ob=-20,
    cci_os=-100, cci_ob=100, adx_range=20, adx_trend=25,
    require_bb=False,
)

print("="*110)
print("  震荡指标组合策略 — 参数扫描 (0.01 lot)")
print("  3震荡指标: RSI + Williams %R + CCI")
print("  ADX模式: <20震荡/>=25趋势+DI方向")
print("  MA14背景分(可选) + BB碰轨(可选)")
print("="*110)

for label in ['M30', 'M15', 'H1']:
    data = ALL_DATA.get(label)
    if not data:
        continue
    print(f"\n{'#'*80}")
    print(f"  ## {label} ({len(data):,}根K线) — 基线参数")
    print(f"{'#'*80}")

    # 基线
    r = run_backtest(data, **BASE)
    if r:
        m = 'V' if r['total_pnl']>0 else 'X'
        print(f"  基线(thr={BASE['entry_threshold']}, RSI_os={BASE['rsi_os']}, "
              f"Wil={BASE['wil_os']}, CCI={BASE['cci_os']})")
        print(f"  {r['trades']}笔 ${r['total_pnl']} PF={r['pf']} WR={r['win_rate']}% DD=${r['max_dd']} {m}")
    else:
        print("  基线: 无交易")

    # 扫描1: 入场门槛
    print("\n  ── 参数扫描: 入场门槛 ──")
    for thr in [2, 3, 4]:
        r = run_backtest(data, **{**BASE, 'entry_threshold': thr})
        if r:
            m = 'V' if r['total_pnl']>0 else 'X'
            print(f"    thr={thr}: {r['trades']}笔 ${r['total_pnl']} PF={r['pf']} DD=${r['max_dd']} {m}")
        else:
            print(f"    thr={thr}: 无交易")

    # 扫描2: RSI阈值
    print("\n  ── 参数扫描: RSI超卖/超买阈值 ──")
    for os, ob in [(25, 75), (30, 70), (35, 65), (20, 80)]:
        r = run_backtest(data, **{**BASE, 'rsi_os': os, 'rsi_ob': ob})
        if r:
            m = 'V' if r['total_pnl']>0 else 'X'
            print(f"    RSI<{os}/>{ob}: {r['trades']}笔 ${r['total_pnl']} PF={r['pf']} DD=${r['max_dd']} {m}")
        else:
            print(f"    RSI<{os}/>{ob}: 无交易")

    # 扫描3: Williams %R阈值
    print("\n  ── 参数扫描: Williams %R阈值 ──")
    for wil_os, wil_ob in [(-85, -15), (-80, -20), (-75, -25), (-90, -10)]:
        r = run_backtest(data, **{**BASE, 'wil_os': wil_os, 'wil_ob': wil_ob})
        if r:
            m = 'V' if r['total_pnl']>0 else 'X'
            print(f"    Wil<{wil_os}/>{wil_ob}: {r['trades']}笔 ${r['total_pnl']} PF={r['pf']} DD=${r['max_dd']} {m}")
        else:
            print(f"    Wil<{wil_os}/>{wil_ob}: 无交易")

    # 扫描4: CCI阈值
    print("\n  ── 参数扫描: CCI阈值 ──")
    for c_os, c_ob in [(-120, 120), (-100, 100), (-80, 80), (-150, 150)]:
        r = run_backtest(data, **{**BASE, 'cci_os': c_os, 'cci_ob': c_ob})
        if r:
            m = 'V' if r['total_pnl']>0 else 'X'
            print(f"    CCI<{c_os}/>{c_ob}: {r['trades']}笔 ${r['total_pnl']} PF={r['pf']} DD=${r['max_dd']} {m}")
        else:
            print(f"    CCI<{c_os}/>{c_ob}: 无交易")

    # 扫描5: ADX阈值
    print("\n  ── 参数扫描: ADX震荡/趋势阈值 ──")
    for adx_r, adx_t in [(18, 25), (20, 25), (22, 27), (20, 23)]:
        r = run_backtest(data, **{**BASE, 'adx_range': adx_r, 'adx_trend': adx_t})
        if r:
            m = 'V' if r['total_pnl']>0 else 'X'
            print(f"    ADX<{adx_r}/>{adx_t}: {r['trades']}笔 ${r['total_pnl']} PF={r['pf']} DD=${r['max_dd']} {m}")
        else:
            print(f"    ADX<{adx_r}/>{adx_t}: 无交易")

    # 扫描6: 去MA14
    print("\n  ── 参数扫描: 去MA14 + BB附加 ──")
    for use_ma, use_bb in [(True, False), (False, False), (False, True), (True, True)]:
        r = run_backtest(data, **{**BASE, 'use_ma14': use_ma, 'use_bb_filter': use_bb})
        if r:
            m = 'V' if r['total_pnl']>0 else 'X'
            print(f"    MA14={'Y' if use_ma else 'N'} BB={'Y' if use_bb else 'N'}: {r['trades']}笔 ${r['total_pnl']} PF={r['pf']} DD=${r['max_dd']} {m}")
        else:
            print(f"    MA14={'Y' if use_ma else 'N'} BB={'Y' if use_bb else 'N'}: 无交易")

    # 扫描7: require_bb (BB硬条件)
    print("\n  ── 参数扫描: BB硬条件 ──")
    for req_bb in [False, True]:
        r = run_backtest(data, **{**BASE, 'require_bb': req_bb})
        if r:
            m = 'V' if r['total_pnl']>0 else 'X'
            print(f"    require_bb={req_bb}: {r['trades']}笔 ${r['total_pnl']} PF={r['pf']} DD=${r['max_dd']} {m}")
        else:
            print(f"    require_bb={req_bb}: 无交易")

print("\n" + "="*110)
print("  扫描完成")
print("="*110)
