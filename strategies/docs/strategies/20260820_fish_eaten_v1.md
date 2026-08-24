---
name: fish_eaten
magic: 661301

type: 价格回归（Counter-Trend）
display: RSI-BB Trend — M30 价格回归策略
display_en: fish_eaten v2 — M30 Price Reversion Strategy
desc: 门禁+3层筛子入场，RSI/MFI双极限吃鱼出场，M30周期
desc_en: RSI-BB Trend — M30 price reversion strategy with ADX gate + 3-layer filter entry + fish exit
---

## 入场逻辑

### 门禁（前置条件）

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ADX > 20 | 存在趋势，非震荡 |
| ② | \|+DI − -DI\| > 5 | 趋势方向明确 |

### Gate (Pre-conditions)

| # | Condition | Description |
|:-:|:---------|:------------|
| ① | ADX > 20 | Trending market, not ranging |
| ② | \|+DI − -DI\| > 5 | Clear trend direction |

### 三层筛子（做多：−DI > +DI）

| 层 | 条件 | 说明 |
|:--:|:----|:----|
| 第1层 | RSI < 30 **且** MFI < 25 | 超卖确认 |
| 第2层 | close ≤ BB 下轨 + 5 | 价格在 BB 下轨附近 |
| 第3层 | BB 中轨方向向下 | 均线趋势向下，等待回归 |

### Three-Layer Filter (Long: −DI > +DI)

| Layer | Condition | Description |
|:----:|:---------|:------------|
| 1 | RSI < 30 **and** MFI < 25 | Oversold confirmation |
| 2 | close ≤ BB lower band + 5 | Price near BB lower band |
| 3 | BB mid-band direction down | MA trend down, waiting for reversion |

### 三层筛子（做空：+DI > −DI）

| 层 | 条件 | 说明 |
|:--:|:----|:----|
| 第1层 | RSI > 70 **且** MFI > 75 | 超买确认 |
| 第2层 | close ≥ BB 上轨 − 5 | 价格在 BB 上轨附近 |
| 第3层 | BB 中轨方向向上 | 均线趋势向上，等待回归 |

### Three-Layer Filter (Short: +DI > −DI)

| Layer | Condition | Description |
|:----:|:---------|:------------|
| 1 | RSI > 70 **and** MFI > 75 | Overbought confirmation |
| 2 | close ≥ BB upper band − 5 | Price near BB upper band |
| 3 | BB mid-band direction up | MA trend up, waiting for reversion |


## Entry Logic
## 出场逻辑

## Exit Logic

### 吃鱼出场（主出场）

| 方向 | 触发条件 | 说明 |
|:---:|:---------|:----|
| **做多** | RSI≥70 **且** MFI≥75 **都到过** → 任一离开(RSI<70 或 MFI<75) → 且 close < BB上轨−offset | 完整吃完一波上涨 |
| **做空** | RSI≤30 **且** MFI≤25 **都到过** → 任一离开(RSI>30 或 MFI>25) → 且 close > BB下轨+offset | 完整吃完一波下跌 |

### Fish Exit (Primary)

| Direction | Trigger | Description |
|:--------:|:--------|:------------|
| **Long** | RSI≥70 **and** MFI≥75 **both reached** → either leaves (RSI<70 or MFI<75) → and close < BB upper band − offset | Capture the full upside move |
| **Short** | RSI≤30 **and** MFI≤25 **both reached** → either leaves (RSI>30 or MFI>25) → and close > BB lower band + offset | Capture the full downside move |

### 时间止损（兜底）

- 一个指标到达极限后，另一个在 **48 根 K 线（M30 = 24 小时）** 内未到达 → 强制平仓
- 防止部分交易永远等不到两个指标同时到极限

### Time Stop (Backstop)

- One indicator reaches extreme, the other does not within **48 bars (M30 = 24 hours)** → force close
- Prevents trades from waiting indefinitely for both indicators to reach extremes

