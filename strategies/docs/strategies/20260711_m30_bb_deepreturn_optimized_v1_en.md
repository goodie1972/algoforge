---
name: m30_bb_deepreturn_optimized
magic: 661102
type: Counter-Trend
display_en: M30 BB Deep Return — Bollinger Deep Reversion
desc_en: M30 Bollinger deep reversion, RSI+MFI oversold/overbought entry, triple-branch exit
---

**Timeframe:** M30

## Entry Logic
### Long Entry (Oversold)
| # | Condition | Description |
|---|---|---|
| 1 | RSI < 30 | Oversold |
| 2 | MFI < 20 | Money flow extremely weak |
| 3 | close ≤ BB lower band | Price breaks below the lower band |
### Short Entry (Overbought)
| # | Condition | Description |
|---|---|---|
| 1 | RSI > 70 | Overbought |
| 2 | MFI > 80 | Money flow extremely strong |
| 3 | close ≥ BB upper band | Price breaks above the upper band |
## Exit Logic
| # | Condition | Description |
|---|---|---|
| ① | Breakeven Exit | After reaching ≥0.3×ATR profit, price returns near cost |
| ② | Trend Reversal | Long/short direction changed |
| ③ | Branch Conflict | Long and short conditions appear simultaneously |
## Risk Control
- Dynamic Threshold Gate: In trending markets (ADX>25), 2 points with-trend / 4 points counter-trend; in ranging markets (ADX≤25), 3 points for both directions
- BB Expansion With-Trend Block: When bandwidth ratio >1.05 with the bands opening upward, shorts are blocked if price is above the middle band and MFI is not declining (mirror rule blocks longs)
- Profit Close Cooling: No new position in the same direction within 900s after a profit exit; qualifying signals during the cooldown are zeroed out
- Breakeven Delay: Breakeven exit is not activated within 3600s after entry; the hard stop covers it
- Hard Stop: Exit when the loss exceeds 2.0×ATR(20), covering all positions
- Max Positions: 5 (STRATEGY_POOL config)
## Parameter Reference
| Parameter | Value | Description |
|---|---|---|
| mfi_oversold / mfi_overbought | 30 / 70 | MFI oversold/overbought thresholds |
| bb_period / bb_std | 20 / 2.0 | Bollinger Bands period and standard deviation multiplier |
| score_threshold / score_threshold_trending | 3 / 2 | Ranging-market threshold / trending-market with-trend threshold |
| adx_trend_threshold | 25 | ADX trend/ranging boundary |
| atr_volatility_threshold | 0.0025 | ATR volatility scoring threshold (ATR/close > 0.25%) |
| p_trailing_atr_bull / p_trailing_atr_bear | 1.5 / 1.0 | ATR trailing TP multipliers for BB with-trend / counter-trend branches |
| p_hard_atr | 2.0 | Hard stop ATR multiplier |
| profit_drawdown_pct | 0.50 | Profit pullback TP ratio for BB counter-trend branch (tightened to 35% when peak >$10) |
| mfi_reversal_pct | 15.0 | MFI reversal TP threshold for BB with-trend branch (%) |
| bounce_bb_width | 0.5 | Rebound target for BB counter-trend branch = 0.5 × current bandwidth |
| _exit_cooldown_seconds | 900 | Cooldown in the same direction after a profit close (seconds) |
| breakeven_delay_seconds | 3600 | Delayed activation of breakeven exit (seconds) |
## Data Source
- Dependencies: `close`, `rsi`, `mfi`, `bb`, `atr`
