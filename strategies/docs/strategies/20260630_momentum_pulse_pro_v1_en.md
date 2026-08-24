---
name: momentum_pulse_pro
magic: 661301

type: 反转
display_en: Momentum Pulse PRO — 7-Dimension Momentum Score + 3-Layer TP Exit
desc_en: H1 7-dimensional multi-factor scoring system with three-tier take-profit phased exit
---

### BUY (Long)

### SELL (Short)




## Exit Logic

| ① | TP1 (1.5 ATR) | Sell 50% of position after trigger |  |
| ② | TP2 (3.0 ATR) | Sell 30% of position after trigger |  |
| ③ | TP3 (5.0 ATR) | Sell remaining 20% of position after trigger |  |
| ④ | ATR Moving Trailing | Peak drawdown exceeds 1.5 ATR |  |
| ⑤ | Hard Stop | Loss exceeds 1.5 ATR |  |




## Special Rules

- Data source: All indicators from DataFactory TA-Lib