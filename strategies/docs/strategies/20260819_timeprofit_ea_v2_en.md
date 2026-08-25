---
name: timeprofit_ea
magic: 880202
type: Trend
display_en: TimeProfit EA — H2 Trend + M5 Entry + Round Number Box
desc_en: Original TimeProfitEA port, H2 trend judgment, box trading at $100 round-number levels, ATR risk control
---

**Timeframe:** M5 (primary execution) + H2 (EMA10/EMA30 trend filter)

## Original Source
- **Language:** MQL5 (MT5) → Python port
- **Author:** caoruihua
- **Description:** A round-number box trading strategy with H2 trend + M5 entry. Core file: `TimeProfitEA.mq5`. Backtest: 188 trades, Profit Factor 2.03, win rate 38.3%.
## Scoring Factors
### BUY (Long)
| # | Factor | Score | Description |
| --- | --- | --- | --- |
| 1 | H2 trend up | +1 | EMA10 > EMA30 and spacing ≥ $1.0 |
| 2 | Rebound entry | +1 | Price rebounds from upper level down to near a lower level |
| 3 | Breakout entry | +1 | Price breaks strongly above the upper level |
### SELL (Short)
| # | Factor | Score | Description |
| --- | --- | --- | --- |
| 1 | H2 trend down | +1 | EMA10 < EMA30 and spacing ≥ $1.0 |
| 2 | Rebound entry | +1 | Price rebounds from lower level up to near an upper level |
| 3 | Breakout entry | +1 | Price breaks down below the lower level |
## Entry Logic
### Trend Judgment (H2)
- Fast EMA: 10 (H2) / M5 substitute: 120
- Slow EMA: 30 (H2) / M5 substitute: 300
- Minimum trend spacing: $1.0 (avoid ranging periods)
- No trading when trend is neutral
### Round Number Box (**$100** Interval)
- XAUUSD shows clear support/resistance at $100 round-number levels (e.g. 2300, 2400, 2500...)
- ±$4 around a level is a no-entry zone (avoid false breakouts)
- Rebound zone: within $70 of a level (pullback within a trend)
- Breakout entry: price breaks a level by more than $4
- Candle direction must agree with the trend (configurable via `REQUIRE_CANDLE_DIRECTION`)
- Both rebound and breakout directions must agree with the H2 trend
## Exit Logic
| # | Condition | Description |
| --- | --- | --- |
| ① | Fixed Stop | 3.0×ATR (minimum $5) |
| ② | Round-Number TP | Take profit $3 before the nearest round-number level |
| ③ | Min TP Distance | Skip the signal when TP distance < $10 |
## Parameter Reference
| Parameter | Value | Description |
| --- | --- | --- |
| TIMEFRAME | M5 | Primary running timeframe (H2 defines trend, M5 EMA120/300 fallback approximation) |
| TREND_FAST_EMA / TREND_SLOW_EMA | 10 / 30 | H2 trend EMAs |
| MIN_TREND_GAP_DOLLARS | 1.0 | Minimum trend EMA gap (dollars) |
| M5_ENTRY_EMA | 10 | Rebound entry touch confirmation MA (v2) |
| M5_ENTRY_EMA_CONFIRM | True | v2: rebound entry requires price to touch M5 EMA10 |
| REQUIRE_CANDLE_DIRECTION | True | M5 candle direction must agree with trend |
| USE_PULLBACK_ENTRY / USE_BREAKOUT_ENTRY | True / True | Rebound entry / breakout entry switches |
| PULLBACK_DISTANCE | 70.0 | Rebound zone distance to level edge (dollars) |
| LEVEL_STEP | 100.0 | Round-number level interval (dollars) |
| NO_TRADE_DISTANCE | 4.0 | No-entry distance near levels (dollars) |
| TP_BUFFER | 3.0 | Take-profit buffer before level (dollars) |
| MIN_TP_DISTANCE | 10.0 | Minimum take-profit distance (dollars) |
| ATR_PERIOD | 14 | ATR period |
| ATR_STOP_MULT | 3.0 | Stop loss = ATR × 3.0 |
| MIN_STOP_DISTANCE | 5.0 | Minimum stop distance (dollars) |
| FIXED_LOTS | 0.01 | Fixed lot size |
| COOLDOWN_MINUTES | 10 | Cooldown minutes after any close |
| _exit_cooldown_seconds | 300 | Same-direction cooldown after profit close (seconds) |
## Risk Control
- Stop loss: 3.0×ATR, minimum $5 (MIN_STOP_DISTANCE); no TP multiplier, take profit $3 before round-number level (TP_BUFFER); when TP distance < $10 (MIN_TP_DISTANCE), use the next level instead
- Cooldown: no new positions for 10 minutes after any close (COOLDOWN_MINUTES); no repeat position in the same direction for 5 minutes (300 seconds) after a profit close
- Level no-entry zone: no trading when price is < $4 (NO_TRADE_DISTANCE) from any round-number level, to avoid false breakouts
- Fixed 0.01 lots, max slippage 30
## Special Rules
- Cooldown: no trading within 10 minutes after any close
- Profit close cooldown: no repeat position in the same direction within 5 minutes
- Data source: All indicators from DataFactory TA-Lib
