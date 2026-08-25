---
name: rsi_grading_m30_upgraded
magic: 660904
type: Scoring
display_en: M30 RSI Grading — RSI Scoring Grading Strategy
desc_en: M30 RSI scoring system with multi-timeframe RSI composite scoring and tiered entry
---

**Timeframe:** M30

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

## Parameter Reference

| Parameter | Value | Description |
|:------------------|:------:|:----------------------|
| Entry score threshold | Fixed 3 points | Long/short scored separately, enter at ≥3 points |
| RSI extreme oversold | < 20 | Long +2 points |
| RSI oversold | 20~35 | Long +1 point |
| RSI normal zone | 35~65 | No points |
| RSI overbought | 65~80 | Short +1 point |
| RSI extreme overbought | > 80 | Short +2 points |
| ADX trend gate | > 28 | Ban opposite-direction orders in trend direction (v6 restored) |
| ADX trend-following bonus | > 25 | MA14 trend direction +1 point (v6 new) |
| Trend-following exit | trail 2.0 / hard stop 2.0 ×ATR | EMA9>EMA21 while holding long (or vice versa for short) |
| Counter-trend exit | trail 1.0 / hard stop 1.0 ×ATR | Tightened when position direction opposes the trend |

## Risk Control

- BB expansion + MFI same-direction interception: when bb_width_ratio>1.05 and BB opening direction, price position relative to midline, and MFI direction are all aligned, the counter-trend side's score is zeroed and banned (prevent catching a falling knife during trend acceleration)
- ADX>28 trend gate: ban shorts in uptrend, ban longs in downtrend (ban counter-trend orders)
- ATR hard stop: trend-following 2.0×ATR, counter-trend 1.0×ATR (EMA9/21 trend-aware dynamic switching)
- ATR trailing stop: trend-following 2.0×ATR, counter-trend 1.0×ATR peak drawdown
- Profit drawdown take profit: take profit when peak profit drawdown exceeds limit; when ADX>25, trend-following orders relax drawdown tolerance to ≥50%, counter-trend orders tighten to ≤15%
- Break-even exit: close to lock capital when profit pulls back near cost
- Entry validation: reject order when tick price runs beyond BB band by more than 0.5% (BUY above lower band ×1.005 / SELL below upper band ×0.995 does not enter)
- Max position: 1 order (STRATEGY_POOL config)

## Data Source

- Dependencies: `close`, `rsi`, `rsi_5`, `rsi_10`, `bb`