## 回测结果

### Best Parameters (M30, 2024-01 ~ 2026-08, 4889 bars)

| 参数 | 值 | 说明 |
|:----|:---|:----|
| ADX_GATE | 20 | 门禁阈值 |
| DI_DIFF_GATE | 5 | DI 差值门禁 |
| BB_EXIT_OFFSET | 8 | 吃鱼出场偏移 |
| TIME_STOP_BARS | 48 | 时间止损 K 线数 |

### 性能

| 指标 | 值 |
|:----|:---|
| 净 PnL | +$346 (+3.46%) |
| 交易笔数 | 26 |
| 胜率 | 62% |
| 最大持仓 | 48 K 线（24 小时） |

### 参数敏感性

- **ADX**: 20/22 效果接近，25 略差
- **DI**: 5 和 10 无差异
- **BB**: 8/10 优于 5
- **TS**: 48 为最佳平衡点（TS=12 全部被砍，无 TS 有死单）

### Performance

| Metric | Value |
|:----|:---|
| Net PnL | +$346 (+3.46%) |
| Trades | 26 |
| Win Rate | 62% |
| Max Hold | 48 bars（24 hours） |

### 参数敏感性

- **ADX**: 20/22 效果接近，25 略差
- **DI**: 5 和 10 无差异
- **BB**: 8/10 优于 5
- **TS**: 48 为最佳平衡点（TS=12 全部被砍，无 TS 有死单）

### Parameter Sensitivity

- **ADX**: 20/22 similar performance，25 slightly worse
- **DI**: 5 和 10 无差异
- **BB**: 8/10 better than 5
- **TS**: 48 为optimal balance（TS=12 all cut off，无 TS have dead trades）

### Performance

| Metric | Value |
|:----|:---|
| Net PnL | +$346 (+3.46%) |
| Trades | 26 |
| Win Rate | 62% |
| Max Hold | 48 bars（24 hours） |

### 参数敏感性

- **ADX**: 20/22 similar performance，25 slightly worse
- **DI**: 5 和 10 无差异
- **BB**: 8/10 better than 5
- **TS**: 48 为optimal balance（TS=12 all cut off，无 TS have dead trades）

## Backtest Results

### Best Parameters（M30, 2024-01 ~ 2026-08, 4889 根 bars）

| 参数 | 值 | 说明 |
|:----|:---|:----|
| ADX_GATE | 20 | 门禁阈值 |
| DI_DIFF_GATE | 5 | DI 差值门禁 |
| BB_EXIT_OFFSET | 8 | 吃鱼出场偏移 |
| TIME_STOP_BARS | 48 | 时间止损 bars数 |

### 性能

| Metric | Value |
|:----|:---|
| Net PnL | +$346 (+3.46%) |
| Trades | 26 |
| Win Rate | 62% |
| Max Hold | 48 bars（24 hours） |

### 参数敏感性

- **ADX**: 20/22 效果接近，25 略差
- **DI**: 5 和 10 无差异
- **BB**: 8/10 优于 5
- **TS**: 48 为最佳平衡点（TS=12 全部被砍，无 TS 有死单）

## 数据源

- 全部指标从 DataFactory TA-Lib 读取
- 依赖指标：`close`, `rsi`, `mfi`, `adx`, `pdi`, `ndi`, `bb`, `bb_mid_direction`

## Data Source

- All indicators from DataFactory TA-Lib
- Dependencies：`close`, `rsi`, `mfi`, `adx`, `pdi`, `ndi`, `bb`, `bb_mid_direction`

## 风控

- 固定 0.01 手
- 1.5×ATR 宽止损兜底（正常情况不会触发）
- 吃鱼出场管理利润，无止盈锁

## Risk Control

- Fixed 0.01 lots
- 1.5×ATR wide stop-loss backstop（正常情况不会触发）
- Fish exit manages profit，no take profit锁