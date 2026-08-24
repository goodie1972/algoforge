---
name: m30_followave
magic: 661402

type: 趋势跟踪
display: M30 FollowAve — Stoch+BBI+BB 趋势跟踪（带 Trailing Stop）
display_en: M30 FollowAve — Stoch+BBI+BB Trend Following (w/ Trailing Stop)
desc: M30 趋势跟踪，±DI 门禁 + Stoch 金叉/死叉 + BBI + BB 中轨 + 2.0×ATR trailing stop
desc_en: M30 trend-following with ±DI gate, Stoch cross, BBI, BB mid, and 2.0×ATR trailing stop
---

## 入场逻辑

### 门禁（前置条件）

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | \|+DI − -DI\| > 5 | 趋势方向明确 |
| ② | +DI > −DI = 多头，−DI > +DI = 空头 | 趋势方向 |

### 三层筛子（做多：+DI > −DI）

| 层 | 条件 | 说明 |
|:--:|:----|:----|
| 第1层 | close > BBI | 价格在均线簇上方 |
| 第2层 | Stoch K > D（金叉）且 K < 80 | 动量向上，但未超买 |
| 第3层 | close ≥ BB 中轨 | 价格在布林带中轨之上 |

### 三层筛子（做空：−DI > +DI）

| 层 | 条件 | 说明 |
|:--:|:----|:----|
| 第1层 | close < BBI | 价格在均线簇下方 |
| 第2层 | Stoch K < D（死叉）且 K > 20 | 动量向下，但未超卖 |
| 第3层 | close ≤ BB 中轨 | 价格在布林带中轨之下 |

## 出场逻辑

### Trailing Stop（主要出场，2.0×ATR）

| 方向 | 条件 | 说明 |
|:---:|:----|:----|
| **做多** | close < 最高点 − 2.0×ATR | 从最高点回撤止盈 |
| **做空** | close > 最低点 + 2.0×ATR | 从最低点反弹止盈 |

### 趋势反转出场（辅助出场）

| 方向 | 条件 |
|:---:|:----|
| 做多 | close < BBI 连续 **3 根** K 线 |
| 做空 | close > BBI 连续 **3 根** K 线 |

### BB 硬止损（兜底）

| 方向 | 条件 |
|:---:|:----|
| 做多 | close < BB 下轨 |
| 做空 | close > BB 上轨 |

## 回测结果

**最佳参数：M30 + Stoch5 + 确认3根 + DI门禁=5 + Trail=2.0×ATR**

| 指标 | 值 |
|:----|:---|
| 净 PnL | +$658 (+6.58%) |
| 交易笔数 | 304 |
| 胜率 | 37% |
| 盈亏比 | 2.20 |
| 最大赢利 | +$154 |
| 最大亏损 | -$86 |

## 数据源

- 全部指标从 DataFactory TA-Lib 读取
- 依赖指标：`close`, `bbi`, `stoch_5_3_3`, `bb`, `bb_mid_direction`, `pdi`, `ndi`, `atr`

## 风控

- 固定 0.01 手
- 3.0×ATR 宽止损兜底（Trailing stop 和 BB 硬止损是主要出场）