---
name: momentum_pulse_pro
magic: 661301
type: Counter-Trend
display_en: Momentum Pulse PRO — 7-Dimension Multi-Factor Scoring + Three-Tier TP Exit
desc_en: M30 7-dimension multi-factor scoring system, three-tier TP phased exit
---

**Timeframe:** M30

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
## Risk Control
- Directional Edge: Triggered only when the dominant direction's score is strictly higher than the other side's and ≥threshold
- Initial Stop: 1.5×ATR (order-level SL, also serves as the runtime hard stop)
- Trailing: Exit when peak pullback exceeds 1.5×ATR
- Three-Tier TP Phased Exit: TP1/TP2 marked for partial exits; TP3 (5.0×ATR) closes everything
- Max Positions: 1 (STRATEGY_POOL config)
## Parameter Reference
| Parameter | Value | Description |
|---|---|---|
| score_threshold | 6 | 7-dimension scoring trigger threshold (≥6/7) |
| AMC strength threshold | >0.3 / <−0.3 | Scoring threshold for Adaptive Momentum Composite |
| tp1_atr / tp2_atr / tp3_atr | 1.5 / 3.0 / 5.0 | ATR multipliers for the three-tier TP |
| sl_atr | 1.5 | Initial stop ATR multiplier |
| trail_atr | 1.5 | Trailing ATR multiplier |
| ADX trend threshold | 22 | Market state threshold for factor ⑥ |
| Volume confirmation multiplier | 1.2 | Factor ⑤: current volume > average of previous 20 bars ×1.2 |
## Special Rules
- AMC = (RSI_norm + MACD_norm + ROC_norm) / 3, the average of the three normalized items
- Source: TradingView Momentum Pulse PRO (Adaptive Momentum Composite + Multi-Dimension Consensus)
- Time Stop: hold the position for at most 40 bars
- Data Source: All indicators are read from DataFactory TA-Lib
