---
name: bakome_backup
magic: 777004
status: backup

type: ICT/价格行为
display: BAKOME GoldScalper 后备策略
desc: ICT FVG + Order Block + Silver Bullet 时段(London 8-10/NY 13-15)的黄金剥头皮后备策略
desc_en: BAKOME GoldScalper Backup — ICT FVG + OB + Silver Bullet session scalper
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | FVG 检测 | 检测 Fair Value Gap 缺口 |
| ② | Order Block | 确认 Order Block 区域 |
| ③ | 交易时段 | London 8-10 / NY 13-15 Silver Bullet 时段 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | FVG 填充 | 价格填补 FVG 缺口 |
| ② | ATR 止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 文件版本: 20260607_H1_bakome_backup.py, bakome_backup.py
