---
name: mfi_bb_m30_optimized
magic: 661002

type: 均值回归
display: M30 MFI + 布林带均值回归（优化版）
desc: MFI 极端值 + BB 触轨入场，按趋势/逆趋势分支出场，更严格 MFI 阈值（85/15）
desc_en: M30 MFI + Bollinger Bands Mean Reversion (Optimized) — stricter MFI thresholds, branch-based exit
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 触轨 | 收盘价触及 BB 上轨或下轨（2 根 K 线容差，更精确） |
| ② | MFI 极值 | MFI > 85（做空）或 MFI < 15（做多） |

**判决规则：** BB 触轨 + MFI 极值同时满足触发信号。

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 顺势出场 | 价格到达另一 BB 轨道或 MFI 到另一极端 |
| ② | 逆势出场 | 价格回归 BB 中轨或半带宽处 |

## 特别规则

- 相比原版 mfi_bb_m30，优化版使用更严格的 MFI 阈值（85/15 vs 80/20），信号质量更高
- 数据源：全部指标从 DataFactory TA-Lib 读取
