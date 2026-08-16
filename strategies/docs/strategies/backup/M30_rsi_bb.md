---
name: M30_rsi_bb
status: backup
version: historical

type: 反转
display: M30 RSI + 布林带均值回归（历史版本）
desc: M30 RSI+布林带均值回归策略的历史版本集合，已被 v1 版本替代
desc_en: M30 RSI + Bollinger Bands Mean Reversion (historical versions)
---

## 说明

此策略在 backup 目录中存在多个历史演进版本：
- `20260607_M30_rsi_bb.py` — 早期版本
- `20260608_v1_M30_rsi_bb.py` — v1 版本
- `20260611_m30_rsi_v4.py` — v4 版本
- `20260612_m30_rsi_v4.py` — v4 修正版
- `20260615_m30_rsi_v5.py` — v5 版本
- `20260607_M30_rsi_bb.py` — 早期备份

当前活跃版本为 `20260630_M30_rsi_bb_v1.py`，详见 [M30_rsi_bb.md](../M30_rsi_bb.md)。

## 入场/出场逻辑

参见当前活跃版本的说明文档。历史版本的核心逻辑相同，区别在于评分因子权重和阈值参数的演进。

## 备注

- 后备策略，已从活跃池中移除
- 所有历史版本均已被 v1 版本替代
