"""followave 全样本消融实验：逐层拆掉出场规则，量化每层贡献 + 风险指标。

样本：M15 2026-04-24~09-05, M30 2026-03-24~09-05（库内全量）
与旧脚本(7/1~8/27)相比样本量 2.3x / 2.8x。
"""
import sys
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from backtest.followave_param_test import load_candles, calc_indicators


def run(candles, *,
        entry_cross=True,        # 入场是否要求 Stoch 当根穿越(v1.2) vs 只要 K>D(v1.0)
        entry_k_ob=70,           # 入场 K 上限
        entry_k_os=30,           # 入场 K 下限
        use_tp=True,             # ① 极值穿越止盈
        use_trendrev=True,       # ② 趋势反转
        use_hardstop=True,       # ③ 硬止损
        use_trail=True,          # ④ 移动止损
        trendrev_bbi_dir=True,   # ② 是否要求 bbi_dir 同向
        ecb=3,                   # ② 连续确认根数
        trail_atr=4.0,
        sl_atr=None,             # 不为 None 时用 ATR 硬止损替代 BB 反向轨
        min_hold=0,              # ① 最小持仓根数
        exit_ob=80, exit_os=20,
        bb_tol=3):
    trades = []
    in_pos = False
    direction = None
    entry_price = 0.0
    entry_bar = -1
    exit_count = 0
    last_bar_time = 0
    trail_peak = None
    touched = False
    pending = None

    for i in range(30, len(candles)):
        row = candles[i - 1]
        bbi = row['bbi']; close = row['close']; high = row['high']; low = row['low']
        pdi = row['pdi']; ndi = row['ndi']
        k = row['stoch_k']; d = row['stoch_d']
        bb_mid = row['bb_mid']; bb_up = row['bb_up']; bb_low = row['bb_low']
        bbi_dir = row['bbi_dir']; atr = row['atr']
        if any(np.isnan(v) for v in [bbi, close, pdi, ndi, k, atr]):
            continue

        if pending and not in_pos:
            entry_price = candles[i]['open']
            entry_bar = i
            direction = pending
            in_pos = True
            exit_count = 0
            trail_peak = None
            touched = False
            pending = None
            last_bar_time = candles[i]['time']
            continue

        if in_pos:
            if candles[i]['time'] == last_bar_time:
                continue
            last_bar_time = candles[i]['time']
            prev = candles[i - 2] if i >= 2 else None
            k_p = prev['stoch_k'] if prev is not None and not np.isnan(prev['stoch_k']) else k
            d_p = prev['stoch_d'] if prev is not None and not np.isnan(prev['stoch_d']) else d
            held = i - entry_bar

            if direction == 'LONG':
                if trail_peak is None or high > trail_peak:
                    trail_peak = high
                if high >= bb_up - bb_tol:
                    touched = True

                if use_tp and touched and held >= min_hold and k < d and k_p >= d_p and k > exit_ob:
                    trades.append(_mk(entry_bar, i, 'LONG', entry_price, close, 'overbought_cross'))
                    in_pos = False; direction = None; continue

                if use_trendrev:
                    cond = (close < bbi and bbi_dir == 'down') if trendrev_bbi_dir else (close < bbi)
                    exit_count = exit_count + 1 if cond else 0
                    if exit_count >= ecb:
                        trades.append(_mk(entry_bar, i, 'LONG', entry_price, close, 'trend_reversal'))
                        in_pos = False; direction = None; continue

                if use_hardstop:
                    if sl_atr is not None:
                        if entry_price - close > sl_atr * atr:
                            trades.append(_mk(entry_bar, i, 'LONG', entry_price, close, 'atr_stop'))
                            in_pos = False; direction = None; continue
                    elif close < bb_low:
                        trades.append(_mk(entry_bar, i, 'LONG', entry_price, close, 'bb_stop'))
                        in_pos = False; direction = None; continue

                if use_trail and trail_atr > 0 and trail_peak is not None:
                    if close < trail_peak - trail_atr * atr:
                        trades.append(_mk(entry_bar, i, 'LONG', entry_price, close, 'trailing'))
                        in_pos = False; direction = None; continue

            else:
                if trail_peak is None or low < trail_peak:
                    trail_peak = low
                if low <= bb_low + bb_tol:
                    touched = True

                if use_tp and touched and held >= min_hold and k > d and k_p <= d_p and k < exit_os:
                    trades.append(_mk(entry_bar, i, 'SHORT', entry_price, close, 'oversold_cross'))
                    in_pos = False; direction = None; continue

                if use_trendrev:
                    cond = (close > bbi and bbi_dir == 'up') if trendrev_bbi_dir else (close > bbi)
                    exit_count = exit_count + 1 if cond else 0
                    if exit_count >= ecb:
                        trades.append(_mk(entry_bar, i, 'SHORT', entry_price, close, 'trend_reversal'))
                        in_pos = False; direction = None; continue

                if use_hardstop:
                    if sl_atr is not None:
                        if close - entry_price > sl_atr * atr:
                            trades.append(_mk(entry_bar, i, 'SHORT', entry_price, close, 'atr_stop'))
                            in_pos = False; direction = None; continue
                    elif close > bb_up:
                        trades.append(_mk(entry_bar, i, 'SHORT', entry_price, close, 'bb_stop'))
                        in_pos = False; direction = None; continue

                if use_trail and trail_atr > 0 and trail_peak is not None:
                    if close > trail_peak + trail_atr * atr:
                        trades.append(_mk(entry_bar, i, 'SHORT', entry_price, close, 'trailing'))
                        in_pos = False; direction = None; continue
            continue

        if abs(pdi - ndi) <= 5:
            continue
        prev = candles[i - 2] if i >= 2 else None
        k_p = prev['stoch_k'] if prev is not None and not np.isnan(prev['stoch_k']) else k
        d_p = prev['stoch_d'] if prev is not None and not np.isnan(prev['stoch_d']) else d
        if entry_cross:
            gx = k > d and k_p <= d_p
            dx = k < d and k_p >= d_p
        else:
            gx = k > d
            dx = k < d
        if pdi > ndi and close > bbi and gx and k < entry_k_ob and close >= bb_mid:
            pending = 'LONG'
        elif ndi > pdi and close < bbi and dx and k > entry_k_os and close <= bb_mid:
            pending = 'SHORT'
    return trades


