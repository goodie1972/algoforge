---
name: sanqing_h1
magic: 880107
type: Trend
display_en: H1 SanQing Original
desc_en: EMA9/21 Trend + ATR14 Scoring + Dual Take-Profit
---

## Scoring Factors
| # | Factor | Score | Description |
|---|---|---|---|
| 1 | Uptrend | +2 | EMA9 > EMA21 |
| 2 | EMA Golden Cross | +1 | EMA9 crosses above EMA21 |
| 3 | Pullback to EMA9 | +2 | low ≤ EMA9×1.002 and close > EMA9 |
| 4 | Body>1ATR | +1 | Body length exceeds 1× ATR |
| 5 | Volume Surge | +1 | Volume > average volume ×1.3 |
| 6 | Engulfing Pattern | +2 | Body median ≥1.5 and body/previous high ≥1.5 and body occupies ≥50% of the candle |
| 1 | Downtrend | +2 | EMA9 < EMA21 |
| 2 | EMA Death Cross | +1 | EMA9 crosses below EMA21 |
| 3 | Pullback to EMA9 | +2 | high ≥ EMA9×0.998 and close < EMA9 |
| 4 | Body>1ATR | +1 | Body length exceeds 1× ATR |
| 5 | Volume Surge | +1 | Volume > average volume ×1.3 |
| 6 | Engulfing Pattern | +2 | Body median ≥1.5 and body/previous high ≥1.5 and body occupies ≥50% of the candle |
## Exit Logic
| # | Condition | Description |
|---|---|---|
| ① | Profit Pullback TP | Peak pullback 25% |
| ② | ATR Trailing TP (trail) | 1.0 ATR |
| ③ | ATR Hard Stop (hard) | 2.0 ATR |
## Special Rules
- Threshold: =4 when ADX>20, =3 when ADX≤20
- Position Gate: top 10% of the 60-bar range blocks longs, bottom 10% blocks shorts
- Data Source: All indicators are read from DataFactory TA-Lib
