---
name: mfi_bb_m30_upgraded
magic: 661003

type: 反转
display: M30 MFI+BB Upgraded — 资金流布林带升级版
display_en: M30 MFI+BB Upgraded — Money Flow BB Upgraded
desc: MFI+BB v16 升级版，BB expand 4 件套 + MFI 方向 + 时间/价格止损
desc_en: M30 MFI+BB v16 upgraded with BB expand 4-set + MFI direction + time/price stop
---

## 入场逻辑

### 做多

### Long Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| # | 条件 | 说明 |
| 1 | MFI < 20 | Oversold |
| 2 | close ≤ BB lower band | Price breaks below lower band |
| 3 | BB expand 4-set | Bandwidth expansion, direction, ratio, trend all set |

| # | 条件 | 说明 |
|:-:|:----|:----|
| 1 | MFI < 20 | 超卖 |
| 2 | close ≤ BB 下轨 | 价格跌破下轨 |
| 3 | BB expand 4 件套 | 带宽扩张、方向、比率、趋势齐备 |

### 做空

### Short Entry

| # | Condition | Description |
|:------:|:------------------:|:----------------------:|
| # | 条件 | 说明 |
| 1 | MFI > 80 | Overbought |
| 2 | close ≥ BB upper band | Price breaks above upper band |
| 3 | BB expand 4-set | Bandwidth expansion, direction, ratio, trend all set |

| # | 条件 | 说明 |
|:-:|:----|:----|
| 1 | MFI > 80 | 超买 |
| 2 | close ≥ BB 上轨 | 价格突破上轨 |
| 3 | BB expand 4 件套 | 带宽扩张、方向、比率、趋势齐备 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 反转条件 | 相反方向信号出现 |
| ② | 时间止损 | 超时未达目标 |
| ③ | 价格止损 | 不利方向移动超限 |

## 数据源

- 依赖指标：`close`, `mfi`, `mfi_direction`, `bb`, `bb_width`, `bb_width_direction`, `bb_width_ratio`
