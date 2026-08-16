---
name: sanqing_h1_original
magic: 880101
status: backup

type: 多因子评分
display: SanQing EA 原始 v1 版
desc: SanQing EA 原始 v1 代码，6 因子评分 + 固定阈值、ATR 跟踪止损，无任何后期改动的纯净版
desc_en: SanQing EA Original v1 — 6-factor scoring + fixed threshold, pristine untouched version
---

## 评分因子

| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | EMA9/21 趋势 | +1 | EMA9 > EMA21（做多）/ EMA9 < EMA21（做空） |
| ② | ATR14 波动 | +1 | ATR 确认波动活跃 |
| ③ | ADX | +1 | ADX 趋势强度 |
| ④ | RSI | +1 | RSI 方向确认 |
| ⑤ | BB 触轨 | +1 | 布林带触轨 |
| ⑥ | K 线形态 | +1 | K 线反转形态 |

**判决规则：** 评分 ≥ 固定阈值触发信号。

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 文件: sanqing_h1_original_20260711.py
