---
name: bakome_backup_optimized
magic: 777006
status: backup

type: ICT/价格行为
display: BAKOME GoldScalper 优化版
desc: 交易时段扩至 10h(London 6-10 + NY 12-16)、FVG 检测放宽、ADX 自适应出场的 ICT 剥头皮策略
desc_en: BAKOME GoldScalper Optimized — extended 10h sessions, relaxed FVG, ADX adaptive exit
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | FVG 检测 | 放宽的 FVG 缺口检测条件 |
| ② | Order Block | 确认 Order Block 区域 |
| ③ | 交易时段 | London 6-10 + NY 12-16（扩展至 10 小时） |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ADX 自适应 | ADX 高时用宽松出场，ADX 低时用紧凑出场 |
| ② | ATR 止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 文件: bakome_backup_optimized_20260711.py
