---
name: stoch_m30
magic: 660901
status: backup

type: 均值回归/震荡
display: M30 Stoch 均值回归策略
desc: Stoch 9-3-3 K/D 交叉 + EMA21 + BB 宽度 ≤1.0 的 M30 纯震荡均值回归策略，ATR 硬止损
desc_en: M30 Stoch Mean Reversion — K/D crossover + EMA21 + BB width ≤1.0, ATR hard stop
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | Stoch 交叉 | Stoch(9,3,3) K/D 交叉 |
| ② | EMA21 方向 | EMA21 方向确认 |
| ③ | BB 宽度 | BB 带宽 ≤1.0 确认震荡环境 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | Stoch 反向交叉 | K/D 反向交叉 |
| ② | ATR 硬止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 文件: stoch_m30.py
