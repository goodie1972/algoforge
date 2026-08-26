---
name: m15_followave
magic: 661401
type: Trend-Following
display_en: M15 FollowAve — Stoch+BBI+BB Trend Following
desc_en: M15 trend following, ±DI gate + Stoch golden/death cross + BBI direction + BB mid-band confirmation, no trailing stop
---

**Timeframe:** M15

## Entry Logic
### Gate (Pre-conditions)
| # | Condition | Description |
| --- | --- | --- |
| ① | \|+DI − -DI\| > 5 | Clear trend direction |
| ② | +DI > −DI = Long, −DI > +DI = Short | Trend direction |
### Three-Layer Filter (Long: +DI > −DI)
| Layer | Condition | Description |
| --- | --- | --- |
| 1 | close > BBI | Price above MA cluster |
| 2 | Stoch K > D (golden cross) and K < 70 | Momentum up, not overbought |
| 3 | close ≥ BB mid-band | Price above BB mid-band |
### Three-Layer Filter (Short: −DI > +DI)
| Layer | Condition | Description |
| --- | --- | --- |
| 1 | close < BBI | Price below MA cluster |
| 2 | Stoch K < D (death cross) and K > 20 | Momentum down, not oversold |
| 3 | close ≤ BB mid-band | Price below BB mid-band |
## Exit Logic
### Trend Reversal Exit (Primary)
| Direction | Condition | Description |
| --- | --- | --- |
| **Long** | close < BBI for **3** consecutive candles | Trend reversal confirmed |
| **Short** | close > BBI for **3** consecutive candles | Trend reversal confirmed |
| Long | close < BB lower band | Price breaks below lower band, trend fully reversed |
| Short | close > BB upper band | Price breaks above upper band, trend fully reversed |
## Backtest Results
**Best Parameters: M15 + Stoch5 + 3 confirmation bars + DI gate=5 + no Trail**
| Metric | Value |
| --- | --- |
| Net PnL | +$403 (+4.03%) |
| Trades | 312 |
| Win Rate | 36% |
| Profit Factor | 2.09 |
| Max Win | +$154 |
| Max Loss | -$74 |
## Parameter Reference
| Parameter | Value | Description |
| --- | --- | --- |
| TIMEFRAME | M15 | Primary running timeframe |
| DI_GATE | 5 | ±DI difference gate |
| EXIT_CONFIRM_BARS | 3 | Confirmation candle count for trend reversal exit |
| TRAIL_ATR | 0 | No trailing stop used |
| STOCH_K_OVERBOUGHT / OVERSOLD | 70 / 20 | Stoch K overbought / oversold thresholds |
| FIXED_LOTS | 0.01 | Fixed lot size |
| MAX_SLIPPAGE | 30 | Max slippage |
## Data Source
- All indicators from DataFactory TA-Lib
- Dependencies: `close`, `bbi`, `stoch_5_3_3`, `bb`, `bb_mid_direction`, `pdi`, `ndi`, `atr`
## Risk Control
- Fixed 0.01 lots
- 3.0×ATR wide stop backstop (BB hard stop is the primary exit)
