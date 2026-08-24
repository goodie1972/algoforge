---
name: bakome_gold_scalper_original
magic: 880303
version: v1_original
display_en: BAKOME Gold Scalper Original
desc_en: Complete ICT Strategy (FVG + OB + Liquidity Sweep + Silver Bullet) type: Reversal
type: 反转
---

|:----|:-----|


> Professional algorithmic trading system for XAUUSD (Gold) implementing ICT concepts (FVG, Order Blocks, Liquidity Sweeps, Silver Bullet) with full risk management, backtesting engine, and live trading capabilities.

### Original Repo Description

> Professional algorithmic trading system for XAUUSD (Gold) implementing ICT concepts (FVG, Order Blocks, Liquidity Sweeps, Silver Bullet) with full risk management, backtesting engine, and live trading capabilities.

## Original Source

|:----|:-----|


> Professional algorithmic trading system for XAUUSD (Gold) implementing ICT concepts (FVG, Order Blocks, Liquidity Sweeps, Silver Bullet) with full risk management, backtesting engine, and live trading capabilities.

### Original Repo Description

> Professional algorithmic trading system for XAUUSD (Gold) implementing ICT concepts (FVG, Order Blocks, Liquidity Sweeps, Silver Bullet) with full risk management, backtesting engine, and live trading capabilities.




### Core Architecture






### Entry Conditions

**Bias Direction (H4 EMA200):**
- Price > EMA200 → Bullish bias (BUY direction)
- Price < EMA200 → Bearish bias (SELL direction)

**Triple ICT Confirmation (at least 2 must hold):**
| # | Condition | Description |
|:-:|:---------|:------------|
| 1 | Liquidity Sweep | Price breaks recent swing high/low then reverses |
| 2 | Fair Value Gap | 3-candle gap pattern detection |
| 3 | Order Block | Reversal candle before strong breakout as S/R zone |

**Session Filter:**
- Silver Bullet sessions only: London 8-9, New York 15-16 (MT4 UTC+3)
- London/New York sessions only, Asian session quiet

### Exit Logic


### Exit Logic

| # | Condition | Description |
|:-:|:---------|:------------|
| ① | ATR Hard Stop | Close at 2.0×ATR loss |
| ② | Breakeven | Move SL to entry after 1.0×ATR profit |
| ③ | Trailing Stop | Activate at 1.5×ATR profit, step 0.5×ATR |

## Strategy Logic



### Core Architecture






### Entry Conditions

**Bias Direction (H4 EMA200):**
- Price > EMA200 → Bullish bias (BUY direction)
- Price < EMA200 → Bearish bias (SELL direction)

**Triple ICT Confirmation (at least 2 must hold):**
| # | Condition | Description |
|:-:|:---------|:------------|
| 1 | Liquidity Sweep | Price breaks recent swing high/low then reverses |
| 2 | Fair Value Gap | 3-candle gap pattern detection |
| 3 | Order Block | Reversal candle before strong breakout as S/R zone |

**Session Filter:**
- Silver Bullet sessions only: London 8-9, New York 15-16 (MT4 UTC+3)
- London/New York sessions only, Asian session quiet

### Exit Logic


### Exit Logic

| # | Condition | Description |
|:-:|:---------|:------------|
| ① | ATR Hard Stop | Close at 2.0×ATR loss |
| ② | Breakeven | Move SL to entry after 1.0×ATR profit |
| ③ | Trailing Stop | Activate at 1.5×ATR profit, step 0.5×ATR |



## Special Rules

- Data source: All indicators from DataFactory TA-Lib