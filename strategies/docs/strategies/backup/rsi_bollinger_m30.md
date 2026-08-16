---
name: rsi_bollinger_m30
status: backup

type: 均值回归
display: M30 RSI + M15 RSI 方向过滤策略
desc: 继承 RSI 布林带策略，方向过滤由 M30 改为 M15 的均值回归策略
desc_en: M30 RSI + Bollinger Bands with M15 RSI direction filter
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 触轨 | M30 价格触及 BB 上轨或下轨 |
| ② | RSI 确认 | M30 RSI 超卖/超买 |
| ③ | M15 方向过滤 | M15 RSI 方向与信号一致 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 回归 | 价格回归 BB 中轨 |
| ② | ATR 止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 早期策略，无 STRATEGY_MAGIC 常量
