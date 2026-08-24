---
name: multi_confluence_quant
magic: 661601

type: 评分
display_en: Multi-Confluence Quant — 14-Factor Composite Score
desc_en: H1: 14 technical indicator factor scores, signal triggered when ≥10/14.
---

### BUY (Long)
| ① | EMA Ribbon | +1 | EMA20 > EMA50 |
| ⑧ | Stoch RSI | +1 | Stoch RSI K > 50 |
| ⑨ | MACD | +1 | MACD(12,26) > 0 |

### SELL (Short)
| ① | EMA Ribbon | +1 | EMA20 < EMA50 |
| ⑧ | Stoch RSI | +1 | Stoch RSI K < 50 |
| ⑨ | MACD | +1 | MACD(12,26) < 0 |




## Exit Logic

| ① | Profit Pullback TP | Peak profit drawdown 25% (peak > 0.5 ATR) |  |
| ② | ATR Moving Trailing | Peak drawdown exceeds 1.5 ATR |  |
| ③ | Hard Stop | Loss exceeds 2.0 ATR |  |




## Special Rules

- Data source: All indicators from DataFactory TA-Lib