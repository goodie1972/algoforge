---
name: timeprofit_ea
magic: 880202
type: Trend
display_en: TimeProfit EA — H2 Trend + M5 Entry + Round Number Box
desc_en: Original TimeProfitEA port, H2 trend judgment, box trading at $100 round-number levels, ATR risk control
---

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
## Special Rules
- Cooldown: no trading within 10 minutes after any close
- Profit close cooldown: no repeat position in the same direction within 5 minutes
- Data source: All indicators from DataFactory TA-Lib
