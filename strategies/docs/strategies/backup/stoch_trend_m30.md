---
name: stoch_trend_m30
magic: 660903
status: backup

type: 趋势回调/多周期
display: Stoch 回调顺势策略 (M30)
desc: ADX>25 趋势确认 + Stoch(21,5,3) 超买超卖回调入场、H4 趋势方向过滤的 M30 顺势策略
desc_en: M30 Stoch Pullback Trend-Following — ADX>25 + Stoch(21,5,3) + H4 trend filter
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ADX 趋势确认 | ADX > 25 |
| ② | Stoch 回调 | Stoch(21,5,3) 超买超卖回调 |
| ③ | H4 趋势过滤 | H4 趋势方向与信号一致 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |
| ② | 硬止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 文件: stoch_trend_m30.py
