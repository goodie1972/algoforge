---
name: timeprofit_ea
magic: 880202

type: 趋势
display_en: TimeProfit EA — H2 Trend + M5 Entry + Round Number Box
desc_en: Original TimeProfitEA port, H2 trend, 00 round-number box trading
---

- **GitHub:** [caoruihua/sanqing-ea-mt5](https://github.com/caoruihua/sanqing-ea-mt5)

## Original Source

- **GitHub:** [caoruihua/sanqing-ea-mt5](https://github.com/caoruihua/sanqing-ea-mt5)
- **Language:** MQL5 (MT5) → Python Port
- **Author:** caoruihua
- **Description:** An H2 trend + M5 entry round-number box trading strategy. Core file: TimeProfitEA.mq5. Backtest: 188 trades, Profit Factor 2.03, Win Rate 38.3%.


### BUY (Long)

### SELL (Short)




### Trend Judgment (H2)


### Round Number Box (100 Interval)


### M5 Entry Confirmation


## Entry Logic

## Exit Logic

| ① | Fixed Stop | 3.0×ATR (minimum $5) |  |
| ② | Round-Number TP | Take profit $3 before price reaches nearest round number level |  |
| ③ | Min TP Distance | Skip signal when take-profit distance < $10 |  |




## Special Rules

- Cooldown: No trading within 10 minutes after any close
- Profit close cooldown: No repeat position in same direction within 5 minutes
- Data source: All indicators from DataFactory TA-Lib