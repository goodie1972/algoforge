---
name: bakome_gold_scalper_original
magic: 880303
version: v1_original
display_en: BAKOME Gold Scalper Original
desc_en: Complete ICT strategy (FVG + OB + Liquidity Sweep + Silver Bullet)
type: Reversal
---

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
## Special Rules
- Max 2 concurrent positions
- Max 10 trades per day
- No trading when ATR < 1.0 (low volatility filter)
- Data source: All indicators from DataFactory TA-Lib
