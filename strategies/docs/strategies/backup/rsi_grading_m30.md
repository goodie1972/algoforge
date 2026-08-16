---
name: rsi_grading_m30
magic: 660902
status: backup

type: 均值回归/分级评分
display: M30 RSI 分级评分均值回归策略
desc: RSI 分级评分 + MA14 方向 + BB 触轨 + ADX>28 趋势门禁、阈值 2、EMA9/21 趋势感知出场的均值回归策略
desc_en: M30 RSI Grading — RSI tiered scoring + MA14 direction + BB touch + ADX>28 gate, threshold 2
---

## 评分因子

| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | RSI 分级 | +1~+2 | RSI 超卖/超买分级评分 |
| ② | MA14 方向 | +1 | MA14 趋势方向 |
| ③ | BB 触轨 | +1 | 价格触及 BB 轨道 |
| ④ | ADX 门禁 | — | ADX>28 趋势门禁 |

**判决规则：** 评分 ≥2 触发信号。

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | EMA9/21 趋势感知 | 顺势用宽松出场，逆势用紧凑出场 |
| ② | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 优化版和升级版已替代此策略
- 文件版本: 20260629_rsi_grading_m30.py, rsi_grading_m30_20260630.py
