---
name: mfi_bb_m30_upgraded
magic: 661003
type: Reversal
display_en: M30 MFI+BB Upgraded — Money Flow Bollinger Band Upgraded
desc_en: MFI+BB v16 upgraded version with BB expand 4-set + MFI direction + time/price stop
---

**Timeframe:** M30

## Entry Logic

### Long Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| 1 | MFI < 20 | Oversold |
| 2 | close ≤ BB lower band | Price breaks below lower band |
| 3 | BB expand 4-set | Bandwidth expansion, direction, ratio, trend all set |

### Short Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| 1 | MFI > 80 | Overbought |
| 2 | close ≥ BB upper band | Price breaks above upper band |
| 3 | BB expand 4-set | Bandwidth expansion, direction, ratio, trend all set |

## Exit Logic

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| ① | Reversal condition | A signal in the opposite direction appears |
| ② | Time stop | Target not reached within timeout |
| ③ | Price stop | Adverse move exceeds limit |

## Parameter Reference

| Parameter | Value | Description |
|:------------------|:------:|:----------------------|
| Candle tolerance | 2 bars | Check whether the last 2 closes broke out of the band |
| BB width expansion threshold | ratio > 1.05 | When expanding, activate same-direction trend interception (4-set) |
| Exit MFI midline | 50 | Trend-following exit requires MFI to cross the 50 line |
| Band-cross pullback buffer | 0.01 | Trend-following exit only when price pulls back inside the band (±0.01) and MFI crosses the line |
| Midline reference | BB mid-band at entry | v16 fixed reference, avoiding premature exit caused by dynamic midline drift |
| Half-width take profit | BB width at entry ÷ 2 | Exit once price moves a half-width distance in the counter-trend direction |

## Risk Control

- No hard stop (removed since v14): relies on midline/half-width/trend-following band-cross pullback for natural exits
- Ultra-wide fallback stop to prevent blowup: BUY SL = open price ×0.50, SELL SL = open price ×1.50 (fallback only, not expected to trigger)
- Strong trend ban (4-set): BB expansion (ratio>1.05) + BB direction same as price + price on same side of midline + MFI direction aligned; when all four are met, counter-trend orders are banned to prevent catching a falling knife during trend acceleration; when signals conflict (e.g. BB rising but MFI falling), no interception, allowing entry in early reversal
- Max position: 1 order (STRATEGY_POOL config)

## Data Source

- Dependencies: `close`, `mfi`, `mfi_direction`, `bb`, `bb_width`, `bb_width_direction`, `bb_width_ratio`
