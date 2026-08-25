---
name: stoch_trend_h1_optimized
magic: 661202
type: Trend
display_en: H1 Stoch Trend — Stochastic Trend Strategy
desc_en: H1 Stoch trend-following with 3-timeframe trend confirmation + Stoch golden/death cross entries
---

## Entry Logic

### Long Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| 1 | H1 trend up | Main timeframe trend |
| 2 | H4 trend up | Higher timeframe trend confirmation |
| 3 | Stoch K > D | Golden cross |
| 4 | Stoch K < 80 | Not overbought |

### Short Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| 1 | H1 trend down | Main timeframe trend |
| 2 | H4 trend down | Higher timeframe trend confirmation |
| 3 | Stoch K < D | Death cross |
| 4 | Stoch K > 20 | Not oversold |

## Exit Logic

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| ① | Trend reversal | H1 trend direction changes |
| ② | Stoch reversal | Golden/death cross reversal |
| ③ | Time stop | Close position on timeout |

## Data Source

- Dependencies: `close`, `stoch_5_3_3`, `trend`, `ema_9`, `ema_21`
