---
name: bakome_gold_scalper_original
magic: 880303
version: v1_original
display_en: BAKOME Gold Scalper Original
desc_en: Complete ICT strategy (FVG + OB + Liquidity Sweep + Silver Bullet)
type: Reversal
---

**Timeframe:** M5 (primary execution) + H4 (EMA200 trend bias filter)

## Original Source
| Item | Content |
| --- | --- |
| Repo | [BAKOMEPythonGoldScalper](https://github.com/BAKOME-Hub/BAKOMEPythonGoldScalper) |
| Author | Bakome Fabrice Kitoko |
| Original Language | Python (1800+ lines) |
| Ported Version | v1_original (full ICT logic ported, system interface adaptation only) |
## Strategy Logic
### Core Architecture
H4 EMA200 defines trend bias → Silver Bullet session → M5 triple ICT confirmation → ATR risk control
### Entry Conditions
**Bias Direction (H4 EMA200):**
- Price > EMA200 → Bullish bias (BUY direction)
- Price < EMA200 → Bearish bias (SELL direction)
**Triple ICT Confirmation (at least 2 must hold):**
| # | Condition | Description |
| --- | --- | --- |
| 1 | Liquidity Sweep | Price breaks recent swing high/low then reverses |
| 2 | Fair Value Gap | 3-candle gap pattern detection |
| 3 | Order Block | Reversal candle before strong breakout as support/resistance zone |
**Session Filter:**
- Silver Bullet sessions only: London 8-9, New York 15-16 (MT4 timezone UTC+3)
- London/New York sessions only, Asian session quiet
### Exit Logic
| # | Condition | Description |
| --- | --- | --- |
| ① | ATR Hard Stop | Close when loss reaches 2.0×ATR |
| ② | Breakeven | Move SL to entry price at 1.0×ATR profit |
| ③ | Trailing Stop | Activate at 1.5×ATR profit, step 0.5×ATR |
## Parameter Reference
| Parameter | Value | Description |
| --- | --- | --- |
| TIMEFRAME | M5 | Primary running timeframe (H4 EMA200 defines trend bias) |
| H4_EMA_SLOW | 200 | H4 trend bias MA |
| LIQUIDITY_LOOKBACK | 50 | Liquidity Sweep swing point lookback bars |
| FVG_LOOKBACK | 20 | FVG detection lookback bars |
| FVG_MIN_SIZE_ATR | 0.5 | Minimum FVG gap (×ATR) |
| SIGNAL_MIN_CONFIRMATIONS | 2 | Minimum LS/FVG/OB triple confirmations required |
| LONDON_KILL_ZONE | 8–9 | London Silver Bullet session (UTC+3) |
| NY_KILL_ZONE | 15–16 | New York Silver Bullet session (UTC+3) |
| ATR_SL_MULTIPLIER | 2.0 | Hard stop (×ATR) |
| ATR_TP_MULTIPLIER | 3.0 | Take profit (×ATR) |
| BE_TRIGGER_ATR | 1.0 | Breakeven trigger (×ATR) |
| TRAIL_START_ATR / TRAIL_STEP_ATR | 1.5 / 0.5 | Trailing stop activation / step (×ATR) |
| MIN_ATR_POINTS | 100.0 | Minimum ATR (points), no trading when ATR < 100×0.01=1.0 |
| MAX_SPREAD_POINTS | 50.0 | Maximum spread (points) |
| FIXED_LOTS | 0.01 | Fixed lot size |
| MAX_POSITIONS | 2 | Max concurrent positions |
| MAX_DAILY_TRADES | 10 | Max trades per day |
## Risk Control
- Stop/Take profit: hard stop 2.0×ATR, take profit 3.0×ATR (falls back to fixed percentage stop when ATR is invalid)
- Breakeven: move SL to entry price at 1.0×ATR profit; trailing stop: activates at 1.5×ATR profit, stop set 0.5×ATR from the extreme, close immediately when broken (`check_ema20_exit`)
- Low volatility filter: no trading when ATR < 1.0 (MIN_ATR_POINTS×0.01); max spread 50 points (MAX_SPREAD_POINTS)
- Position limits: fixed 0.01 lots, max 2 concurrent positions, max 10 trades per day
## Special Rules
- Max 2 concurrent positions
- Max 10 trades per day
- No trading when ATR < 1.0 (low volatility filter)
- Data source: All indicators from DataFactory TA-Lib
