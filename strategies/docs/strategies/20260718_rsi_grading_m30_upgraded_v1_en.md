---
name: rsi_grading_m30_upgraded
magic: 660904
type: 评分
display_en: M30 RSI Grading — RSI Scoring Strategy
desc_en: M30 RSI Grading system with multi-timeframe RSI scoring
---

### Long Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| 1 | RSI14 < 30 | +2 |
| 2 | RSI5 < 25 | +1 |
| 3 | RSI10 < 28 | +1 |
| 4 | Price ≤ BB lower band | +2 |
| 5 | Total score ≥ 4 | — |



### Short Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| 1 | RSI14 > 70 | +2 |
| 2 | RSI5 > 75 | +1 |
| 3 | RSI10 > 72 | +1 |
| 4 | Price ≥ BB upper band | +2 |
| 5 | Total score ≥ 4 | — |



## Entry Logic
## Exit Logic




## Data Source

- Dependencies：`close`, `rsi`, `rsi_5`, `rsi_10`, `bb`