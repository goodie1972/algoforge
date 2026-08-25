---
name: mfi_bb_m30_upgraded
magic: 661003
type: Reversal
display_en: M30 MFI+BB Upgraded — Money Flow Bollinger Band Upgraded
desc_en: MFI+BB v16 upgraded version with BB expand 4-set + MFI direction + time/price stop
---

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

## Data Source

- Dependencies: `close`, `mfi`, `mfi_direction`, `bb`, `bb_width`, `bb_width_direction`, `bb_width_ratio`
