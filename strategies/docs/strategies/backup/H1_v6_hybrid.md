---
name: H1_v6_hybrid
magic: [660604, 660605, 660606, 660607]
status: backup

type: 多因子评分
display: V6 Hybrid 多因子评分策略
desc: 融合 KDJ/布林/Keltner/MACD 背离/RSI/ATR/M30 方向的 8 因子评分 ≥3 触发、ATR 动态止损的双向多因子策略
desc_en: V6 Hybrid — 8-factor scoring (KDJ/BB/Keltner/MACD divergence/RSI/ATR/M30 direction), threshold 3
---

## 评分因子

| # | 因子 | 说明 |
|:-:|:----|:----|
| ① | KDJ | KDJ 金叉/死叉 |
| ② | 布林带 | BB 触轨确认 |
| ③ | Keltner | Keltner 通道突破 |
| ④ | MACD 背离 | MACD 与价格背离 |
| ⑤ | RSI | RSI 超卖/超买 |
| ⑥ | ATR | 波动率确认 |
| ⑦ | M30 方向 | M30 趋势方向过滤 |
| ⑧ | K 线形态 | 反转 K 线确认 |

**判决规则：** 评分 ≥3 触发信号。

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |
| ② | 硬止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 多版本演进文件: v4 ~ v6 等
