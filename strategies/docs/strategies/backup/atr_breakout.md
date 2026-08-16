---
name: atr_breakout
status: backup

type: 趋势跟踪/突破
display: ATR 突破策略
desc: N 日高低点突破入场 + ATR 动态止损的趋势跟踪策略，适合黄金大波段
desc_en: ATR Breakout — N-day high/low breakout entry + ATR dynamic stop-loss
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 高低点突破 | 价格突破 N 日最高点（做多）或最低点（做空） |
| ② | ATR 确认 | ATR 波动率确认突破有效性 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |
| ② | 硬止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 早期策略，无 STRATEGY_MAGIC 常量（magic 由 settings 注入）
