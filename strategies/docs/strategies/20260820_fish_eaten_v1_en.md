---
name: fish_eaten
magic: 661301
type: Price Reversion (Counter-Trend)
display_en: fish_eaten v2 — M30 Price Reversion Strategy
desc_en: Gate + 3-layer filter entry, RSI/MFI dual-extreme fish exit, M30 timeframe
---

## Entry Logic
### Gate (Pre-conditions)
| # | Condition | Description |
| --- | --- | --- |
| ① | ADX > 20 | Trending market, not ranging |
| ② | \|+DI − -DI\| > 5 | Clear trend direction |
### Three-Layer Filter (Long: −DI > +DI)
| Layer | Condition | Description |
| --- | --- | --- |
| 1 | RSI < 30 **and** MFI < 25 | Oversold confirmation |
| 2 | close ≤ BB lower band + 5 | Price near BB lower band |
| 3 | BB mid-band direction down | MA trend down, waiting for reversion |
### Three-Layer Filter (Short: +DI > −DI)
| Layer | Condition | Description |
| --- | --- | --- |
| 1 | RSI > 70 **and** MFI > 75 | Overbought confirmation |
| 2 | close ≥ BB upper band − 5 | Price near BB upper band |
| 3 | BB mid-band direction up | MA trend up, waiting for reversion |
## Exit Logic
### Fish Exit (Primary)
| Direction | Trigger | Description |
| --- | --- | --- |
| **Long** | RSI≥70 **and** MFI≥75 **both reached** → either leaves (RSI<70 or MFI<75) → and close < BB upper band − offset | Eats the full upside move |
| **Short** | RSI≤30 **and** MFI≤25 **both reached** → either leaves (RSI>30 or MFI>25) → and close > BB lower band + offset | Eats the full downside move |
### Time Stop (Backstop)
- When one indicator reaches its extreme, if the other does not within **48 bars (M30 = 24 hours)** → force close
- Prevents trades from waiting forever for both indicators to hit extremes
## Backtest Results
### Best Parameters
| Parameter | Value | Description |
| --- | --- | --- |
| ADX_GATE | 20 | Gate threshold |
| DI_DIFF_GATE | 5 | DI difference gate |
| BB_EXIT_OFFSET | 8 | Fish exit offset |
| TIME_STOP_BARS | 48 | Time stop bar count |
### Performance
| Metric | Value |
| --- | --- |
| Net PnL | +$346 (+3.46%) |
| Trades | 26 |
| Win Rate | 62% |
| Max Hold | 48 bars (24 hours) |
### Parameter Sensitivity
- **ADX**: 20/22 similar performance, 25 slightly worse
- **DI**: 5 and 10 show no difference
- **BB**: 8/10 better than 5
- **TS**: 48 is the best balance point (TS=12 cuts everything off; without TS dead trades remain)
## Data Source
- All indicators from DataFactory TA-Lib
- Dependencies: `close`, `rsi`, `mfi`, `adx`, `pdi`, `ndi`, `bb`, `bb_mid_direction`
## Risk Control
- Fixed 0.01 lots
- 1.5×ATR wide stop backstop (normally never triggered)
- Fish exit manages profit, no take-profit lock
