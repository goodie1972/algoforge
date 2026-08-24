---
name: sanqing_h1_upgraded
magic: 880108

type: 趋势
display_en: H1 SanQing Upgraded
desc_en: EMA9/21 Trend Score + Athlete Pullback to EMA9 Entry + ADX Adaptive Exit
---

### BUY (Long)

### SELL (Short)



|:----|:----|

## Athlete Ticket Check

|:----|:----|


|:-:|:----|:----:|:----:|:----:|

## Exit Logic (ADX Adaptive)

| # | Condition | Range (ADX≤25) | Medium Trend (25~35) | Strong Trend (ADX>35) |
|:-:|:---------|:----:|:----:|:----:|
| ① | ADX adaptive trailing stop | 1.5 ATR drawdown | 2.5 ATR drawdown | 3.5 ATR drawdown |
| ② | ADX adaptive take profit | 2.5 ATR | 4.0 ATR | 6.0 ATR |
| ③ | Hard stop (fixed) | 1.5 ATR | 1.5 ATR | 1.5 ATR |
| ④ | Profit drawdown + DI protection | Peak drawdown 25%, skip if DI aligned (trend intact) |
| ⑤ | DI reversal exit | 5 min after open: BUY pos NDI>PDI / SELL pos PDI>NDI |



## Special Rules

- **Position Gate**: Price in top 10% of 60-bar range blocks long，bottom 10% blocks short
- Data source: All indicators from DataFactory TA-Lib