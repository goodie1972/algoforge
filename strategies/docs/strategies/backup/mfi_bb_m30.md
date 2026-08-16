---
name: mfi_bb_m30
magic: 661001
status: backup

type: 均值回归/双模
display: M30 MFI + 布林带均值回归策略
desc: 以 ADX=25 分界趋势/震荡模式，MFI 极端值 + BB 触轨入场、按趋势/逆趋势分支出场的 MFI 均值回归策略
desc_en: M30 MFI + Bollinger Bands — ADX=25 dual-mode, MFI extreme + BB touch entry
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 触轨 | 收盘价触及 BB 上轨或下轨 |
| ② | MFI 极值 | MFI > 80（做空）或 MFI < 20（做多） |
| ③ | ADX 模式判断 | ADX < 25 震荡模式，ADX ≥ 25 趋势模式 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 顺势出场 | 价格到达另一 BB 轨道或 MFI 到另一极端 |
| ② | 逆势出场 | 价格回归 BB 中轨或半带宽处 |

## 备注

- 后备策略，已从活跃池中移除
- 优化版 mfi_bb_m30_optimized 和升级版 mfi_bb_m30_upgraded 已替代此策略
- 文件版本: 20260629_mfi_bb_m30.py, 20260629_mfi_bb_m30_v1.py, 20260630_mfi_bb_m30_v1.py
