---
name: stoch_trend_h1_upgraded
magic: 661204
status: backup

type: KDJ 周期/趋势
display: Stoch KDJ 周期策略（升级版）
desc: ADX>25 + KDJ 金叉/死叉 + BBI 方向三道闸门入场，按入场 K 极值分情况出场、不用硬止损的 KDJ 周期策略
desc_en: Stoch KDJ Cycle — ADX>25 + KDJ crossover + BBI direction triple-gate, no hard stop
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ADX 趋势确认 | ADX > 25 |
| ② | KDJ 交叉 | KDJ 金叉（做多）或死叉（做空） |
| ③ | BBI 方向 | BBI 方向与信号一致 |

**判决规则：** 三道闸门同时满足触发信号。

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | K 极值分支 | 按入场时 K 值极值分情况出场 |
| ② | 无硬止损 | 不使用硬止损，依靠 K 线形态出场 |

## 备注

- 后备策略，已从活跃池中移除
- 文件: stoch_trend_h1_upgraded_20260719.py
