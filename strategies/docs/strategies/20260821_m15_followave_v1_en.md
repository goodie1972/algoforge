---
name: m15_followave
magic: 661401
type: Trend-Following
display_en: M15 FollowAve — Stoch+BBI+BB Trend Following
desc_en: M15 trend following, ±DI gate + Stoch golden/death cross + BBI direction + BB mid-band confirmation + overbought death-cross profit-taking + 2.0×ATR trailing stop
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
Exits are checked in priority order (highest first); the first match triggers exit:
### ① Overbought Death-Cross Profit-Taking (Active TP, Top Priority)
| Direction | Condition | Description |
| --- | --- | --- |
| Long | Touched BB upper (high≥bb_top−3) + Stoch K>80 death cross | Take profit when momentum fades after overbought |
| Short | Touched BB lower (low≤bb_bot+3) + Stoch K<20 golden cross | Take profit when momentum recovers after oversold |
### ② Trend Reversal Profit-Taking
| Direction | Condition | Description |
| --- | --- | --- |
| Long | close < BBI + bbi_dir=down, 3 consecutive candles | Trend has reversed |
| Short | close > BBI + bbi_dir=up, 3 consecutive candles | Trend has reversed |
### ③ BB Hard Stop
| Direction | Condition | Description |
| --- | --- | --- |
| Long | close < BB lower band | Stop-loss backstop |
| Short | close > BB upper band | Stop-loss backstop |
### ④ Trailing Stop
| Direction | Condition | Description |
| --- | --- | --- |
| Long | close < peak − 2.0×ATR | Lock profit on drawdown from peak |
| Short | close > trough + 2.0×ATR | Lock profit on rebound from trough |
## Backtest Results
**Best Parameters: M15 + Stoch5 + 3 confirmation bars + DI gate=5 + Trail=2.0×ATR**
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
| TRAIL_ATR | 2.0 | 2.0×ATR trailing stop (lock profit on drawdown from extreme) |
| STOCH_K_OVERBOUGHT / OVERSOLD | 70 / 30 | Stoch K entry overbought / oversold thresholds |
| STOCH_EXIT_OVERBOUGHT / OVERSOLD | 80 / 20 | Stoch K exit overbought / oversold thresholds |
| BB_EXTREME_TOLERANCE | 3 | Points within BB upper/lower band to count as "touched" |
| FIXED_LOTS | 0.01 | Fixed lot size |
| MAX_SLIPPAGE | 30 | Max slippage |
## Data Source
- All indicators from DataFactory TA-Lib
- Dependencies: `close`, `bbi`, `stoch_5_3_3`, `bb`, `bb_mid_direction`, `pdi`, `ndi`, `atr`
## Risk Control
- Fixed 0.01 lots
- 3.0×ATR wide stop backstop (overbought death-cross TP + BB hard stop + trailing stop are the primary exits)
