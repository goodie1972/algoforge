---
name: m30_bb_deepreturn_optimized
magic: 661102

type: 超跌反弹
display: M30 BB DeepReturn Optimized — 超跌反弹优化版
desc: BB 极值 + MFI 极值识别超跌反弹，按 BB 开口方向与 K 线是否同向分支决策出场
desc_en: M30 BB Deep Return Optimized — BB extreme + MFI extreme reversal, branch-based exit by BB direction
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 极值 | 收盘价突破 BB 上轨或下轨 |
| ② | MFI 极值 | MFI > 85（做空）或 MFI < 15（做多） |
| ③ | K 线容差 | 2 根 K 线内 BB 触轨确认，提高精度 |

**判决规则：** BB 极值 + MFI 极值同时满足触发信号。

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 反转（弱反弹） | 0.5 BB 带宽回归 / MFI 回超卖线 / 30% 利润回撤 |
| ② | BB 同向（强反弹） | 按 BB 开口方向与 K 线同向分支决策 |

## 特别规则

- 数据源：全部指标从 DataFactory TA-Lib 读取
- 相比原版 m30_bb_deepreturn，优化版使用更严格的 MFI 阈值（85/15）
