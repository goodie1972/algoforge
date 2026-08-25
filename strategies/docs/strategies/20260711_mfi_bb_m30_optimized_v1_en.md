---
name: mfi_bb_m30_optimized
magic: 661002
type: Reversal
display_en: M30 MFI+BB Optimized — Money Flow Bollinger Band Optimized
desc_en: MFI+BB optimized version with MFI dual-condition gate + BB band mean reversion + 4-set risk control
---

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

## Data Source

- Dependencies: `close`, `mfi`, `mfi_direction`, `bb`, `bb_width`
