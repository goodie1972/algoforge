"""
FollowAve v1.2（旧，bb_mid_direction + 70/30）vs v1.3（新，bb_mid_direction + 80/20）对比回测
==================================================================================
复用 followave_exit_value.py 中已校验（while 索引、与单笔重放同口径、零重叠）的引擎。

v1.2（线上旧版）语义：
  - bbi_dir 读 get_indicator("bb_mid_direction")，即 BB 中轨 = SMA20 斜率（代理方向）
  - 入场阈值 70/30
  - TRAIL_ATR：M15=4.0 / M30=3.0
v1.3（本次改进）语义：
  - 方向源不变，仍读 bb_mid_direction（A/B 验证：真实 bbi_direction 在 M15 净亏 +462.8，综合净亏，已撤销切换）
  - 入场阈值 80/20（撤销 v1.1 无回测依据的收紧，恢复 v1.0 原值）
  - TRAIL_ATR 不变：M15=4.0 / M30=3.0

⚠️ 透明对照：额外打印 real=bbi_direction 行，可见方向源切换对两周期的不一致影响。
结论判读：若 v1.3(proxy) 行 PnL 明显高于 v1.2，则阈值放宽生效；real 行仅供风险提示。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from backtest.followave_exit_value import build, run, met, line

TRAIL = {'M15': 4.0, 'M30': 3.0}


def main():
    print('=== FollowAve v1.2（bb_mid_direction + 70/30）vs v1.3（bb_mid_direction + 80/20）===')
    print('=== 全样本（库内全部可用 K 线），实盘口径对齐 ===\n')
    for tf in ['M15', 'M30']:
        c = build(tf)
        T = TRAIL[tf]
        print(f'\n{"="*128}')
        print(f'{tf}  {len(c)} 根  TRAIL_ATR={T}')
        print('=' * 128)

        v12 = run(c, dir_key='bbmid_dir', entry_k_ob=70, entry_k_os=30, trail_atr=T)
        m12 = met(v12)
        line('v1.2 旧版(proxy+70/30)', m12)

        v13 = run(c, dir_key='bbmid_dir', entry_k_ob=80, entry_k_os=20, trail_atr=T)
        m13 = met(v13)
        line('v1.3 新版(proxy+80/20)', m13)

        # 透明对照：真实 BBI 方向（供风险提示，非采用）
        r13 = run(c, dir_key='bbi_dir', entry_k_ob=80, entry_k_os=20, trail_atr=T)
        line('  [对照]real BBI方向+80/20', met(r13))

        d = m13['pnl'] - m12['pnl']
        print(f'\n  v1.3 相对 v1.2 净增 PnL: {d:>+9.1f}  '
              f'(胜率 {m13["wr"]-m12["wr"]:>+5.1f}pt, 交易数 {m13["n"]-m12["n"]:+d})')


if __name__ == '__main__':
    main()
