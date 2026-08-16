---
name: combined
status: backup

type: 组合策略
display: 双均线 + ATR 组合策略
desc: 双均线与 ATR 突破同向双确认才开仓、ATR 动态止损的组合策略
desc_en: Combined — Double MA + ATR breakout dual-confirmation strategy
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 均线交叉 | EMA 快线穿越慢线 |
| ② | ATR 突破 | 价格突破 ATR 通道 |
| ③ | 同向确认 | 均线信号与突破信号同向才开仓 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 反向交叉 | EMA 快线反向穿越 |
| ② | ATR 止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 早期策略，无 STRATEGY_MAGIC 常量
