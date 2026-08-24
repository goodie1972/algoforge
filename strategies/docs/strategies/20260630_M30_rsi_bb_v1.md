---
name: M30_rsi_bb
magic: 660707

type: 反转
display: M30 RSI + 布林带均值回归 — 7因子评分系统
display_en: M30 RSI + Bollinger Bands Mean Reversion — 7-Factor Score System
desc: M30 RSI+布林带均值回归，7因子评分系统，双重止盈出场 + 动态利润回撤止盈
desc_en: M30 RSI + Bollinger Bands Mean Reversion, 7-Factor Scoring System, Dual Take-Profit Exit
---

## 评分因子

### BUY（做多）
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | M30 trend | +1 | M30 SMA14 上升趋势 |
| ② | BB 底部位置 | +1 | 价格进入 BB 下轨 10% 区间内 |
| ③ | RSI 超卖 | +1~+2 | RSI<35 得+1，RSI<25 得+2 |
| ④ | RSI 方向 | +1 | M30 RSI 连续 3 根向上 |
| ⑤ | DI 强度 | +1 | +DI - -DI > 10 确认单边势 |
| ⑥ | 成交量确认 | +1 | 成交量 > SMA20×1.3 且阳线 |
| ⑦ | K线形态 | +1 | 早晨之星/锤子/刺透等反转形态 |

### SELL（做空）
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | M30 trend | +1 | M30 SMA14 下降趋势 |
| ② | BB 顶部位置 | +1 | 价格进入 BB 上轨 10% 区间内 |
| ③ | RSI 超买 | +1~+2 | RSI>65 得+1，RSI>75 得+2 |
| ④ | RSI 方向 | +1 | M30 RSI 连续 3 根向下 |
| ⑤ | DI 强度 | +1 | -DI - +DI > 10 确认单边势 |
| ⑥ | 成交量确认 | +1 | 成交量 > SMA20×1.3 且阴线 |
| ⑦ | K线形态 | +1 | 黄昏之星/射击之星/乌云盖顶等反转形态 |

**判决规则：** 评分 ≥4 直接开仓，=3 需差 ≥2。H1 MA20 趋势门禁拦截反向信号，但 BB 极值+RSI 极端区允许放过。

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 保本出场 | 走过 ≥0.3ATR 盈利后回到成本附近 |
| ② | 利润回撤止盈 | 峰值利润回撤 25%（ADX>25 时放宽至 50%） |
| ③ | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR；盈利时 +DI/-DI > 10 跳过止盈 |
| ④ | 硬止损 | 亏损超过 hard_mult × ATR |
| ⑤ | 盈利平仓冷却 | 盈利出场后同方向 30 分钟内不再开仓 |

**出场乘数：** 顺势（与 MA14 同向）trail=1.5×ATR / hard=3.0×ATR，逆势 trail=1.0×ATR / hard=2.0×ATR，震荡 trail=1.2×ATR / hard=2.5×ATR。

## 特别规则

- ADX>28 趋势门禁已移除（2026-06-30）
- H1 MA20 趋势门禁：H1 下行禁 BUY，H1 上行禁 SELL，但 BB 极值+RSI 极端区允许反向交易
- 数据源：全部指标从 DataFactory TA-Lib 读取
