---
name: multi_confluence_quant
magic: 661601

type: 评分
display: Multi-Confluence Quant — 14因子综合评分
display_en: Multi-Confluence Quant — 14-Factor Composite Score
desc: H1 14个技术指标因子评分，≥10/14触发信号
desc_en: H1: 14 technical indicator factor scores, signal triggered when ≥10/14.
---

## 评分因子

### BUY（做多）
### BUY (Long)
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | EMA Ribbon | +1 | EMA20 > EMA50 |
| ② | 长期趋势 | +1 | close > EMA200 |
| ③ | RSI 方向 | +1 | RSI(14) > 50 |
| ④ | ADX 趋势确认 | +1 | ADX > 20（多空均加分，表示有趋势） |
| ⑤ | 线性回归斜率 | +1 | 20 根线性回归斜率 > 0 |
| ⑥ | 成交量 | +1 | 成交量 > 前 20 根均值，且为阳线 |
| ⑦ | HTF 趋势 | +1 | H1 close > H1 EMA50 |
| ⑧ | Stoch RSI | +1 | Stoch RSI K > 50 |
| ⑨ | MACD | +1 | MACD(12,26) > 0 |
| ⑩ | 波动扩张 | +1 | ATR > ATR20 × 1.1，且做多方向占优 |
| ⑪ | BB 位置 | +1 | price_pos > 0.5（在上半区） |
| ⑫ | 结构突破 | +1 | close 为 20 根最高（HH20） |
| ⑬ | DI 方向 | +1 | +DI > -DI |
| ⑭ | RSI 过度延伸 | -1 | RSI > 70 时扣分（超买不追多） |

### SELL（做空）
### SELL (Short)
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | EMA Ribbon | +1 | EMA20 < EMA50 |
| ② | 长期趋势 | +1 | close < EMA200 |
| ③ | RSI 方向 | +1 | RSI(14) < 50 |
| ④ | ADX 趋势确认 | +1 | ADX > 20（多空均加分） |
| ⑤ | 线性回归斜率 | +1 | 20 根线性回归斜率 < 0 |
| ⑥ | 成交量 | +1 | 成交量 > 前 20 根均值，且为阴线 |
| ⑦ | HTF 趋势 | +1 | H1 close < H1 EMA50 |
| ⑧ | Stoch RSI | +1 | Stoch RSI K < 50 |
| ⑨ | MACD | +1 | MACD(12,26) < 0 |
| ⑩ | 波动扩张 | +1 | ATR > ATR20 × 1.1，且做空方向占优 |
| ⑪ | BB 位置 | +1 | price_pos < 0.5（在下半区） |
| ⑫ | 结构突破 | +1 | close 为 20 根最低（LL20） |
| ⑬ | DI 方向 | +1 | -DI > +DI |
| ⑭ | RSI 过度延伸 | -1 | RSI < 30 时扣分（超卖不做空） |

**阈值：** ≥10/14 = SIGNAL，≥11/14 = God-Tier。


## 出场逻辑

## Exit Logic

| # | 条件 | 说明 |  |
|:-:|:----|:----|
| ① | Profit Pullback TP | Peak profit drawdown 25% (peak > 0.5 ATR) |  |
| ② | ATR Moving Trailing | Peak drawdown exceeds 1.5 ATR |  |
| ③ | Hard Stop | Loss exceeds 2.0 ATR |  |

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 利润回撤止盈 | 峰值利润回撤 25%（峰值 > 0.5ATR） |
| ② | ATR 移动追踪 | 峰值回撤超过 1.5 ATR |
| ③ | 硬止损 | 亏损超过 2.0 ATR |

## 特别规则

- 覆盖趋势/动量/波动/成交量/结构 5 大类别
- 来源：TradingView Multi-Confluence Quant Crypto Engine [QuantSovereign]
- 数据源：全部指标从 DataFactory TA-Lib 读取

## Special Rules

- 覆盖趋势/动量/波动/成交量/结构 5 大类别
- 来源：TradingView Multi-Confluence Quant Crypto Engine [QuantSovereign]
- Data source: All indicators from DataFactory TA-Lib
