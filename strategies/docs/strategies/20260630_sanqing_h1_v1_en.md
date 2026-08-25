---
name: sanqing_h1
magic: 880107
type: Trend
display_en: H1 SanQing Original
desc_en: EMA9/21 Trend + ATR14 Scoring + Dual Take-Profit
---

**Timeframe:** H1

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
## Risk Control
- Position Gate: Top 10% of the 60-bar range blocks longs, bottom 10% blocks shorts (qualifying signals are zeroed out directly)
- Breakeven Exit: Close when the price returns to within ±0.05×ATR of cost after reaching ≥0.3×ATR profit
- Hard Stop: Close when the loss exceeds hard_mult × ATR (with-trend 4.0 / counter-trend 2.0 / ranging 3.0); order-level SL attached accordingly
- Adaptive Profit Pullback TP: Relaxed to 50% when peak <1.0×ATR, 40% for 1.0~2.0×ATR, otherwise 25% (further relaxed to 50% when ADX>25)
- Trailing TP: Trail multiplier locked at entry (with-trend 2.5 / counter-trend 1.0 / ranging 1.5); exit when the drop from peak exceeds multiplier ×ATR
- Max Positions: 1 (STRATEGY_POOL config)
## Parameter Reference
| Parameter | Value | Description |
|---|---|---|
| score_threshold | 3 | Base scoring threshold (used when ADX≤20) |
| ADX>20 threshold | 4 | Trending-market scoring threshold (effective when ADX>20) |
| adx_threshold | 20 | ADX trend/ranging boundary |
| p_trailing_atr | 1.0 | ATR trailing take-profit base multiplier |
| p_hard_atr | 2.0 | Hard stop ATR base multiplier |
| profit_drawdown_pct | 0.25 | Base ratio for profit pullback TP (adaptively relaxed to 50%/40% for small-profit trades) |
## Special Rules
- Threshold: =4 when ADX>20, =3 when ADX≤20
- Position Gate: top 10% of the 60-bar range blocks longs, bottom 10% blocks shorts
- Data Source: All indicators are read from DataFactory TA-Lib
