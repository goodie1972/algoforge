---
name: H4_stoch_bollinger
status: backup

type: 均值回归
display: H4 Stoch + 布林带均值回归策略
desc: Stoch 超卖区金叉/超买区死叉 + 布林带触轨入场的均值回归策略，EMA20 跟踪止损
desc_en: H4 Stoch + Bollinger Bands Mean Reversion
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 触轨 | 价格触及 BB 上轨或下轨 |
| ② | Stoch 交叉 | Stoch 超卖区金叉（做多）或超买区死叉（做空） |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | EMA20 跟踪 | 价格回归 EMA20 |
| ② | ATR 止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 早期策略，无 STRATEGY_MAGIC 常量
