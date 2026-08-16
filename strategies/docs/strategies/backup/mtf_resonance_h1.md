---
name: mtf_resonance_h1
magic: 660801
status: backup

type: 多周期共振/形态
display: MTF 共振策略
desc: H1 K 线收盘后检测 TA-Lib 形态 + 质量过滤器，同窗口 M15 有同向信号则共振开仓的多周期策略
desc_en: MTF Resonance — H1 TA-Lib pattern + M15 same-direction confirmation
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | H1 形态检测 | H1 K 线收盘后检测 TA-Lib 识别的 K 线形态 |
| ② | 质量过滤 | 形态质量过滤器确认 |
| ③ | M15 共振 | 同窗口 M15 出现同向信号 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |
| ② | 硬止损 | 亏损超过 hard_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 文件版本: 20260629_mtf_resonance_h1.py, mtf_resonance_h1.py
