---
name: m30_bb_deepreturn_optimized
magic: 661102
type: 反转
display_en: M30 BB Deep Return — Oversold Deep Reversion
desc_en: M30 BB deep reversion with RSI+MFI oversold/overbought entry, triple exit
---

### Long Entry (Oversold)

| # | Condition | Description |
|:-:|:---------|:------------|
| 1 | RSI < 30 | Oversold |
| 2 | MFI < 20 | Money flow extremely weak |
| 3 | close ≤ BB lower band | Price breaks below lower band |



### Short Entry (Overbought)

| # | Condition | Description |
|:-:|:---------|:------------|
| 1 | RSI > 70 | Overbought |
| 2 | MFI > 80 | Money flow extremely strong |
| 3 | close ≥ BB upper band | Price breaks above upper band |


## Entry Logic


## Exit Logic

| # | Condition | Description |
|:-:|:---------|:------------|
| ① | Breakeven exit | After ≥0.3×ATR profit, price returns near cost |
| ② | Trend reversal | Long/short direction changed |
| ③ | Branch conflict | Both long and short conditions met |



## Data Source

- Dependencies：`close`, `rsi`, `mfi`, `bb`, `atr`