def _mk(eb, xb, d, ep, xp, reason):
    pnl = (xp - ep) if d == 'LONG' else (ep - xp)
    return {'entry': eb, 'exit': xb, 'dir': d, 'ep': ep, 'xp': xp,
            'pnl': pnl, 'reason': reason, 'bars': xb - eb}


def metrics(trades):
    if not trades:
        return dict(n=0)
    p = [t['pnl'] for t in trades]
    n = len(p)
    wins = [x for x in p if x > 0]
    losses = [x for x in p if x <= 0]
    gw = sum(wins); gl = -sum(losses)
    eq, peak, mdd = 0.0, 0.0, 0.0
    for x in p:
        eq += x
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    sp = sorted(p, reverse=True)
    return dict(
        n=n,
        wr=len(wins) / n * 100,
        pnl=sum(p),
        avg=sum(p) / n,
        pf=(gw / gl) if gl > 0 else float('inf'),
        mxw=max(p), mxl=min(p),
        mdd=mdd,
        ex1=sum(p) - sp[0],
        ex3=sum(p) - sum(sp[:3]),
        bars=sum(t['bars'] for t in trades) / n,
    )


def show(name, m, reasons=None):
    if m['n'] == 0:
        print(f'{name:<34} {"0 笔":>6}')
        return
    pf = f"{m['pf']:>5.2f}" if m['pf'] != float('inf') else '  inf'
    print(f"{name:<34} {m['n']:>4}笔 胜率{m['wr']:>5.1f}% PnL{m['pnl']:>+9.1f} 均{m['avg']:>+6.2f} "
          f"PF{pf} 最大赢{m['mxw']:>7.2f} 最大亏{m['mxl']:>8.2f} 回撤{m['mdd']:>8.1f} "
          f"去Top1{m['ex1']:>+8.1f} 去Top3{m['ex3']:>+8.1f} 均持{m['bars']:>5.1f}根")
    if reasons:
        rs = {}
        for t in reasons:
            rs.setdefault(t['reason'], [0, 0.0])
            rs[t['reason']][0] += 1
            rs[t['reason']][1] += t['pnl']
        s = ' '.join(f"{k}:{v[0]}({v[1]:+.0f})" for k, v in sorted(rs.items(), key=lambda x: -x[1][0]))
        print(f'{"":<34} 出场 → {s}')


TRAIL = {'M15': 4.0, 'M30': 3.0}
for tf in ['M15', 'M30']:
    c = calc_indicators(load_candles(tf, '2026-01-01', '2026-09-30'))
    T = TRAIL[tf]
    print(f'\n{"="*160}')
    print(f'{tf}  全样本 {len(c)} 根')
    print('=' * 160)

    V = [
        ('A v1.0 原版(单出场)', dict(entry_cross=False, entry_k_ob=80, entry_k_os=20,
                                  use_tp=False, use_hardstop=False, use_trail=False,
                                  trendrev_bbi_dir=False)),
        ('B v1.2 现状(文件实际值)', dict(trail_atr=T)),
        ('C v1.2 去掉①止盈层', dict(trail_atr=T, use_tp=False)),
        ('D v1.2 去掉③硬止损', dict(trail_atr=T, use_hardstop=False)),
        ('E v1.2 去掉④移动止损', dict(trail_atr=T, use_trail=False)),
        ('F v1.2 去掉②趋势反转', dict(trail_atr=T, use_trendrev=False)),
        ('G v1.2 ②不要求bbi_dir', dict(trail_atr=T, trendrev_bbi_dir=False)),
        ('H v1.2 硬止损→ATR2.5', dict(trail_atr=T, sl_atr=2.5)),
        ('I v1.2 硬止损→ATR3.5', dict(trail_atr=T, sl_atr=3.5)),
        ('J v1.2 ①加最小持仓6根', dict(trail_atr=T, min_hold=6)),
        ('K v1.0入场 + v1.2出场', dict(entry_cross=False, entry_k_ob=80, entry_k_os=20, trail_atr=T)),
        ('L v1.2入场 + v1.0出场', dict(use_tp=False, use_hardstop=False, use_trail=False,
                                    trendrev_bbi_dir=False)),
    ]
    for name, kw in V:
        t = run(c, **kw)
        show(name, metrics(t), t)
