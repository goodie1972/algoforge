---
name: gold_auto_research
magic: 880306

type: ML
display_en: Gold-AutoResearch — H1 Live Trading Strategy
desc_en: H1 Four-Factor Consensus Voting Strategy: Signals are triggered only when all conditions are consistent.
---

### BUY (Long)

### SELL (Short)





## Exit Logic

| ① | Breakeven Exit | After reaching ≥0.3ATR profit, returns near breakeven |  |
| ② | Profit Pullback TP | Peak profit retraces 25% (relaxed to 50% when ADX>25) |  |
| ③ | ATR Moving TP | Retraces more than trail_mult × ATR from peak |  |
| ④ | Hard Stop | Loss exceeds hard_mult × ATR (with-trend 3.0×ATR, against-trend 2.0×ATR) |  |




## Special Rules

- Data source: All indicators from DataFactory TA-Lib