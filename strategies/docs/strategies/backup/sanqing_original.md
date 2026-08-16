---
name: sanqing_original
magic: 880201
status: backup

type: 多策略调度器
display: 三清 M5 四策略调度器（原始版移植）
desc: 移植自 caoruihua/sanqing-ea 的 M5 四策略调度器(扩张跟随>回调>趋势延续>针形反转)，EMA9/21+ATR14 基础指标
desc_en: SanQing Original — M5 four-strategy dispatcher (expansion/pullback/trend-continuation/pin-reversal)
---

## 入场逻辑

四策略调度器按优先级触发：

| 优先级 | 策略 | 说明 |
|:-:|:----|:----|
| ① | 扩张跟随 | 趋势扩张时顺势入场 |
| ② | 回调 | 趋势回调后入场 |
| ③ | 趋势延续 | 趋势延续确认入场 |
| ④ | 针形反转 | 针形反转形态入场 |

**基础指标：** EMA9/21 + ATR14

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |

## 备注

- 后备策略，已从活跃池中移除
- 文件: sanqing_original_20260802.py
