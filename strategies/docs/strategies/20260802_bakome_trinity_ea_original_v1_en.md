---
name: bakome_trinity_ea_original
magic: 880304
version: v1_original
display_en: BAKOME Trinity EA Original
desc_en: Multi-asset trend following (H1 EMA34 + H4 EMA200)
type: Trend
---

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
## Special Rules
- Max 1 concurrent position
- Max 10 trades per day
- Economic news filter (no entry before/after NFP/FOMC/CPI)
- Data source: All indicators from DataFactory TA-Lib
