"""followave 实盘语义对齐 + 出场层边际价值(单笔独立重放) + 实盘语义下的改进候选对比"""
import sys
import numpy as np
import talib
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from backtest.followave_param_test import load_candles


def build(tf):
    c = load_candles(tf, '2026-01-01', '2026-09-30')
    closes = np.array([x['close'] for x in c], float)
    highs = np.array([x['high'] for x in c], float)
    lows = np.array([x['low'] for x in c], float)
    bbi = (talib.SMA(closes, 3) + talib.SMA(closes, 6) + talib.SMA(closes, 12) + talib.SMA(closes, 24)) / 4
    k, d = talib.STOCH(highs, lows, closes, 5, 3, 0, 3, 0)
    up, mid, low_b = talib.BBANDS(closes, 20, 2, 2)
    pdi = talib.PLUS_DI(highs, lows, closes, 14)
    ndi = talib.MINUS_DI(highs, lows, closes, 14)
    atr = talib.ATR(highs, lows, closes, 14)

    def slope(a):
        s = np.where(a > np.roll(a, 1), 'up', np.where(a < np.roll(a, 1), 'down', 'flat'))
        s[0] = 'flat'
        return s
    bbi_dir, bbmid_dir = slope(bbi), slope(mid)
    for i, x in enumerate(c):
        x.update(bbi=bbi[i], stoch_k=k[i], stoch_d=d[i], bb_mid=mid[i], bb_up=up[i],
                 bb_low=low_b[i], pdi=pdi[i], ndi=ndi[i], atr=atr[i],
                 bbi_dir=bbi_dir[i], bbmid_dir=bbmid_dir[i])
    return c


def sim(c, eb, dr, ep, *, dir_key='bbmid_dir', disabled=(), ecb=3, trail_atr=4.0,
        min_hold=0, exit_ob=80, exit_os=20, bb_tol=3, sl_atr=None, max_hold=None):
    """单笔独立重放：从入场bar开始只跑出场规则，返回 (exit_bar, price, reason) 或 None"""
    exit_count = 0; trail_peak = None; touched = False
    last = c[eb]['time']
    LONG = dr == 'LONG'
    for i in range(eb + 1, len(c)):
        r = c[i - 1]
        close, high, low = r['close'], r['high'], r['low']
        bbi, kk, dd, atr = r['bbi'], r['stoch_k'], r['stoch_d'], r['atr']
        bb_up, bb_low, dn = r['bb_up'], r['bb_low'], r[dir_key]
        if any(np.isnan(v) for v in [bbi, close, kk, atr]):
            continue
        if c[i]['time'] == last:
            continue
        last = c[i]['time']
        prev = c[i - 2] if i >= 2 else None
        k_p = prev['stoch_k'] if prev is not None and not np.isnan(prev['stoch_k']) else kk
        d_p = prev['stoch_d'] if prev is not None and not np.isnan(prev['stoch_d']) else dd
        held = i - eb
        if max_hold and held >= max_hold:
            return i, close, 'MAXHOLD'

        if LONG:
            trail_peak = high if trail_peak is None or high > trail_peak else trail_peak
            if high >= bb_up - bb_tol:
                touched = True
            if 'TP' not in disabled and touched and held >= min_hold and kk < dd and k_p >= d_p and kk > exit_ob:
                return i, close, 'TP极值穿越'
            if 'TR' not in disabled:
                exit_count = exit_count + 1 if (close < bbi and dn == 'down') else 0
                if exit_count >= ecb:
                    return i, close, 'TR趋势反转'
            if 'SL' not in disabled:
                if sl_atr is not None:
                    if ep - close > sl_atr * atr:
                        return i, close, 'SL_ATR止损'
                elif close < bb_low:
                    return i, close, 'SL硬止损'
            if 'TL' not in disabled and trail_atr > 0 and trail_peak is not None \
                    and close < trail_peak - trail_atr * atr:
                return i, close, 'TL移动止损'
        else:
            trail_peak = low if trail_peak is None or low < trail_peak else trail_peak
            if low <= bb_low + bb_tol:
                touched = True
            if 'TP' not in disabled and touched and held >= min_hold and kk > dd and k_p <= d_p and kk < exit_os:
                return i, close, 'TP极值穿越'
            if 'TR' not in disabled:
                exit_count = exit_count + 1 if (close > bbi and dn == 'up') else 0
                if exit_count >= ecb:
                    return i, close, 'TR趋势反转'
            if 'SL' not in disabled:
                if sl_atr is not None:
                    if close - ep > sl_atr * atr:
                        return i, close, 'SL_ATR止损'
                elif close > bb_up:
                    return i, close, 'SL硬止损'
            if 'TL' not in disabled and trail_atr > 0 and trail_peak is not None \
                    and close > trail_peak + trail_atr * atr:
                return i, close, 'TL移动止损'
    return None


