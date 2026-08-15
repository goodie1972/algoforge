---
name: sanqing_h1_original
magic: 880101

type: 趋势
display: H1 SanQing 原始版
desc: 6因子评分(EMA/BB/RSI/ATR/成交量) + ATR追踪止损
desc_en: 6-factor scoring (EMA/BB/RSI/ATR/Volume) + ATR trailing stop
---

## 评分因子

### BUY（做多）
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| 1 | EMA趋势 | +1 | EMA9 > EMA21 |
| 2 | BB下轨 | +1 | close ≤ BB下轨 |
| 3 | RSI超卖 | +1 | RSI ≤ 30 |
| 4 | RSI动量 | +1 | RSI ≤ 50 |
| 5 | ATR高波动 | +1 | ATR/价格 > 0.3% 且 close > SMA14 |
| 6 | 成交量放量 | +1 | volume > vol_sma×1.3 且 close > 前一根 |

### SELL（做空）
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| 1 | EMA趋势 | +1 | EMA9 < EMA21 |
| 2 | BB上轨 | +1 | close ≥ BB上轨 |
| 3 | RSI超买 | +1 | RSI ≥ 70 |
| 4 | RSI动量 | +1 | RSI > 50 |
| 5 | ATR高波动 | +1 | ATR/价格 > 0.3% 且 close < SMA14 |
| 6 | 成交量放量 | +1 | volume > vol_sma×1.3 且 close < 前一根 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR追踪止损 | 4.0 ATR 回撤 |
| ② | ATR硬止损 | 2.5 ATR |

## 特别规则

- 固定阈值 4 分入场
- SL/TP 极宽（2.5 ATR / 超大 TP），出场全权交给 check_ema20_exit
- 无利润回撤止盈、无保本出场、无门禁、无新闻过滤
- 数据源: 全部指标从 DataFactory 读取