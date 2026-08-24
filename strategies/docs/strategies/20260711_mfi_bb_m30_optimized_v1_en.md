---
name: mfi_bb_m30_optimized
magic: 661002
type: 反转
display_en: M30 MFI+BB Optimized — Money Flow BB Optimized
desc_en: M30 MFI+BB optimized with MFI dual gate + BB band return + 4-set risk control
---

### Long Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| 1 | MFI < 20 or MFI up and < 50 | Dual condition gate |
| 2 | close ≤ BB lower band | Price near lower band |
| 3 | BB Bandwidth Expansion | Volatility expansion |



### Short Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| 1 | MFI > 80 or MFI down and > 50 | Dual condition gate |
| 2 | close ≥ BB upper band | Price near upper band |
| 3 | BB Bandwidth Expansion | Volatility expansion |



## Entry Logic
## Exit Logic




## Data Source

- Dependencies：`close`, `mfi`, `mfi_direction`, `bb`, `bb_width`