def run(c, *, dir_key='bbmid_dir', entry_cross=True, entry_k_ob=70, entry_k_os=30,
        disabled=(), ecb=3, trail_atr=4.0, min_hold=0, exit_ob=80, exit_os=20,
        bb_tol=3, sl_atr=None):
    """完整序列回测：入场逻辑不变，出场用 sim() 保证与单笔重放同口径。
    注意：必须用 while 显式控索引——for i in range() 里对 i 赋值会被迭代器覆盖，
    导致跳转失效、产生重叠持仓。"""
    trades = []
    pending = None
    i = 30
    while i < len(c):
        r = c[i - 1]
        bbi, close = r['bbi'], r['close']
        pdi, ndi, kk, dd = r['pdi'], r['ndi'], r['stoch_k'], r['stoch_d']
        bb_mid = r['bb_mid']
        if any(np.isnan(v) for v in [bbi, close, pdi, ndi, kk]):
            i += 1
            continue

        if pending is not None:                      # 上一根出现信号 → 本根开盘成交
            eb, dr, ep = i, pending, c[i]['open']
            pending = None
            res = sim(c, eb, dr, ep, dir_key=dir_key, disabled=disabled, ecb=ecb,
                      trail_atr=trail_atr, min_hold=min_hold, exit_ob=exit_ob,
                      exit_os=exit_os, bb_tol=bb_tol, sl_atr=sl_atr)
            if res is None:                          # 到数据末尾仍未出场，丢弃
                i += 1
                continue
            xb, xp, why = res
            trades.append({'entry': eb, 'exit': xb, 'dir': dr, 'ep': ep, 'xp': xp,
                           'pnl': (xp - ep) if dr == 'LONG' else (ep - xp),
                           'reason': why, 'bars': xb - eb})
            i = xb + 1                               # 单仓位：出场后才能再入场
            continue

        if abs(pdi - ndi) <= 5:
            i += 1
            continue
        prev = c[i - 2] if i >= 2 else None
        k_p = prev['stoch_k'] if prev is not None and not np.isnan(prev['stoch_k']) else kk
        d_p = prev['stoch_d'] if prev is not None and not np.isnan(prev['stoch_d']) else dd
        gx = (kk > dd and k_p <= d_p) if entry_cross else (kk > dd)
        dx = (kk < dd and k_p >= d_p) if entry_cross else (kk < dd)
        if pdi > ndi and close > bbi and gx and kk < entry_k_ob and close >= bb_mid:
            pending = 'LONG'
        elif ndi > pdi and close < bbi and dx and kk > entry_k_os and close <= bb_mid:
            pending = 'SHORT'
        i += 1
    return trades


def met(tr):
    if not tr:
        return dict(n=0, wr=0, pnl=0, pf=0, mdd=0, ex3=0, mxw=0, mxl=0, bars=0)
    p = [t['pnl'] for t in tr]
    gw = sum(x for x in p if x > 0); gl = -sum(x for x in p if x <= 0)
    eq = peak = mdd = 0.0
    for x in p:
        eq += x; peak = max(peak, eq); mdd = min(mdd, eq - peak)
    sp = sorted(p, reverse=True)
    return dict(n=len(p), wr=sum(1 for x in p if x > 0) / len(p) * 100, pnl=sum(p),
                pf=gw / gl if gl > 0 else 9.99, mdd=mdd, ex3=sum(p) - sum(sp[:3]),
                mxw=sp[0], mxl=min(p), bars=sum(t['bars'] for t in tr) / len(tr))


