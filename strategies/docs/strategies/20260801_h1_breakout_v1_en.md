---
name: h1_breakout
magic: 880301
type: Breakout
display_en: H1 Breakout Trend Strategy
desc_en: H1 range breakout + ADX confirmation, EMA20 trailing stop, 6-point scoring system
---

## Scoring Factors

### BUY (Long)

| # | Factor | Score | Description |
|:------:|:------------------|:------:|:----------------------|
| 1 | Range breakout (upper) | +4 | close > range high of last 20 H1 bars |
| 2 | ADX trend confirmation | +3 | ADX > 25 confirms trending market |
| 3 | DI long direction | +2 | +DI > -DI |
| 4 | Above EMA9 | +1 | close > EMA9 (short-term trend up) |
| 5 | Above EMA20 | +1 | close > EMA20 (medium-term trend up) |

### SELL (Short)

| # | Factor | Score | Description |
|:------:|:------------------|:------:|:----------------------|
| 1 | Range breakout (lower) | +4 | close < range low of last 20 H1 bars |
| 2 | ADX trend confirmation | +3 | ADX > 25 confirms trending market |
| 3 | DI short direction | +2 | -DI > +DI |
| 4 | Below EMA9 | +1 | close < EMA9 (short-term trend down) |
| 5 | Below EMA20 | +1 | close < EMA20 (medium-term trend down) |

## Position Gate

| Condition | Action |
|:----|:----|
| Price in top 10% of 60-bar range | Long blocked (TOP-GATE) |
| Price in bottom 10% of 60-bar range | Short blocked (BOTTOM-GATE) |

## Exit Logic (EMA20 Trail + ADX Adaptive)

| Priority | Condition | Description |
|:----:|:----|:----|
| ① | Hard stop | Exit immediately when loss exceeds 1.5×ATR |
| ② | EMA20 trailing stop | BUY: bid < EMA20; SELL: ask > EMA20 |
| ③ | Profit drawdown protection | Position >600s, drawdown exceeds 50% of peak, and DI direction not aligned |
| ④ | DI flip exit | Position >300s, DI direction flipped for 2 consecutive bars |

### ADX Adaptive Trail Parameters

| ADX State | Trail Multiple | Take Profit Multiple |
|:---------|:--------:|:--------:|
| Range (ADX ≤ 25) | 1.0 ATR | 1.5 ATR |
| Medium (25 < ADX ≤ 35) | 1.5 ATR | 2.5 ATR |
| Strong Trend (ADX > 35) | 2.0 ATR | 3.5 ATR |

## Special Rules

- Signal threshold: score ≥ 6 triggers entry
- Range lookback: 20 bars
- Data source: All indicators from DataFactory TA-Lib
