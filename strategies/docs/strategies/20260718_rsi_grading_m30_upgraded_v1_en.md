---
name: rsi_grading_m30_upgraded
magic: 660904
type: Scoring
display_en: M30 RSI Grading — RSI Scoring Grading Strategy
desc_en: M30 RSI scoring system with multi-timeframe RSI composite scoring and tiered entry
---

## Entry Logic

### Long Entry

| # | Factor | Score | Description |
|:------:|:------------------|:------:|:----------------------|
| 1 | RSI14 < 30 | +2 | Oversold |
| 2 | RSI5 < 25 | +1 | Fast RSI confirmation |
| 3 | RSI10 < 28 | +1 | Medium RSI confirmation |
| 4 | Price ≤ BB lower band | +2 | Bollinger band confirmation |
| 5 | Total score ≥ 4 | — | Long entry |

### Short Entry

| # | Factor | Score | Description |
|:------:|:------------------|:------:|:----------------------|
| 1 | RSI14 > 70 | +2 | Overbought |
| 2 | RSI5 > 75 | +1 | Fast RSI confirmation |
| 3 | RSI10 > 72 | +1 | Medium RSI confirmation |
| 4 | Price ≥ BB upper band | +2 | Bollinger band confirmation |
| 5 | Total score ≥ 4 | — | Short entry |

## Exit Logic

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| ① | Score reversal | Long/short score reversal |
| ② | Break-even exit | Pullback to cost after profit |

## Data Source

- Dependencies: `close`, `rsi`, `rsi_5`, `rsi_10`, `bb`
