---
name: m30_vol_return
magic: 880302
type: Reversal
display_en: M30 Volatility Mean Reversion
desc_en: M30 BB touch + ATR expansion + RSI overbought/oversold, take profit on return to middle band, limited recovery
---

## Scoring Factors

### BUY (Long)

| # | Factor | Score | Description |
|:------:|:------------------|:------:|:----------------------|
| 1 | BB lower band touch | +4 | close ≤ BB lower band × 1.01 |
| 2 | RSI oversold | +3 | RSI(14) < 30 |
| 3 | RSI5 oversold (backup) | +2 | RSI(5) < 30 (when RSI14 not oversold) |
| 4 | ATR expansion | +2 | Current ATR > 5-bar average × 1.2 |
| 5 | BB bandwidth expansion | +1 | BB bandwidth > 8.0 |
| 6 | Far from EMA21 | +1 | close < EMA21 (large deviation) |

### SELL (Short)

| # | Factor | Score | Description |
|:------:|:------------------|:------:|:----------------------|
| 1 | BB upper band touch | +4 | close ≥ BB upper band × 0.99 |
| 2 | RSI overbought | +3 | RSI(14) > 70 |
| 3 | RSI5 overbought (backup) | +2 | RSI(5) > 70 (when RSI14 not overbought) |
| 4 | ATR expansion | +2 | Current ATR > 5-bar average × 1.2 |
| 5 | BB bandwidth expansion | +1 | BB bandwidth > 8.0 |
| 6 | Far from EMA21 | +1 | close > EMA21 (large deviation) |

## Position Gate

| Condition | Action |
|:----|:----|
| Price in top 10% of 60-bar range | Long blocked (TOP-GATE) |
| Price in bottom 10% of 60-bar range | Short blocked (BOTTOM-GATE) |

## Exit Logic

| # | Condition | Description |
|:----:|:----|:----|
| ① | Hard stop | Exit immediately when loss exceeds 1.5×ATR |
| ② | BB mid-band TP | Exit when price reverts to Bollinger Band middle band |
| ③ | Profit drawdown protection | Exit when position held >5 minutes and drawdown exceeds 60% of peak |
| ④ | ATR trailing stop | 1.2×ATR trailing stop |

## Special Rules

- Signal threshold: score ≥ 6 triggers entry
- Recovery: at most 1 same-direction recovery (no extra lots)
- Dynamic SL/TP: stop loss 1.5×ATR, take profit BB mid-band or EMA21
- Data source: All indicators from DataFactory TA-Lib
