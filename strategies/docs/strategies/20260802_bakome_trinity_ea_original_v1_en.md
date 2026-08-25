---
name: bakome_trinity_ea_original
magic: 880304
version: v1_original
display_en: BAKOME Trinity EA Original
desc_en: Multi-asset trend following (H1 EMA34 + H4 EMA200)
type: Trend
---

**Timeframe:** M5 (primary execution) + H1/H4 (EMA34/EMA200 dual-timeframe trend filter)

## Original Source
| Item | Content |
| --- | --- |
| Repo | [BakomeTrinityEA](https://github.com/BAKOME-Hub/BakomeTrinityEA) |
| Author | Bakome Fabrice Kitoko |
| Original Language | MQL5 |
| Ported Version | v1_original (fully ported to the Python system) |
## Strategy Logic
### Core Architecture
H1 EMA34 + H4 EMA200 dual-timeframe trend → M5 entry confirmation → ATR risk control
### Entry Conditions
**Trend Judgment (H1 + H4 Dual Timeframe):**
| # | Condition | Direction |
| --- | --- | --- |
| 1 | H1 EMA34 > H4 EMA200 | Long (BUY) |
| 2 | H1 EMA34 < H4 EMA200 | Short (SELL) |
**M5 Entry Confirmation:**
- M5 close on the trend side (0.5% tolerance allowed)
- In bullish trend, M5 should not be significantly below H1 EMA34
- In bearish trend, M5 should not be significantly above H1 EMA34
**Session Filter:**
- Trade during London (7-11, UTC+3) and New York (13-17, UTC+3) sessions
- Asian session quiet
- No trading 30/20 min before/after economic news
### Exit Logic
| # | Condition | Description |
| --- | --- | --- |
| ① | ATR Hard Stop | Close when loss reaches 2.0×ATR |
| ② | Breakeven | Move SL to entry price at 1.0×ATR profit |
| ③ | Trailing Stop | Activate at 1.5×ATR profit, step 0.5×ATR |
## Parameter Reference
| Parameter | Value | Description |
| --- | --- | --- |
| TIMEFRAME | M5 | Primary running timeframe (H1+H4 dual timeframes define trend) |
| H1_EMA_FAST / H4_EMA_SLOW | 34 / 200 | H1 fast / H4 slow trend MA |
| LONDON_START_HOUR | 7 | London session start hour (+4h, UTC+3) |
| NEW_YORK_START_HOUR | 13 | New York session start hour (+4h, UTC+3) |
| USE_NEWS_FILTER | True | Economic news filter switch |
| NEWS_BLOCK_MINUTES_BEFORE / AFTER | 30 / 20 | No-entry minutes before / after news |
| ATR_SL_MULTIPLIER | 2.0 | Hard stop (×ATR) |
| ATR_TP_MULTIPLIER | 3.0 | Take profit (×ATR) |
| BE_TRIGGER_ATR | 1.0 | Breakeven trigger (×ATR) |
| TRAIL_START_ATR / TRAIL_STEP_ATR | 1.5 / 0.5 | Trailing stop activation / step (×ATR) |
| MIN_ATR_POINTS | 100.0 | Minimum ATR (points), no trading when ATR < 100×0.01=1.0 |
| MAX_SPREAD_POINTS | 50.0 | Maximum spread (points) |
| FIXED_LOTS | 0.01 | Fixed lot size |
| MAX_POSITIONS | 1 | Max concurrent positions |
| MAX_DAILY_TRADES | 10 | Max trades per day |
## Risk Control
- Stop/Take profit: hard stop 2.0×ATR, take profit 3.0×ATR (falls back to fixed percentage stop when ATR is invalid)
- Breakeven: move SL to entry price at 1.0×ATR profit; trailing stop: activates at 1.5×ATR profit, stop set 0.5×ATR from the extreme, close immediately when broken (`check_ema20_exit`)
- Low volatility filter: no trading when ATR < 1.0 (MIN_ATR_POINTS×0.01); max spread 50 points (MAX_SPREAD_POINTS)
- News filter: no trading 30 min before / 20 min after NFP 8:30 / FOMC 14:00 / CPI 13:30 (`_is_news_block`)
- Position limits: fixed 0.01 lots, max 1 concurrent position, max 10 trades per day
## Special Rules
- Max 1 concurrent position
- Max 10 trades per day
- Economic news filter (no entry before/after NFP/FOMC/CPI)
- Data source: All indicators from DataFactory TA-Lib
