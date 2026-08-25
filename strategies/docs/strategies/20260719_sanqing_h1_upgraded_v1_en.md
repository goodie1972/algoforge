---
name: sanqing_h1_upgraded
magic: 880108
type: Trend
display_en: H1 SanQing Upgraded
desc_en: EMA9/21 trend scoring + high-position interception + dynamic profit drawdown take profit
---

**Timeframe:** H1

## Scoring Factors

### BUY (Long)

| # | Factor | Score | Description |
|:------:|:------------------|:------:|:----------------------|
| 1 | Uptrend | +2 | EMA9 > EMA21 |
| 2 | EMA golden cross | +1 | EMA9 crosses above EMA21 |
| 3 | Pullback to EMA9 | +2 | low ≤ EMA9×1.002 and close > EMA9 |
| 4 | Body > 1 ATR | +1 | Body length exceeds 1×ATR |
| 5 | Volume surge | +1 | Volume > avg volume×1.3 |
| 6 | Engulfing pattern | +2 | Body median ≥1.5 and body/prev high ≥1.5 and body ≥50% of candle |

### SELL (Short)

| # | Factor | Score | Description |
|:------:|:------------------|:------:|:----------------------|
| 1 | Downtrend | +2 | EMA9 < EMA21 |
| 2 | EMA death cross | +1 | EMA9 crosses below EMA21 |
| 3 | Pullback to EMA9 | +2 | high ≥ EMA9×0.998 and close < EMA9 |
| 4 | Body > 1 ATR | +1 | Body length exceeds 1×ATR |
| 5 | Volume surge | +1 | Volume > avg volume×1.3 |
| 6 | Engulfing pattern | +2 | Body median ≥1.5 and body/prev high ≥1.5 and body ≥50% of candle |

## Athlete Ticket Check

| Direction | Condition |
|:----:|:----|
| BUY | Wait for price to pull back to ≤ EMA9×1.002 before entry |
| SELL | Wait for price to rebound to ≥ EMA9×0.998 before entry |

## Exit Logic (ADX Adaptive)

| # | Condition | Range (ADX≤25) | Medium Trend (ADX 25~35) | Strong Trend (ADX>35) |
|:-:|:----|:----:|:----:|:----:|
| ① | ADX adaptive trailing stop | 1.5 ATR drawdown | 2.5 ATR drawdown | 3.5 ATR drawdown |
| ② | ADX adaptive take profit | 2.5 ATR | 4.0 ATR | 6.0 ATR |
| ③ | Hard stop (fixed) | 1.2 ATR | 1.2 ATR | 1.2 ATR |
| ④ | Profit drawdown + DI protection | Peak drawdown 25%, skip drawdown take profit when DI aligned (trend intact) |
| ⑤ | DI reversal exit | 5 min after open: BUY pos NDI>PDI / SELL pos PDI>NDI |

## Parameter Reference

| Parameter | Value | Description |
|:------------------|:------:|:----------------------|
| Score threshold | 5 points | Reduced to 4 points when ADX > 25 (lower the bar, not ban) |
| Trailing stop | 1.5 / 2.5 / 3.5 ×ATR | Range (ADX≤25) / Medium (25~35) / Strong trend (>35) |
| Take profit | 2.5 / 4.0 / 6.0 ×ATR | Adaptive across three ADX tiers |
| Hard stop | 1.2 ×ATR | Fixed, last line of defense |
| Profit drawdown min hold | 1800 seconds (30 minutes) | Profit drawdown take profit not triggered before holding 30 minutes |
| Dynamic forced take profit | Peak≤10 drawdown 50%; peak>10 drawdown 35% | Only applies during trend protection (DI aligned and ADX>20) |
| SteepMA bonus | MA14 slope (lookback 5 bars) | Direction aligned +1 point |

## Risk Control

- Hard stop: 1.2×ATR (fixed, prevent large losses)
- Position gate: within a 60-bar window, price_position>0.82 and deviation from EMA21 >2.5×ATR blocks long; price_position<0.18 and deviation <−2.5×ATR blocks short (score zeroed)
- Profit drawdown min hold 30 minutes: gives the trend time to develop, avoiding being shaken out too early by drawdown
- Trend protection + dynamic forced take profit: when DI aligned and ADX>20, skip normal drawdown take profit to let profits run; only force take profit when drawdown exceeds the dynamic threshold (peak≤10→50%, >10→35%)
- DI flip exit: detected 5 minutes after open, requires next-bar confirmation before exiting (prevent frequent flips)
- Max position: 1 order (STRATEGY_POOL config)

## Special Rules

- Threshold: **fixed 5 points** (score 3→5, raise entry bar, reduce low-quality signals by ~60%)
- **ADX Gate**: When ADX>25, entry threshold drops from 5 to 4 (20→25, lower the bar instead of banning)
- **Position Gate**: Within a 60-bar window, price_position > 0.82 and deviation from EMA21 > 2.5×ATR blocks long; price_position < 0.18 and deviation < −2.5×ATR blocks short
- **Hard Stop**: 1.2 ATR (1.5→1.2, ~36 points per trade, prevent large losses)
- **v10_optimized (2026-08-08)**: Raised score threshold to 5, ADX threshold to 25, tightened hard stop to 1.2 ATR; fewer trades, higher signal quality
- Data source: All indicators from DataFactory TA-Lib
