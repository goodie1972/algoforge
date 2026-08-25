---
name: momentum_pulse_pro
magic: 661301
type: Counter-Trend
display_en: Momentum Pulse PRO — 7-Dimension Multi-Factor Scoring + Three-Tier TP Exit
desc_en: H1 7-dimension multi-factor scoring system, three-tier TP phased exit
---

## Scoring Factors
| # | Factor | Score | Description |
|---|---|---|---|
| ① | AMC Strength | +1 | Adaptive Momentum Composite (RSI+MACD+ROC Z-score) > 0.3 |
| ② | Signal Alignment | +1 | MACD(12,26,9) is positive |
| ③ | RSI Zone | +1 | RSI(14) > 50 |
| ④ | Multi-Timeframe Alignment | +1 | H1 close > H1 MA20 |
| ⑤ | Volume Confirmation | +1 | Current volume > average of previous 20 bars × 1.2 |
| ⑥ | Market State | +1 | ADX>22 and +DI > -DI |
| ⑦ | No Exhaustion | +1 | BB position between 20%~80% (not extreme) |
| ① | AMC Strength | +1 | Adaptive Momentum Composite < -0.3 |
| ② | Signal Alignment | +1 | MACD(12,26,9) is negative |
| ③ | RSI Zone | +1 | RSI(14) < 50 |
| ④ | Multi-Timeframe Alignment | +1 | H1 close < H1 MA20 |
| ⑤ | Volume Confirmation | +1 | Current volume > average of previous 20 bars × 1.2 |
| ⑥ | Market State | +1 | ADX>22 and -DI > +DI |
| ⑦ | No Exhaustion | +1 | BB position between 20%~80% (not extreme) |
**Threshold:** A signal is triggered at ≥6/7 points, and the dominant direction's score must be higher than the other side's.
## Exit Logic
| # | Condition | Description |
|---|---|---|
| ① | TP1 (1.5 ATR) | Close 50% of the position after hit |
| ② | TP2 (3.0 ATR) | Close 30% of the position after hit |
| ③ | TP3 (5.0 ATR) | Close the remaining 20% of the position after hit |
| ④ | ATR Trailing | Peak pullback exceeds 1.5 ATR |
| ⑤ | Hard Stop | Loss exceeds 1.5 ATR |
## Special Rules
- AMC = (RSI_norm + MACD_norm + ROC_norm) / 3, the average of the three normalized items
- Source: TradingView Momentum Pulse PRO (Adaptive Momentum Composite + Multi-Dimension Consensus)
- Time Stop: hold the position for at most 40 bars
- Data Source: All indicators are read from DataFactory TA-Lib
