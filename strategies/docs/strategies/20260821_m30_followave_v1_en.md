---
name: m30_followave
magic: 661402
type: 趋势跟踪
display_en: M30 FollowAve — Stoch+BBI+BB Trend Following (w/ Trailing Stop)
desc_en: M30 trend-following with ±DI gate, Stoch cross, BBI, BB mid, and 2.0×ATR trailing stop
---

### Gate (Pre-conditions)

| # | Condition | Description |
|:-:|:---------|:------------|
| ① | \|+DI − -DI\| > 5 | Clear trend direction |
| ② | +DI > −DI = Long, −DI > +DI = Short | Trend direction |



### Three-Layer Filter (Long: +DI > −DI)

| Layer | Condition | Description |
|:----:|:---------|:------------|
| 1 | close > BBI | Price above MA cluster |
| 2 | Stoch K > D (golden cross) and K < 80 | Momentum up, not overbought |
| 3 | close ≥ BB mid-band | Price above BB mid-band |



### Three-Layer Filter (Short: −DI > +DI)

| Layer | Condition | Description |
|:----:|:---------|:------------|
| 1 | close < BBI | Price below MA cluster |
| 2 | Stoch K < D (death cross) and K > 20 | Momentum down, not oversold |
| 3 | close ≤ BB mid-band | Price below BB mid-band |


## Entry Logic

## Exit Logic


|:---:|:----|:----|

### Trailing Stop (Primary, 2.0×ATR)

| Direction | Condition | Description |
|:--------:|:---------|:------------|
| **Long** | close < peak − 2.0×ATR | Profit-taking on pullback from peak |
| **Short** | close > trough + 2.0×ATR | Profit-taking on bounce from trough |


|:---:|:----|

### Trend Reversal Exit (Secondary)

| Direction | Condition |
|:--------:|:---------|
| Long | close < BBI for **3** consecutive candles |
| Short | close > BBI for **3** consecutive candles |


|:---:|:----|

### BB Hard Stop (Backstop)

| Direction | Condition |
|:--------:|:---------|
| Long | close < BB lower band |
| Short | close > BB upper band |



|:----|:---|

## Backtest Results


| Metric | Value |
|:----|:---|
| Net PnL | +$658 (+6.58%) |
| Trades | 304 |
| Win Rate | 37% |
| Profit Factor | 2.20 |
| Max Win | +$154 |
| Max Loss | -$86 |



## Data Source

- All indicators from DataFactory TA-Lib
- Dependencies：`close`, `bbi`, `stoch_5_3_3`, `bb`, `bb_mid_direction`, `pdi`, `ndi`, `atr`



## Risk Control

- Fixed 0.01 lots