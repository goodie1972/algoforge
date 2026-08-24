---
name: m30_vol_return
magic: 880302

type: 反转
display_en: M30 Volatility Mean Reversion
desc_en: M30 BB touch + ATR expansion + RSI divergence, take profit on return to middle band, limited recovery.
---

### BUY (Long)

### SELL (Short)



|:----|:----|

## Position Gate

|:----|:----|


## Exit Logic

| ① | Hard Stop | Exit immediately when loss exceeds 1.5×ATR |  |
| ② | BB Mid-Band TP | Exit when price reverts to Bollinger Band middle band |  |
| ③ | Profit Pullback Protection | Exit when position held >5 minutes and drawdown exceeds 60% of peak |  |
| ④ | ATR Trailing Stop | 1.2×ATR trailing stop |  |




## Special Rules

- Data source: All indicators from DataFactory TA-Lib