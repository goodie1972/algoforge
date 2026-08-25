---
name: h1_breakout
magic: 880301
type: Breakout
display_en: H1 Breakout Trend Strategy
desc_en: H1 range breakout + ADX confirmation, EMA20 trailing stop, 6-point scoring system
---

**Timeframe:** H1

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

## Parameter Reference

| Parameter | Value | Description |
|:------------------|:------:|:----------------------|
| Range lookback period | 20 bars | Breakout range uses the high/low of the last 20 H1 bars |
| ADX trend gate | 25 | ADX > 25 confirms trending market (+3 points) |
| Entry score threshold | 6 points | Max 11 (breakout 4 + ADX 3 + DI 2 + EMA9/20 one each) |
| Hard stop | 1.5×ATR | p_hard_atr, also used for opening SL |
| Take profit | 1.5 / 2.5 / 3.5 ×ATR | Range (≤25) / Medium (25~35) / Strong trend (>35) |
| Trailing stop | 1.0 / 1.5 / 2.0 ×ATR | Adaptive across three ADX tiers (parallel with EMA20 trail) |
| Profit drawdown protection | Hold >600s and drawdown >50% and DI not aligned | _min_hold_seconds=600 |
| DI flip exit | Hold >300s | Requires next-bar confirmation |

## Risk Control

- Hard stop: 1.5×ATR, exit immediately when loss exceeds limit (highest priority)
- Position gate: within a 60-bar window, price in top 10% (price_position>0.90) blocks long (TOP-GATE); bottom 10% (<0.10) blocks short (BOTTOM-GATE), score zeroed
- Profit drawdown protection: exit only when held >600s, peak profit drawdown >50%, and DI direction not aligned (not shaken out while trend intact)
- DI flip exit: detected after holding >300s, requires next-bar confirmation before exiting, preventing false flips
- EMA20 trailing stop: exit when BUY bid<EMA20 / SELL ask>EMA20
- Max position: 1 order (STRATEGY_POOL config)

## Special Rules

- Signal threshold: score ≥ 6 triggers entry
- Range lookback: 20 bars
- Data source: All indicators from DataFactory TA-Lib
