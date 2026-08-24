---
name: m30_bb_deepreturn_optimized
magic: 661102

type: 反转
display: M30 BB Deep Return — 布林带深回归
desc: M30 布林带深度回归，RSI+MFI 超卖超买入场，三重分支出场
desc_en: M30 BB deep reversion with RSI+MFI oversold/overbought entry, triple exit
---

## 入场逻辑

### 做多（超卖）

| # | 条件 | 说明 |
|:-:|:----|:----|
| 1 | RSI < 30 | 超卖 |
| 2 | MFI < 20 | 资金流极弱 |
| 3 | close ≤ BB 下轨 | 价格跌破下轨 |

### 做空（超买）

| # | 条件 | 说明 |
|:-:|:----|:----|
| 1 | RSI > 70 | 超买 |
| 2 | MFI > 80 | 资金流极强 |
| 3 | close ≥ BB 上轨 | 价格突破上轨 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 保本出场 | 走过 ≥0.3×ATR 盈利后回到成本附近 |
| ② | 趋势反转 | 多空方向改变 |
| ③ | 分支争议 | 多空条件同时出现 |

## 数据源

- 依赖指标：`close`, `rsi`, `mfi`, `bb`, `atr`
