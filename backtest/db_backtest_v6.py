"""
数据库 V6 Hybrid 全量回测 (高效版)
===================================
预计算所有指标, 逐根 K 线回测, 所有端口偏移 +100
用法: python backtest/db_backtest_v6.py
"""

import logging, math, os, sys, time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stdout)

# 端口偏移 +100
import config.settings as _settings
_settings.FREEMT4_PORT = 23332  # 原 23232 + 100

from data.database import get_conn
from core.bridge import Candle, OrderType

COMMISSION = 0.5; LOT = 0.01; CONTRACT = 100
ATR_PERIOD = 20; BB_PERIOD = 20; BB_STD = 2.5
KC_MULT = 2.5; STOCH_K = 9; STOCH_S = 3; STOCH_D = 3
DIV_LOOK = 10; MIN_BARS = 250
TRAIL_ATR = 4.0; HARD_ATR = 2.0

conn = get_conn()
h1 = conn.execute("SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='H1' ORDER BY timestamp").fetchall()
m30 = conn.execute("SELECT timestamp,open,high,low,close,volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp").fetchall()
conn.close()

H1 = [Candle(time=str(r[0]),open=r[1],high=r[2],low=r[3],close=r[4],volume=r[5]) for r in h1]
M30 = [Candle(time=str(r[0]),open=r[1],high=r[2],low=r[3],close=r[4],volume=r[5]) for r in m30]
CLOSES = [c.close for c in H1]

def find_m30(h1_ts):
    lo, hi = 0, len(M30) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if int(M30[mid].time) <= h1_ts: lo = mid + 1
        else: hi = mid - 1
    return hi

# ── 指标函数 ──
def sma(arr, n): return sum(arr[-n:]) / n if len(arr) >= n else None
def ema(arr, n):
    if len(arr) < n: return None
    k = 2/(n+1); e = arr[0]
    for p in arr[1:]: e = (p-e)*k+e
    return e
def ema_series(arr, n):
    if len(arr) < n: return None
    k = 2/(n+1); r = [arr[0]]
    for p in arr[1:]: r.append((p-r[-1])*k+r[-1])
    return r

def stoch(cdl, kp=STOCH_K, sp=STOCH_S, dp=STOCH_D):
    n = len(cdl)
    if n < kp+sp+dp+1: return None
    rk = []
    for i in range(kp-1, n):
        w = cdl[i-kp+1:i+1]; hi = max(c.high for c in w); lo = min(c.low for c in w)
        rk.append(50.0 if hi==lo else (w[-1].close-lo)/(hi-lo)*100)
    if len(rk) < sp+dp+1: return None
    sk = [sum(rk[i-sp+1:i+1])/sp for i in range(sp-1, len(rk))]
    if len(sk) < dp+1: return None
    return {"ck":sk[-1],"pk":sk[-2],"cd":sum(sk[-dp:])/dp,"pd":sum(sk[-(dp+1):-1])/dp}

