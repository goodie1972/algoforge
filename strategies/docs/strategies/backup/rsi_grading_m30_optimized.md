---
name: rsi_grading_m30_optimized
magic: 660903
status: backup

type: 均值回归/分级评分
display: M30 RSI 分级评分优化版
desc: ADX≤28 保持阈值 2、恢复 RSI 方向反转因子、放宽 RSI 阈值至 35/60 的均值回归策略
desc_en: M30 RSI Grading Optimized — ADX≤28 threshold 2, RSI direction reversal factor, relaxed 35/60 thresholds
---

## 评分因子

| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | RSI 分级 | +1 | RSI < 35 或 > 65 得分 |
| ② | MA14 方向 | +1 | MA14 趋势方向 |
| ③ | BB 触轨 | +1 | 价格触及 BB 轨道 |
| ④ | RSI 方向反转 | +1 | RSI 连续反转方向 |

**判决规则：** ADX ≤28 时阈值 2 触发信号。

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | EMA9/21 趋势感知 | 顺势用宽松出场，逆势用紧凑出场 |
| ② | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 升级版 rsi_grading_m30_upgraded 已替代此策略
- 文件: rsi_grading_m30_optimized_20260711.py
