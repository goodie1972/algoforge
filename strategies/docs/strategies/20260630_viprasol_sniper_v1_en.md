---
name: viprasol_sniper
magic: 661401
type: Other
display_en: Viprasol Sniper — 7-Factor Consensus + Multi-Level RR Exit
desc_en: H1 7-factor scoring system, multi-level RR exit (1R/2R/3R/4R/5R)
---

## Scoring Factors
| # | Factor | Score | Description |
|---|---|---|---|
| ① | Price vs EMA | +1 | close > EMA21 (VWAP substitute) |
| ② | RSI Direction | +1 | RSI(14) > 50 |
| ③ | MACD Direction | +1 | MACD(12,26,9) > 0 |
| ④ | EMA Alignment | +1 | EMA9 > EMA21 |
| ⑤ | ADX+DI | +1 | ADX>25 and +DI > -DI |
| ⑥ | Volume Confirmation | +1 | Volume > average of previous 20 bars × 1.2, and bullish candle |
| ⑦ | Secondary RSI | +1 | M15 RSI(14) > 50 |
| ① | Price vs EMA | +1 | close < EMA21 |
| ② | RSI Direction | +1 | RSI(14) < 50 |
| ③ | MACD Direction | +1 | MACD(12,26,9) < 0 |
| ④ | EMA Alignment | +1 | EMA9 < EMA21 |
| ⑤ | ADX+DI | +1 | ADX>25 and -DI > +DI |
| ⑥ | Volume Confirmation | +1 | Volume > average of previous 20 bars × 1.2, and bearish candle |
| ⑦ | Secondary RSI | +1 | M15 RSI(14) < 50 |
**Threshold:** Triggered at ≥4/7 factors, and the dominant direction's score must be higher than the other side's.
## Exit Logic
| # | Condition | Description |
|---|---|---|
| ① | TP1 (1R) | Move to breakeven after trigger |
| ② | TP2 (2R) | Exit at 2× risk profit |
| ③ | TP3 (3R) | Exit at 3× risk profit |
| ④ | TP4 (4R) | Exit at 4× risk profit |
| ⑤ | TP5 (5R) | Exit at 5× risk profit |
| ⑥ | ATR Trailing | Peak pullback exceeds 1.0 ATR and peak profit > 0.5ATR |
| ⑦ | Hard Stop | Loss exceeds 1.5 ATR |
**RR Exit:** At entry, 1R = SL_ATR × ATR is locked in; all TP levels are based on the locked 1R (not drifting with subsequent ATR).
## Special Rules
- Source: TradingView Viprasol Sniper Confluence Entry/Exit
- Entry confirmed on candle close
- Data Source: All indicators are read from DataFactory TA-Lib
