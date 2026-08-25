---
name: m30_vol_return
magic: 880302
type: Reversal
display_en: M30 Volatility Mean Reversion
desc_en: M30 BB touch + ATR expansion + RSI overbought/oversold, take profit on return to middle band, limited recovery
---

**Timeframe:** M30

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

## Parameter Reference

| Parameter | Value | Description |
|:------------------|:------:|:----------------------|
| Entry score threshold | 6 points | Max 11 (band touch 4 + RSI 3 + ATR 2 + bandwidth 1 + deviation 1) |
| ATR expansion multiple | 1.2 | Current ATR > last 5-bar ATR average ×1.2 counts as expansion |
| RSI oversold / overbought | 30 / 70 | RSI(14) priority, RSI(5) backup (+2 points) |
| BB bandwidth threshold | 8.0 | Width > 8.0 treated as volatility amplification (+1 point) |
| Band-touch buffer | lower ×1.01 / upper ×0.99 | Touch detection tolerance |
| Hard stop | 1.5×ATR | sl_atr_mult |
| Take profit | BB mid-band | Default fallback order: BB mid-band → EMA21 → 1.0×ATR |
| ATR trailing stop | 1.2×ATR | Actually uses p_trail_normal (tiers 0.8/1.2/1.8 as backup) |
| Profit drawdown protection | Hold >300s and drawdown >60% | Exit when peak profit give-back exceeds limit |
| Recovery | At most 1 time, lot multiplier 1.0 | Same-direction re-entry only, no extra lots |

## Risk Control

- Hard stop: 1.5×ATR (highest priority)
- Position gate: within a 60-bar window, price in top 10% (>0.90) blocks long (TOP-GATE); bottom 10% (<0.10) blocks short (BOTTOM-GATE), score zeroed
- Profit drawdown protection: exit when held >300s (5 minutes) and peak drawdown >60%, protecting floating profit from being given back
- ATR trailing stop: 1.2×ATR peak drawdown (BUY breaks below peak −1.2×ATR / SELL rises above trough +1.2×ATR)
- BB mid-band take profit: mean-reversion target, bank profits without chasing one-sided moves; falls back to 1.0×ATR target when no mid-band
- Recovery limit: at most 1 same-direction recovery without adding lots, preventing counter-trend averaging down
- Max position: 1 order (STRATEGY_POOL config)

## Special Rules

- Signal threshold: score ≥ 6 triggers entry
- Recovery: at most 1 same-direction recovery (no extra lots)
- Dynamic SL/TP: stop loss 1.5×ATR, take profit BB mid-band or EMA21
- Data source: All indicators from DataFactory TA-Lib
