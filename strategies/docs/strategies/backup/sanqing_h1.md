---
name: sanqing_h1
status: backup
version: historical

type: 多因子评分
display: SanQing H1（历史版本）
desc: 三清 H1 6因子评分策略的历史版本集合，已被 v1 版本替代
desc_en: SanQing H1 (historical versions)
---

## 说明

此策略在 backup 目录中存在多个历史演进版本：
- `20260607_H1_sanqing.py` — 早期版本
- `20260608_v1_H1_sanqing.py` — v1 版本
- `20260611_sanqing_h1_v4.py` — v4 版本
- `20260612_sanqing_h1_v5.py` — v5 版本
- `20260615_sanqing_h1_v6.py` — v6 版本
- `20260629_sanqing_h1_v6r.py` — v6r 版本

当前活跃版本为 `20260630_sanqing_h1_v1.py`，详见 [sanqing_h1.md](../sanqing_h1.md)。

## 入场/出场逻辑

参见当前活跃版本的说明文档。核心逻辑为 EMA9/21 + ATR14 + ADX + RSI + BB + K线形态 6因子评分。

## 备注

- 后备策略，已从活跃池中移除
- 所有历史版本均已被 v1 版本替代
