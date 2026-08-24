---
name: bakome_trinity_ea_original
magic: 880304
version: v1_original
display_en: BAKOME Trinity EA Original
desc_en: Multi-Asset Trend Following (H1 EMA34 + H4 EMA200) Type: Trend
type: 趋势
---

|:----|:-----|


> Bakome Trinity EA - Multi-Asset Trading System supporting XAUUSD, GBPUSD, BTCUSD with Economic News Filter, No Grid/Martingale, Adaptive Risk.

### Original Repo Description

> Bakome Trinity EA - Multi-Asset Trading System supporting XAUUSD, GBPUSD, BTCUSD with Economic News Filter, No Grid/Martingale, Adaptive Risk.

## Original Source

|:----|:-----|


> Bakome Trinity EA - Multi-Asset Trading System supporting XAUUSD, GBPUSD, BTCUSD with Economic News Filter, No Grid/Martingale, Adaptive Risk.

### Original Repo Description

> Bakome Trinity EA - Multi-Asset Trading System supporting XAUUSD, GBPUSD, BTCUSD with Economic News Filter, No Grid/Martingale, Adaptive Risk.




### Core Architecture



|:-:|:----|:----:|



### Entry Conditions

**Trend Judgment (H1 + H4 Dual Timeframe):**
| # | Condition | Direction |
|:-:|:---------|:--------:|
| 1 | H1 EMA34 > H4 EMA200 | Long (BUY) |
| 2 | H1 EMA34 < H4 EMA200 | Short (SELL) |

**M5 Entry Confirmation:**
- M5 close on the trend side (0.5% tolerance allowed)
- In bullish trend, M5 should not be significantly below H1 EMA34
- In bearish trend, M5 should not be significantly above H1 EMA34

**Session Filter:**
- London (7-11, UTC+3) and New York (13-17, UTC+3) sessions
- Asian session quiet
- No trading 30/20 min before/after economic news

### Exit Logic


### Exit Logic

| # | Condition | Description |
|:-:|:---------|:------------|
| ① | ATR Hard Stop | Close at 2.0×ATR loss |
| ② | Breakeven | Move SL to entry after 1.0×ATR profit |
| ③ | Trailing Stop | Activate at 1.5×ATR profit, step 0.5×ATR |

## Strategy Logic



### Core Architecture



|:-:|:----|:----:|



### Entry Conditions

**Trend Judgment (H1 + H4 Dual Timeframe):**
| # | Condition | Direction |
|:-:|:---------|:--------:|
| 1 | H1 EMA34 > H4 EMA200 | Long (BUY) |
| 2 | H1 EMA34 < H4 EMA200 | Short (SELL) |

**M5 Entry Confirmation:**
- M5 close on the trend side (0.5% tolerance allowed)
- In bullish trend, M5 should not be significantly below H1 EMA34
- In bearish trend, M5 should not be significantly above H1 EMA34

**Session Filter:**
- London (7-11, UTC+3) and New York (13-17, UTC+3) sessions
- Asian session quiet
- No trading 30/20 min before/after economic news

### Exit Logic


### Exit Logic

| # | Condition | Description |
|:-:|:---------|:------------|
| ① | ATR Hard Stop | Close at 2.0×ATR loss |
| ② | Breakeven | Move SL to entry after 1.0×ATR profit |
| ③ | Trailing Stop | Activate at 1.5×ATR profit, step 0.5×ATR |



## Special Rules

- Data source: All indicators from DataFactory TA-Lib