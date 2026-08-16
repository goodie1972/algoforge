---
name: mfi_bb_m30_upgraded
magic: 661003

type: 超跌反弹
display: M30 MFI + BB Upgraded v16 — 超跌反弹升级版
desc: 收盘价超 BB 轨道入场，BB 开口扩 >5% 时禁同向入场（防趋势加速接飞刀）
desc_en: M30 MFI + BB Upgraded v16 — Close beyond BB band entry, BB expansion >5% disables same-direction entry
---

## 入场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 突破 | 收盘价超过 BB 上轨（做空）或下轨（做多） |
| ② | BB 开口过滤 | BB 开口扩张 >5% 时禁止同方向入场（防止趋势加速时接飞刀） |

**判决规则：** 收盘价突破 BB 轨道 + BB 开口未过度扩张时触发信号。

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | BB 反转回归 | 价格回归 BB 中轨或反向轨道 |
| ② | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |
| ③ | 硬止损 | 亏损超过 hard_mult × ATR |

## 特别规则

- 相比优化版，升级版增加 BB 开口扩张过滤，防止趋势加速段入场
- 数据源：全部指标从 DataFactory TA-Lib 读取
