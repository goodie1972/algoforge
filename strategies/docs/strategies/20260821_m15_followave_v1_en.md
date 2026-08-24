---
name: m15_followave
magic: 661401
type: 趋势跟踪
display_en: M15 FollowAve — Stoch+BBI+BB Trend Following
desc_en: M15 trend-following strategy with ±DI gate, Stoch cross, BBI direction, and BB mid confirmation
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

### Trend Reversal Exit (Primary)

| Direction | Condition | Description |
|:--------:|:---------|:------------|
| **Long** | close < BBI for **3** consecutive candles | Trend-confirmed reversal |
| **Short** | close > BBI for **3** consecutive candles | Trend-confirmed reversal |


|:---:|:----|:----|

### BB Hard Stop (Backstop)

| Direction | Condition | Description |
|:--------:|:---------|:------------|
| Long | close < BB lower band | Price breaks below lower band, trend fully reversed |
| Short | close > BB upper band | Price breaks above upper band, trend fully reversed |



|:----|:---|

## Backtest Results


| Metric | Value |
|:----|:---|
| Net PnL | +$403 (+4.03%) |
| Trades | 312 |
| Win Rate | 36% |
| Profit Factor | 2.09 |
| Max Win | +$154 |
| Max Loss | -$74 |



## Data Source

- All indicators from DataFactory TA-Lib
- Dependencies：`close`, `bbi`, `stoch_5_3_3`, `bb`, `bb_mid_direction`, `pdi`, `ndi`, `atr`



## Risk Control

- Fixed 0.01 lots