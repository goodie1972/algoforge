---
name: m30_followave
magic: 661402
type: Trend-Following
display_en: M30 FollowAve — Stoch+BBI+BB Trend Following (with Trailing Stop)
desc_en: M30 trend following, ±DI gate + Stoch golden/death cross + BBI + BB mid-band + 2.0×ATR trailing stop
---

**Timeframe:** M30

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
| Direction | Condition | Description |
| --- | --- | --- |
| **Long** | close < peak − 2.0×ATR | Take profit on drawdown from peak |
| **Short** | close > trough + 2.0×ATR | Take profit on rebound from trough |
### Trend Reversal Exit (Secondary)
| Direction | Condition |
| --- | --- |
| Long | close < BBI for **3** consecutive candles |
| Short | close > BBI for **3** consecutive candles |
| Long | close < BB lower band |
| Short | close > BB upper band |
## Backtest Results
**Best Parameters: M30 + Stoch5 + 3 confirmation bars + DI gate=5 + Trail=2.0×ATR**
| Metric | Value |
| --- | --- |
| Net PnL | +$658 (+6.58%) |
| Trades | 304 |
| Win Rate | 37% |
| Profit Factor | 2.20 |
| Max Win | +$154 |
| Max Loss | -$86 |
## Parameter Reference
| Parameter | Value | Description |
| --- | --- | --- |
| TIMEFRAME | M30 | Primary running timeframe |
| DI_GATE | 5 | ±DI difference gate |
| EXIT_CONFIRM_BARS | 3 | Confirmation candle count for trend reversal exit |
| TRAIL_ATR | 2.0 | 2.0×ATR trailing stop (take profit on drawdown from extreme) |
| STOCH_K_OVERBOUGHT / OVERSOLD | 70 / 20 | Stoch K overbought / oversold thresholds |
| FIXED_LOTS | 0.01 | Fixed lot size |
| MAX_SLIPPAGE | 30 | Max slippage |
## Data Source
- All indicators from DataFactory TA-Lib
- Dependencies: `close`, `bbi`, `stoch_5_3_3`, `bb`, `bb_mid_direction`, `pdi`, `ndi`, `atr`
## Risk Control
- Fixed 0.01 lots
- 3.0×ATR wide stop backstop (trailing stop and BB hard stop are the primary exits)
