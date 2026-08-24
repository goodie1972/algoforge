---
name: gold_auto_research
magic: 880306

type: ML
display: Gold-AutoResearch — H1 实盘策略
display_en: Gold-AutoResearch — H1 Live Trading Strategy
desc: H1 4因子共识投票策略 + 高位拦截(price_position>0.88且偏离EMA21>4×ATR禁BUY)
desc_en: H1 Four-Factor Consensus Voting Strategy: Signals are triggered only when all conditions are consistent.
---

## 评分因子

### BUY（做多）
### BUY (Long)
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | 趋势 | +1 | H1 EMA10 > EMA20 |
| ② | 动量 | +1 | MACD(12,26,9) + Stoch(14,3,3) 同时看多 |
| ③ | 波动活性 | +1 | ADX>20 或 ATR 高于 SMA20 |
| ④ | 安全 | +1 | RSI(10) 未超买 + 价格未在 BB 上轨外 |

### SELL（做空）
### SELL (Short)
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | 趋势 | +1 | H1 EMA10 < EMA20 |
| ② | 动量 | +1 | MACD(12,26,9) + Stoch(14,3,3) 同时看空 |
| ③ | 波动活性 | +1 | ADX>20 或 ATR 高于 SMA20 |
| ④ | 安全 | +1 | RSI≤35 时独立封空，防止接近超卖区开空 |

**判决规则：**** 4 个因子全部一致才触发信号（AND 逻辑），缺少任一因子不交易。

**Judgment Rule:** ** 4 个因子全部一致才触发信号（AND 逻辑），缺少任一因子不交易。

## 出场逻辑

## Exit Logic

| # | 条件 | 说明 |  |
|:-:|:----|:----|
| ① | Breakeven Exit | After reaching ≥0.3ATR profit, returns near breakeven |  |
| ② | Profit Pullback TP | Peak profit retraces 25% (relaxed to 50% when ADX>25) |  |
| ③ | ATR Moving TP | Retraces more than trail_mult × ATR from peak |  |
| ④ | Hard Stop | Loss exceeds hard_mult × ATR (with-trend 3.0×ATR, against-trend 2.0×ATR) |  |

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 保本出场 | 走过 ≥0.3ATR 盈利后回到成本附近 |
| ② | 利润回撤止盈 | 峰值利润回撤 25%（ADX>25 时放宽至 50%） |
| ③ | ATR 移动止盈 | 从最高点回落超过 trail_mult × ATR |
| ④ | 硬止损 | 亏损超过 hard_mult × ATR（顺势 3.0×ATR，逆势 2.0×ATR） |

## 特别规则

- H4 SMA50 趋势门禁：H4 下行禁 BUY，H4 上行禁 SELL
- 数据源：全部指标从 DataFactory TA-Lib 读取

## Special Rules

- H4 SMA50 趋势门禁：H4 下行禁 BUY，H4 上行禁 SELL
- 数据源：全部指标从 DataFactory TA-Lib 读取
