---
name: m30_bb_deepreturn_optimized
magic: 661102
type: Counter-Trend
display_en: M30 BB Deep Return — Bollinger Deep Reversion
desc_en: M30 Bollinger deep reversion, RSI+MFI oversold/overbought entry, triple-branch exit
---

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
## Data Source
- Dependencies: `close`, `rsi`, `mfi`, `bb`, `atr`
