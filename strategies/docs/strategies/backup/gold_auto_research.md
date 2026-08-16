---
name: gold_auto_research
status: backup
version: historical

type: ML
display: Gold-AutoResearch H1（历史版本）
desc: Gold-AutoResearch H1 4因子共识投票策略的历史版本集合，已被 v1 版本替代
desc_en: Gold-AutoResearch H1 (historical versions)
---

## 说明

此策略在 backup 目录中存在多个历史演进版本：
- `20260607_H1_gold_autoresearch.py` — 早期版本
- `20260608_v1_H1_gold_autoresearch.py` — v1 版本
- `20260611_gold_autoresearch_h1_v5.py` — v5 版本

当前活跃版本为 `20260630_gold_auto_research_v1.py`，详见 [gold_auto_research.md](../gold_auto_research.md)。

## 入场/出场逻辑

参见当前活跃版本的说明文档。核心逻辑为 H1 4因子共识投票 + 高位拦截。

## 备注

- 后备策略，已从活跃池中移除
- 所有历史版本均已被 v1 版本替代
