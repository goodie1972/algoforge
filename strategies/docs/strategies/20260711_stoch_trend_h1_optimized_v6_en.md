---
name: stoch_trend_h1_optimized
magic: 661202
type: Trend
display_en: H1 Stoch Trend — Stochastic Trend Strategy
desc_en: H1 Stoch trend-following with 3-timeframe trend confirmation + Stoch golden/death cross entries
---

**Timeframe:** H1 (with H4 trend filter and M15 precise entry)

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

## Parameter Reference

| Parameter | Value | Description |
|:------------------|:------:|:----------------------|
| ADX trend gate | 25 | ADX ≤ 25 ranges do not enter (v8 raised from 20 to 25) |
| Hard stop | 1.2×ATR | Exit immediately when adverse move after entry exceeds 1.2×ATR |
| Trailing take profit | 1.5×ATR | Exit when peak drawdown exceeds 1.5×ATR |
| Score threshold | 5 / max 8 | Multi-timeframe weighted score ≥5 to enter (v8 raised from 4 to 5) |
| Stoch extreme zone | K<20 / K>80 | +1 point (v8 weight reduced from +2 to +1) |
| Stoch golden/death cross | — | +2 points |
| EMA21 / DI direction alignment | — | +1 point each |
| H4 trend alignment | — | +1 point (H4 EMA21 direction) |
| M15 Stoch alignment | K<30 / K>70 | +1 point (precise entry timing) |
| Entry validation gate | ADX≥25 and DI same direction | BUY requires K≤40, SELL requires K≥60 |

## Risk Control

- Hard stop: 1.2×ATR (v8 tightened from 2.0 to 1.2)
- Break-even exit: after reaching ≥0.3×ATR profit, close to lock capital when it falls back to the cost zone (0~0.05×ATR)
- Profit drawdown take profit: once peak profit > minimum peak threshold, take profit when drawdown exceeds the drawdown ratio; in strong trends with ADX>25, drawdown tolerance is relaxed to ≥50%
- Trend exhaustion exit: exit immediately when ADX drops below 20 while holding
- DI reversal exit: exit when the position direction opposes the dominant ±DI direction (trend may reverse)
- Weak trend ban: ADX ≤ 25 produces no signals; entry validation requires DI direction alignment and Stoch K within the entry zone (BUY K≤40 / SELL K≥60)
- Max position: 1 order (STRATEGY_POOL config)

## Data Source

- Dependencies: `close`, `stoch_5_3_3`, `trend`, `ema_9`, `ema_21`
