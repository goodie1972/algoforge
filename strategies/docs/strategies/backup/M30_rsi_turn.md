---
name: M30_rsi_turn
status: backup

type: 动量/反转
display: M30 RSI 掉头策略
desc: 只看 M30 RSI 方向，掉头入场、反向掉头出场并同时开反向单的动量策略
desc_en: M30 RSI Turn — RSI direction reversal momentum strategy
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | RSI 掉头 | M30 RSI 方向反转即入场 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | RSI 反向掉头 | RSI 再次反转时平仓并开反向单 |

## 备注

- 后备策略，已从活跃池中移除
- 早期策略，无 STRATEGY_MAGIC 常量
