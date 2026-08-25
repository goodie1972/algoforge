---
name: viprasol_sniper
magic: 661401
type: Other
display_en: Viprasol Sniper — 7-Factor Consensus + Multi-Level RR Exit
desc_en: M30 7-factor scoring system, multi-level RR exit (1R/2R/3R/4R/5R)
---

**Timeframe:** M30

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
## Risk Control
- Directional Edge: Triggered only when the dominant direction's score is strictly higher than the other side's and ≥threshold
- Initial Stop: 1.5×ATR (=1R), attached at order level
- Breakeven Shift: Move the order SL to the entry price after profit touches 1R
- Trailing: Exit triggered only when peak pullback exceeds 1.0×ATR and peak profit >0.5×ATR
- Hard Stop: Exit when the loss exceeds 1.5×ATR
- Max Positions: 1 (STRATEGY_POOL config)
## Parameter Reference
| Parameter | Value | Description |
|---|---|---|
| score_threshold | 4 | 7-factor trigger threshold (≥4/7) |
| sl_atr | 1.5 | Initial stop ATR multiplier (=1R) |
| breakeven_r | 1.0 | Breakeven activation level (move stop to entry price after 1R is hit) |
| rr_levels | [2, 3, 4, 5] | Step-by-step exit RR levels (2R/3R/4R/5R) |
| trail_atr | 1.0 | Trailing ATR multiplier |
| rsi_period / atr_period | 14 / 14 | Calculation periods for RSI, ATR |
| ema_fast / ema_slow | 9 / 21 | Fast/slow lines of EMA alignment |
## Special Rules
- Source: TradingView Viprasol Sniper Confluence Entry/Exit
- Entry confirmed on candle close
- Data Source: All indicators are read from DataFactory TA-Lib
