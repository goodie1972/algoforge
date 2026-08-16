---
name: stoch_trend_h1_optimized
magic: 661202

type: 趋势回调
display: Stoch 回调顺势策略（H1 优化版 v6）
desc: ADX>20 趋势确认 + Stoch(14,3,3) 超买超卖回调入场，H4 趋势过滤 + H1 信号 + M15 精确切机
desc_en: H1 Stoch Pullback Trend-Following (Optimized v6) — ADX>20 trend + Stoch(14,3,3) pullback entry
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ADX 趋势确认 | ADX > 20 确认趋势存在 |
| ② | Stoch 回调 | Stoch(14,3,3) K 线进入超买（做空）或超卖（做多）区域后回调 |
| ③ | H4 趋势过滤 | H4 趋势方向与信号一致 |
| ④ | M15 精确切机 | M15 出现同向触发信号 |

**判决规则：** ADX + Stoch + H4 + M15 多周期共振触发信号。

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |
| ② | 硬止损 | 亏损超过 hard_mult × ATR |
| ③ | Stoch 反转 | Stoch 出现反向交叉 |

## 特别规则

- 相比原版 stoch_trend_h1，优化版使用 Stoch(14,3,3) 更快信号响应
- 数据源：全部指标从 DataFactory TA-Lib 读取
