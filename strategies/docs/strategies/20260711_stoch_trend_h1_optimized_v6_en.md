---
name: stoch_trend_h1_optimized
magic: 661202
type: 趋势
display_en: H1 Stoch Trend — Stochastic Trend Strategy
desc_en: H1 Stoch trend-following with 3-TF trend confirmation + Stoch cross
---

### Long Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| 1 | H1 trend up | Main timeframe trend |
| 2 | H4 trend up | Higher timeframe confirmation |
| 3 | Stoch K > D (golden cross) | Golden cross |
| 4 | Stoch K < 80 | Not overbought |



### Short Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| 1 | H1 trend down | Main timeframe trend |
| 2 | H4 trend down | Higher timeframe confirmation |
| 3 | Stoch K < D (death cross) | Death cross |
| 4 | Stoch K > 20 | Not oversold |



## Entry Logic
## Exit Logic




## Data Source

- Dependencies：`close`, `stoch_5_3_3`, `trend`, `ema_9`, `ema_21`