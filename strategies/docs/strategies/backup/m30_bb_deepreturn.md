---
name: m30_bb_deepreturn
magic: 661101
status: backup

type: 超跌反弹
display: M30 BB DeepReturn 超跌反弹策略
desc: 布林带极值 + MFI 极值识别超跌反弹，按 BB 开口方向与 K 线是否同向分支决策出场的策略
desc_en: M30 BB DeepReturn — BB extreme + MFI extreme oversold rebound, branch-based exit
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 极值 | 收盘价突破 BB 上轨或下轨 |
| ② | MFI 极值 | MFI 极端值确认超跌 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 反转（弱反弹） | 0.5 BB 带宽回归 / MFI 回归 / 30% 利润回撤 |
| ② | BB 同向（强反弹） | 按 BB 开口方向与 K 线同向分支决策 |

## 备注

- 后备策略，已从活跃池中移除
- 优化版 m30_bb_deepreturn_optimized 已替代此策略
- 文件版本: 20260629_m30_bb_deepreturn.py, m30_bb_deepreturn_20260630.py
