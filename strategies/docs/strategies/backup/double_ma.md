---
name: double_ma
status: backup

type: 趋势跟踪/均线交叉
display: 双均线策略
desc: EMA 快线上穿/下穿慢线产生多空信号的趋势跟踪策略
desc_en: Double MA — EMA fast/slow crossover trend-following strategy
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 金叉 | EMA 快线上穿慢线 → 做多 |
| ② | 死叉 | EMA 快线下穿慢线 → 做空 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 反向交叉 | EMA 快线反向穿越慢线 |
| ② | ATR 止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 早期策略，无 STRATEGY_MAGIC 常量