def rsi(arr, n=14):
    if len(arr) < n+1: return None
    g = []; l = []
    for i in range(1,n+1):
        d = arr[i]-arr[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag = sum(g)/n; al = sum(l)/n
    for i in range(n+1, len(arr)):
        d = arr[i]-arr[i-1]; ag = (ag*(n-1)+max(d,0))/n; al = (al*(n-1)+max(-d,0))/n
    return 100.0 if al==0 else 100-100/(1+ag/al)

def macd(arr):
    if len(arr)<35: return None
    k12=2/13;k26=2/27;k9=2/10;e12=arr[0];e26=arr[0];ml=[]
    for p in arr: e12=(p-e12)*k12+e12;e26=(p-e26)*k26+e26;ml.append(e12-e26)
    sg=[ml[0]]
    for v in ml[1:]: sg.append((v-sg[-1])*k9+sg[-1])
    return [ml[i]-sg[i] for i in range(len(ml))]

def bottom_div(hv, lb=DIV_LOOK):
    n=len(hv);st=n-lb*2
    if st<1: return False
    lo=[]
    for i in range(st+1,n-1):
        if hv[i]<hv[i-1] and hv[i]<hv[i+1]: lo.append(hv[i])
    return len(lo)>=2 and lo[-1]>lo[-2]

def top_div(hv, lb=DIV_LOOK):
    n=len(hv);st=n-lb*2
    if st<1: return False
    hi=[]
    for i in range(st+1,n-1):
        if hv[i]>hv[i-1] and hv[i]>hv[i+1]: hi.append(hv[i])
    return len(hi)>=2 and hi[-1]<hi[-2]

def bb(arr, p=BB_PERIOD, m=BB_STD):
    if len(arr)<p: return None
    r=arr[-p:]; s=sum(r)/p; v=sum((c-s)**2 for c in r)/p
    return {"s":s,"u":s+m*math.sqrt(v),"l":s-m*math.sqrt(v)}

def atr_val(cdl, p=ATR_PERIOD):
    if len(cdl)<p+2: return None
    tr=[]
    for i in range(1,len(cdl)):
        h=cdl[i].high;l=cdl[i].low;pc=cdl[i-1].close;tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    if len(tr)<p: return None
    a=[sum(tr[:p])/p]
    for i in range(p,len(tr)): a.append((a[-1]*(p-1)+tr[i])/p)
    return a

def kc(close_series, atr_list, mult=KC_MULT):
    e20 = ema(close_series, 20)
    if e20 is None or atr_list is None: return None
    return {"e":e20,"u":e20+atr_list[-1]*mult,"l":e20-atr_list[-1]*mult}

def m30_trend(m30_closes, idx):
    if idx < 60 or idx >= len(m30_closes): return "NEUTRAL"
    sub = m30_closes[:idx+1]
    e20 = ema_series(sub, 20)
    if e20 is None or len(e20) < 6: return "NEUTRAL"
    sl = e20[-1] - e20[-6]; cp = sub[-1]
    s50 = sma(sub, 50)
    if s50 is None: return "NEUTRAL"
    if sl > 0 and cp > s50: return "UP"
    if sl < 0 and cp < s50: return "DOWN"
    if sl > 0: return "UP"
    if sl < 0: return "DOWN"
    return "NEUTRAL"

# ── 回测主循环 ──
def run():
    t0 = time.time()
    trades = []; running_pnl = 0.0; peak = 0.0; max_dd = 0.0
    entry_price = 0.0; entry_idx = 0; in_pos = False; pos_dir = None
    trail_high = 0.0; trail_low = 0.0
    signals = 0; buys = 0; sells = 0

    # 预计算 ATR 系列
    atr_all = atr_val(H1)
    kc_all = None

    print(f"\n  开始回测 {len(H1)} 根 H1 K线 ...", flush=True)

    for i in range(MIN_BARS, len(H1)):
        c = H1[i]; cl = c.close; ts = int(c.time)
        sc = CLOSES[:i+1]; sca = H1[:i+1]

        s200 = sma(sc, 200)
        if s200 is None: continue
        st = stoch(sca)
        if st is None: continue
        rs = rsi(sc)
        if rs is None: continue
        md = macd(sc)
        bd = bottom_div(md, DIV_LOOK) if md else False
        td = top_div(md, DIV_LOOK) if md else False
        bbv = bb(sc)
        if bbv is None: continue
        atr_now = atr_all[i] if atr_all and i < len(atr_all) else None
        if atr_now is None: continue

        # ATR SMA for exit thresholds (last 10)
        atr_sma = sma(atr_all[:i+1], 10) if atr_all and i >= 10 else None
        if atr_sma is None: atr_sma = atr_now

        kcv = kc(sc, atr_all[:i+1] if atr_all else None)
        if kcv is None: continue

        # M30
        m30_idx = find_m30(ts)
        m30d = m30_trend([m.close for m in M30], m30_idx) if m30_idx >= 0 else "NEUTRAL"
        m30up = m30d == "UP"; m30dn = m30d == "DOWN"

        # 多头评分
        ls = 0
        if cl > s200: ls += 1
        if st["ck"] < 30 or st["pk"] < 30: ls += 1
        if c.low <= bbv["l"]: ls += 1
        if c.low <= kcv["l"]: ls += 1
        if bd: ls += 2
        if rs < 30: ls += 1
        if atr_now < atr_sma * 1.2: ls += 1
        if m30up: ls += 1
        elif m30dn: ls -= 1

        # 空头评分
        ss = 0
        if cl <= s200:
            if st["ck"] > 65 or st["pk"] > 65: ss += 1
            if c.high >= kcv["u"]: ss += 1
            if td: ss += 2
            if rs > 70: ss += 1
            if m30dn: ss += 1
            elif m30up: ss -= 1

        signal = None
        if ls >= 3: signal = "BUY"
        elif ss >= 3: signal = "SELL"

        if signal: signals += 1
        if signal == "BUY": buys += 1
        if signal == "SELL": sells += 1

        # ── 出场 ──
        if in_pos and entry_price > 0:
            is_buy = pos_dir == "BUY"
            if is_buy:
                trail_high = max(trail_high, cl)
                dd = trail_high - cl
                loss = entry_price - cl
                if dd > atr_sma * TRAIL_ATR or loss > atr_sma * HARD_ATR:
                    pnl = (cl - entry_price) * CONTRACT * LOT - COMMISSION
                    trades.append({"dir":pos_dir,"ep":entry_price,"ex":cl,"pnl":round(pnl,2),
                                   "reason":"ATR","entry_t":datetime.fromtimestamp(ts).strftime('%m-%d %H:%M'),
                                   "exit_t":datetime.fromtimestamp(ts).strftime('%m-%d %H:%M')})
                    running_pnl += pnl
                    if running_pnl > peak: peak = running_pnl
                    dd = peak - running_pnl
                    if dd > max_dd: max_dd = dd
                    in_pos = False; entry_price = 0
            else:
                trail_low = min(trail_low, cl)
                rally = cl - trail_low
                loss = cl - entry_price
                if rally > atr_sma * TRAIL_ATR or loss > atr_sma * HARD_ATR:
                    pnl = (entry_price - cl) * CONTRACT * LOT - COMMISSION
                    trades.append({"dir":pos_dir,"ep":entry_price,"ex":cl,"pnl":round(pnl,2),
                                   "reason":"ATR","entry_t":datetime.fromtimestamp(ts).strftime('%m-%d %H:%M'),
                                   "exit_t":datetime.fromtimestamp(ts).strftime('%m-%d %H:%M')})
                    running_pnl += pnl
                    if running_pnl > peak: peak = running_pnl
                    dd = peak - running_pnl
                    if dd > max_dd: max_dd = dd
                    in_pos = False; entry_price = 0

        # ── 入场 ──
        if signal and not in_pos:
            in_pos = True; pos_dir = signal
            entry_price = cl + (0.2 if signal == "BUY" else 0)
            entry_idx = i
            trail_high = cl; trail_low = cl

    # 最终平仓
    if in_pos:
        last = H1[-1]; is_buy = pos_dir == "BUY"
        pnl = (last.close - entry_price)*CONTRACT*LOT - COMMISSION if is_buy else (entry_price - last.close)*CONTRACT*LOT - COMMISSION
        trades.append({"dir":pos_dir,"ep":entry_price,"ex":last.close,"pnl":round(pnl,2),
                       "reason":"END","entry_t":datetime.fromtimestamp(int(entry_idx and H1[entry_idx].time or H1[-1].time)).strftime('%m-%d %H:%M'),
                       "exit_t":datetime.fromtimestamp(int(last.time)).strftime('%m-%d %H:%M')})

    elapsed = time.time() - t0
    return trades, running_pnl, max_dd, peak, signals, buys, sells, elapsed

def report(trades, final_pnl, max_dd, peak, signals, buys, sells, elapsed):
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    wr = len(wins)/n*100 if n else 0
    aw = sum(t["pnl"] for t in wins)/len(wins) if wins else 0
    al = sum(t["pnl"] for t in losses)/len(losses) if losses else 0
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in losses))
    pf = gp/gl if gl else 999
    ddp = max_dd/10000*100

    print(f"\n{'='*70}")
    print(f"  XAUUSD V6 Hybrid — 数据库全量回测报告")
    print(f"  {'='*66}")
    print(f"  数据源:   data/market_data.db (SQLite)")
    print(f"  H1:       {len(H1)} 根 ({datetime.fromtimestamp(int(H1[0].time)).strftime('%Y-%m-%d')} ~ {datetime.fromtimestamp(int(H1[-1].time)).strftime('%Y-%m-%d')})")
    print(f"  初始资金: $10,000  |  LOT: 0.01  |  佣金: $0.50")
    print(f"  端口偏移: 所有端口 +100 (防生产冲突)")
    print(f"  耗时:     {elapsed:.1f}s")
    print(f"  {'='*66}")
    print(f"  [核心指标]")
    print(f"  总交易:     {n}")
    print(f"  总盈亏:     ${final_pnl:>+.2f}  ({final_pnl/10000*100:+.2f}%)")
    print(f"  胜率:       {wr:.1f}%  ({len(wins)}胜 / {len(losses)}负)")
    print(f"  平均盈利:   ${aw:+.2f}  平均亏损: ${al:+.2f}")
    if al: print(f"  盈亏比:     {abs(aw/al):.2f}")
    print(f"  利润因子:   {pf:.2f}")
    print(f"  最大回撤:   ${max_dd:.2f} ({ddp:.2f}%)")
    print(f"  信号总数:   {signals} (BUY={buys} SELL={sells})")
    print(f"  {'='*66}")

    # 月度
    monthly = {}
    for t in trades:
        m = t["exit_t"][:2]
        if m not in monthly: monthly[m]={"pnl":0,"n":0,"wins":0}
        monthly[m]["pnl"]+=t["pnl"]; monthly[m]["n"]+=1
        if t["pnl"]>0: monthly[m]["wins"]+=1
    print(f"\n  月份盈亏")
    for m in sorted(monthly.keys()):
        d = monthly[m]; wr2 = d["wins"]/d["n"]*100 if d["n"] else 0
        print(f"    {m}月: {d['n']}笔  胜率{wr2:.0f}%  ${d['pnl']:+.2f}")

    # 最近10笔
    print(f"\n  最近 {min(10,n)} 笔交易")
    print(f"  {'方向':>4} {'入场':>8} {'出场':>8} {'盈亏':>8} {'理由':<6} {'时间':<12}")
    for t in trades[-10:]:
        sgn = "+" if t["pnl"]>0 else ""
        print(f"  {t['dir']:>4} {t['ep']:>8.2f} {t['ex']:>8.2f} {sgn}${t['pnl']:>+6.2f} {t['reason']:<6} {t['exit_t']:<12}")

    # 连续盈亏
    max_cons_win = 0; max_cons_loss = 0; cur_w = 0; cur_l = 0
    for t in trades:
        if t["pnl"]>0: cur_w+=1; cur_l=0; max_cons_win=max(max_cons_win,cur_w)
        else: cur_l+=1; cur_w=0; max_cons_loss=max(max_cons_loss,cur_l)
    print(f"\n  最大连胜: {max_cons_win}  最大连败: {max_cons_loss}")
    print(f"{'='*70}")

def main():
    trades, pnl, mdd, peak, sigs, buys, sells, elapsed = run()
    report(trades, pnl, mdd, peak, sigs, buys, sells, elapsed)

if __name__ == "__main__":
    main()
