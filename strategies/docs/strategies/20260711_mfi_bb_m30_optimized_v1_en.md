---
name: mfi_bb_m30_optimized
magic: 661002
type: Reversal
display_en: M30 MFI+BB Optimized — Money Flow Bollinger Band Optimized
desc_en: MFI+BB optimized version with MFI dual-condition gate + BB band mean reversion + 4-set risk control
---

**Timeframe:** M30

## Entry Logic

### Long Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| 1 | MFI < 20 or MFI direction up and < 50 | Dual condition gate |
| 2 | close ≤ BB lower band | Price near lower band |
| 3 | BB bandwidth expansion | Volatility expansion |

### Short Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| 1 | MFI > 80 or MFI direction down and > 50 | Dual condition gate |
| 2 | close ≥ BB upper band | Price near upper band |
| 3 | BB bandwidth expansion | Volatility expansion |

## Exit Logic

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| ① | BB mid-band reversion | Price returns to BB mid-band |
| ② | Branch reversal | A signal in the opposite direction appears |

## Parameter Reference

| Parameter | Value | Description |
|:------------------|:------:|:----------------------|
| MFI overbought threshold | 85 | MFI ≥ 85 triggers short signal (tightened from 80) |
| MFI oversold threshold | 15 | MFI ≤ 15 triggers long signal (tightened from 20) |
| BB period | 20 | Bollinger Band calculation period |
| BB standard deviation multiple | 2.0 | Bollinger Band width |
| Candle tolerance | 2 bars | Band-touch signal detection tolerance (reduced from 3 to 2 bars) |
| Entry validation price tolerance | ±1.5% | Reject order when tick price deviates from BB band by more than ±1.5% |

## Risk Control

- No ATR hard stop: exits are fully managed by BB mid-band reversion / half-width / trend-following reversal signals; no time stop
- Ultra-wide fallback stop to prevent blowup: BUY SL = open price ×0.95, SELL SL = open price ×1.05
- Entry secondary validation: reject entry when price runs beyond BB band ±1.5% or MFI crosses the opposite threshold (>85 / <15), preventing chasing
- Max position: 1 order (STRATEGY_POOL config)

## Data Source

- Dependencies: `close`, `mfi`, `mfi_direction`, `bb`, `bb_width`
