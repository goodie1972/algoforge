---
name: mfi_bb_m30_upgraded
magic: 661003
type: 反转
display_en: M30 MFI+BB Upgraded — Money Flow BB Upgraded
desc_en: M30 MFI+BB v16 upgraded with BB expand 4-set + MFI direction + time/price stop
---

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



## Entry Logic
## Exit Logic




## Data Source

- Dependencies：`close`, `mfi`, `mfi_direction`, `bb`, `bb_width`, `bb_width_direction`, `bb_width_ratio`