---
name: stoch_trend_h1
magic: 661201
status: backup

type: 趋势回调
display: H1 Stoch 回调顺势策略
desc: ADX>25 趋势确认 + Stoch(14,3,3) 超买超卖回调入场、H4 趋势方向过滤的 H1 顺势策略
desc_en: H1 Stoch Pullback Trend-Following — ADX>25 + Stoch(14,3,3) pullback + H4 trend filter
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ADX 趋势确认 | ADX > 25 确认趋势存在 |
| ② | Stoch 回调 | Stoch(14,3,3) 超买（做空）或超卖（做多）回调 |
| ③ | H4 趋势过滤 | H4 趋势方向与信号一致 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |
| ② | 硬止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 优化版 stoch_trend_h1_optimized 已替代此策略
- 文件: stoch_trend_h1_20260630.py, 20260629_stoch_trend_h1.py
