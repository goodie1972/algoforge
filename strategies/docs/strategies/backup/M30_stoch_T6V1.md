---
name: M30_stoch_T6V1
magic: 660901
status: backup

type: 震荡+趋势双模
display: M30 Stoch BB 双模策略 T6V1
desc: ADX<30 震荡模式(Stoch 金叉+EMA21)与 ADX≥30 趋势模式(DI+EMA21，无 Stoch 交叉)叠加的双模策略
desc_en: M30 Stoch BB Dual-Mode T6V1 — ADX<30 oscillation mode + ADX≥30 trend mode
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 震荡模式 | ADX<30: Stoch 金叉 + EMA21 方向确认 |
| ② | 趋势模式 | ADX≥30: DI 方向 + EMA21（不依赖 Stoch 交叉） |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |
| ② | 硬止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 文件: 20260619_m30_stoch_T6V1.py
