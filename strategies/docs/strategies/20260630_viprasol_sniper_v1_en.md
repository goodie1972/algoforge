---
name: viprasol_sniper
magic: 661401

type: 其他
display_en: Viprasol Sniper — 7-Factor Consensus + Multi-Level RR Exit
desc_en: H1 7-factor scoring, multi-level RR exit (1R/2R/3R/4R/5R)
---

### BUY (Long)

### SELL (Short)




## Exit Logic

| ① | TP1 (1R) | Move stop to breakeven after trigger |  |
| ② | TP2 (2R) | Exit at 2x risk profit |  |
| ③ | TP3 (3R) | Exit at 3x risk profit |  |
| ④ | TP4 (4R) | Exit at 4x risk profit |  |
| ⑤ | TP5 (5R) | Exit at 5x risk profit |  |
| ⑥ | ATR Moving Trailing | Peak drawdown exceeds 1.0 ATR and peak profit > 0.5 ATR |  |
| ⑦ | Hard Stop | Loss exceeds 1.5 ATR |  |





## Special Rules

- Data source: All indicators from DataFactory TA-Lib