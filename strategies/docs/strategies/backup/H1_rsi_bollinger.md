---
name: H1_rsi_bollinger
status: backup

type: 均值回归
display: H1 RSI + 布林带均值回归策略
desc: 价格触布林带轨 + RSI 超卖/超买确认入场，BB 带宽止损 + EMA20 跟踪止盈
desc_en: H1 RSI + Bollinger Bands Mean Reversion
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 触轨 | 价格触及 BB 上轨或下轨 |
| ② | RSI 确认 | RSI 超卖（做多）或超买（做空） |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 带宽止损 | BB 带宽收窄到阈值 |
| ② | EMA20 跟踪 | 价格回归 EMA20 止盈 |

## 备注

- 后备策略，已从活跃池中移除
- 早期策略，无 STRATEGY_MAGIC 常量
