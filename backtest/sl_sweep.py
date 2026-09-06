"""
fish_eaten v3.1 · 止损宽度扫描 + 原版 v2 重跑（当前 M30 数据）
===============================================================
目的：
  1. 把 SL 从 1.5×ATR 放宽到 2.5~3.5×ATR（含 1.5 / 3.0 / 5.0 对照），看胜率/回撤是否恢复；
  2. 用「当前 M30 数据集」(2026-03~2026-08, DB 源) 把原版 v2 旧 6 筛子重跑一次 ——
     原来只有 26 笔（更小/不同口径），现在同口径下样本更大，做公平对比。

入场打分逻辑复用 strategies/fish_eaten_entry.py，与实盘同一份代码。

用法：
  python -m backtest.sl_sweep
输出：
  backtest/sl_sweep_M30_db.json
  backtest/sl_sweep_M30_db.xlsx
"""
import os
import sys
import json

import numpy as np  # noqa
import pandas as pd  # noqa

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backtest.fish_eaten_v3 import (  # noqa: E402
    run_backtest, summarize, load_db, calc_indicators, EntryParams, _write_xlsx
)

TF = 'M30'
SRC = 'db'


def main():
    print(f"加载 {TF} 数据（来源: {SRC}）...")
    df = load_db(TF)
    df = calc_indicators(df, from_db=(SRC == 'db'))
    print(f"  {len(df)} 根K线  {df['time'].iloc[0]} → {df['time'].iloc[-1]}")

    bars = {k: df[k].values for k in
            ('open', 'high', 'low', 'close', 'rsi', 'mfi', 'adx', 'pdi', 'ndi',
             'bb_top', 'bb_mid', 'bb_bot', 'bb_width', 'atr')}
    bars['time'] = df['time'].tolist()
    bars['bb_mid_dir'] = df['bb_mid_dir'].values

    p_v3 = EntryParams()  # 默认 = S4/A30/-/D8 (v3.1)

    regimes = [
        ('无止损', 'none', 1.5),
        ('1.5ATR', 'atr', 1.5),
        ('2.5ATR', 'atr', 2.5),
        ('3.0ATR', 'atr', 3.0),
        ('3.5ATR', 'atr', 3.5),
        ('5.0ATR', 'atr', 5.0),
    ]

    rows_v2, rows_v3 = [], []
    t_v2_by, t_v3_by = {}, {}
    for label, sl_mode, sl_mult in regimes:
        kw = dict(time_stop=48, bb_exit=8, sl_mode=sl_mode, sl_atr_mult=sl_mult)
        t_v2 = run_backtest(bars, mode='v2', **kw)
        t_v3 = run_backtest(bars, mode='v3', p=p_v3, **kw)
        rows_v2.append(summarize(f'v2 {label}', t_v2))
        rows_v3.append(summarize(f'v3 {label}', t_v3))
        t_v2_by[label] = t_v2
        t_v3_by[label] = t_v3

    print("\n" + "=" * 100)
    print("原版 v2 旧6筛子 · 当前 M30 数据(5419根) · 各档止损")
    print("=" * 100)
    _pt(rows_v2)

    print("\n" + "=" * 100)
    print("v3.1 默认 S4/A30/-/D8 · 当前 M30 数据 · 各档止损")
    print("=" * 100)
    _pt(rows_v3)

    # ── v3 参数网格 @ 3.0ATR（最佳候选 SL）──
    print("\n扫描 v3 参数网格 @ 3.0ATR ...")
    grid = []
    for score_min in (3, 4, 5, 6):
        for adx_max in (30.0, 40.0, 60.0):
            for req in (False, True):
                for div in (8, 10, 14):
                    grid.append(EntryParams(score_min=score_min, adx_max=adx_max,
                                            require_pierce=req, div_lookback=div))
    results = []
    for p in grid:
        tr = run_backtest(bars, mode='v3', p=p,
                          time_stop=48, bb_exit=8, sl_mode='atr', sl_atr_mult=3.0)
        s = summarize(f"S{p.score_min}/A{int(p.adx_max)}/"
                      f"{'P' if p.require_pierce else '-'}/D{p.div_lookback}", tr)
        s['params'] = p.as_dict()
        s['trades_list'] = tr
        results.append(s)

    ok = [r for r in results if r['trades'] >= 10]
    ok.sort(key=lambda r: r['pnl'], reverse=True)
    print(f"\n样本≥10 笔: {len(ok)}/{len(results)}")
    print("=" * 100)
    print("净PnL Top15 @3.0ATR")
    print("=" * 100)
    _pt(ok[:15])
    ok2 = sorted(ok, key=lambda r: r['avg_pnl'], reverse=True)
    print("\n" + "=" * 100)
    print("均笔盈亏 Top15 @3.0ATR")
    print("=" * 100)
    _pt(ok2[:15])

    # ── 输出 ──
    out = {
        'regimes_v2': rows_v2,
        'regimes_v3': rows_v3,
        'grid_3atr': [{k: v for k, v in r.items() if k != 'trades_list'} for r in results],
    }
    jp = os.path.join(ROOT, 'backtest', 'sl_sweep_M30_db.json')
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nJSON: {jp}")

    xpath = os.path.join(ROOT, 'backtest', 'sl_sweep_M30_db.xlsx')
    _write_xlsx(xpath, rows_v2[0], rows_v3[3], results,
                t_v2_by.get('3.0ATR', []), t_v3_by.get('3.0ATR', []))
    print(f"Excel: {xpath}")


def _pt(rows):
    hdr = (f"{'组合':<22}{'笔数':>5}{'胜率%':>7}{'净PnL':>10}{'均笔':>9}"
           f"{'回撤':>9}{'均K线':>7}{'MAE':>8}{'MFE':>8}{'MFE/MAE':>9}")
    print(hdr)
    print('-' * len(hdr))
    for r in rows:
        ratio = r['mfe'] / r['mae'] if r['mae'] else 0
        print(f"{r['name']:<22}{r['trades']:>5}{r['winrate']:>7.1f}{r['pnl']:>10.2f}"
              f"{r['avg_pnl']:>9.2f}{r['maxdd']:>9.2f}{r['avg_bars']:>7.1f}"
              f"{r['mae']:>8.2f}{r['mfe']:>8.2f}{ratio:>9.2f}")
    print("\nMAE=全持仓最大逆向幅度(真实风险)  MFE=全持仓最大有利幅度  MFE/MAE>1 才是正期望结构")


if __name__ == '__main__':
    main()