def line(tag, m):
    print(f"{tag:<32} {m['n']:>4}笔 胜率{m['wr']:>5.1f}% PnL{m['pnl']:>+9.1f} PF{m['pf']:>5.2f} "
          f"回撤{m['mdd']:>8.1f} 去Top3{m['ex3']:>+9.1f} 最大亏{m['mxl']:>8.2f} 均持{m['bars']:>5.1f}根")


TRAIL = {'M15': 4.0, 'M30': 3.0}

def main():
  for tf in ['M15', 'M30']:
      c = build(tf)
      T = TRAIL[tf]
      print(f'\n{"="*128}\n{tf}  {len(c)} 根   出场层边际价值与候选对比\n{"="*128}')

      # B0（旧 v1.2 线上语义）：bb_mid_direction = BB中轨/SMA20 斜率（代理，非 BBI）
      base = run(c, dir_key='bbmid_dir', trail_atr=T)
      line('B0 v1.2 现状(代理方向70/30)', met(base))
      # B0-real（方向源统一为真实 BBI 后，阈值仍 70/30）：口径修复单独贡献
      line('B0-real 真实BBI方向(70/30)', met(run(c, dir_key='bbi_dir', trail_atr=T)))

      # 出场层边际价值：单笔独立重放配对
      print('  -- 出场层边际价值（同一笔，含该层 vs 屏蔽该层）--')
      for lay in ['TP', 'TR', 'SL', 'TL']:
          pairs = []
          for t in base:
              if not t['reason'].startswith({'TP': 'TP', 'TR': 'TR', 'SL': 'SL', 'TL': 'TL'}[lay]):
                  continue
              cf = sim(c, t['entry'], t['dir'], t['ep'], disabled=(lay,), trail_atr=T)
              if cf:
                  pairs.append((t['pnl'], (cf[1] - t['ep']) if t['dir'] == 'LONG' else (t['ep'] - cf[1]),
                                t['bars'], cf[0] - t['entry']))
          if not pairs:
              print(f'     {lay}: 触发 0 次'); continue
          g = sum(a - b for a, b, _, _ in pairs)
          bet = sum(1 for a, b, _, _ in pairs if a > b)
          hb = sum(bb for _, _, bb, _ in pairs) / len(pairs)
          print(f'     {lay} 触发{len(pairs):>4}次  该层增量{g:>+9.1f} ({g/len(pairs):>+6.2f}/次)  '
                f'提前走更优 {bet}/{len(pairs)}({bet/len(pairs)*100:>3.0f}%)  '
                f'屏蔽后均持{hb:>5.1f}根')

      print('  -- 改进候选（实盘语义下）--')
      CAND = [
          ('C1 入场放宽→K<80/K>20', dict(entry_k_ob=80, entry_k_os=20)),
          ('C2 入场不强制当根穿越', dict(entry_cross=False)),
          ('C3 C1+C2 (v1.0入场口径)', dict(entry_k_ob=80, entry_k_os=20, entry_cross=False)),
          ('C4 硬止损→ATR 2.5x', dict(sl_atr=2.5)),
          ('C5 硬止损→ATR 3.0x', dict(sl_atr=3.0)),
          ('C6 ①止盈加最小持仓6根', dict(min_hold=6)),
          ('C7 屏蔽④移动止损', dict(disabled=('TL',))),
          ('C8 屏蔽③硬止损', dict(disabled=('SL',))),
          ('C9 C3+C4', dict(entry_k_ob=80, entry_k_os=20, entry_cross=False, sl_atr=2.5)),
          ('CA C3+C7', dict(entry_k_ob=80, entry_k_os=20, entry_cross=False, disabled=('TL',))),
      ]
      for nm, kw in CAND:
          line('  ' + nm, met(run(c, trail_atr=T, **kw)))


if __name__ == '__main__':
    main()
