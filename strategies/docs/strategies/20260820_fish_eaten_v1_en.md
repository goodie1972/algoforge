---
name: fish_eaten
magic: 661301
type: Counter-Trend
display_en: fish_eaten v2 — M30 Price Reversion Strategy
desc_en: RSI-BB Trend — M30 price reversion strategy with ADX gate + 3-layer filter entry + fish exit
---

### Gate (Pre-conditions)

| # | Condition | Description |
|:-:|:---------|:------------|
| ① | ADX > 20 | Trending market, not ranging |
| ② | \|+DI − -DI\| > 5 | Clear trend direction |



### Three-Layer Filter (Long: −DI > +DI)

| Layer | Condition | Description |
|:----:|:---------|:------------|
| 1 | RSI < 30 **and** MFI < 25 | Oversold confirmation |
| 2 | close ≤ BB lower band + 5 | Price near BB lower band |
| 3 | BB mid-band direction down | MA trend down, waiting for reversion |



### Three-Layer Filter (Short: +DI > −DI)

| Layer | Condition | Description |
|:----:|:---------|:------------|
| 1 | RSI > 70 **and** MFI > 75 | Overbought confirmation |
| 2 | close ≥ BB upper band − 5 | Price near BB upper band |
| 3 | BB mid-band direction up | MA trend up, waiting for reversion |


## Entry Logic

## Exit Logic


|:---:|:---------|:----|

### Fish Exit (Primary)

| Direction | Trigger | Description |
|:--------:|:--------|:------------|
| **Long** | RSI≥70 **and** MFI≥75 **both reached** → either leaves (RSI<70 or MFI<75) → and close < BB upper band − offset | Capture the full upside move |
| **Short** | RSI≤30 **and** MFI≤25 **both reached** → either leaves (RSI>30 or MFI>25) → and close > BB lower band + offset | Capture the full downside move |



### Time Stop (Backstop)

- One indicator reaches extreme, the other does not within **48 bars (M30 = 24 hours)** → force close
- Prevents trades from waiting indefinitely for both indicators to reach extremes


### Best Parameters (M30, 2024-01 ~ 2026-08, 4889 bars)

|:----|:---|:----|


|:----|:---|



### Performance

| Metric | Value |
|:----|:---|
| Net PnL | +$346 (+3.46%) |
| Trades | 26 |
| Win Rate | 62% |
| Max Hold | 48 bars（24 hours） |



### Parameter Sensitivity

- **ADX**: 20/22 similar performance，25 slightly worse
- **BB**: 8/10 better than 5

### Performance

| Metric | Value |
|:----|:---|
| Net PnL | +$346 (+3.46%) |
| Trades | 26 |
| Win Rate | 62% |
| Max Hold | 48 bars（24 hours） |


- **ADX**: 20/22 similar performance，25 slightly worse
- **BB**: 8/10 better than 5

## Backtest Results


|:----|:---|:----|


| Metric | Value |
|:----|:---|
| Net PnL | +$346 (+3.46%) |
| Trades | 26 |
| Win Rate | 62% |
| Max Hold | 48 bars（24 hours） |





## Data Source

- All indicators from DataFactory TA-Lib
- Dependencies：`close`, `rsi`, `mfi`, `adx`, `pdi`, `ndi`, `bb`, `bb_mid_direction`



## Risk Control

- Fixed 0.01 lots