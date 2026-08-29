---
name: m15_followave
magic: 661401
type: 趋势跟踪
display: M15 FollowAve — Stoch+BBI+BB 趋势跟踪
desc: M15 趋势跟踪，±DI 门禁 + Stoch 金叉/死叉 + BBI 方向 + BB 中轨确认 + 超买死叉止盈 + 2.0×ATR trailing stop
---

**适用周期：** M15

## 入场逻辑
### 门禁（前置条件）
| # | 条件 | 说明 |
| --- | --- | --- |
| ① | \|+DI − -DI\| > 5 | 趋势方向明确 |
| ② | +DI > −DI = 多头，−DI > +DI = 空头 | 趋势方向 |
### 三层筛子（做多：+DI > −DI）
| 层 | 条件 | 说明 |
| --- | --- | --- |
| 第1层 | close > BBI | 价格在均线簇上方 |
| 第2层 | Stoch K > D（金叉）且 K < 70 | 动量向上，但未超买 |
| 第3层 | close ≥ BB 中轨 | 价格在布林带中轨之上 |
### 三层筛子（做空：−DI > +DI）
| 层 | 条件 | 说明 |
| --- | --- | --- |
| 第1层 | close < BBI | 价格在均线簇下方 |
| 第2层 | Stoch K < D（死叉）且 K > 20 | 动量向下，但未超卖 |
| 第3层 | close ≤ BB 中轨 | 价格在布林带中轨之下 |
## 出场逻辑
出场按优先级从高到低检查，任一触发即平仓：
### ① 超买死叉止盈（主动止盈，最高优先级）
| 方向 | 条件 | 说明 |
| --- | --- | --- |
| 做多 | 曾触 BB 上轨（high≥bb_top−3）+ Stoch K>80 死叉 | 超买后动量衰退即止盈 |
| 做空 | 曾触 BB 下轨（low≤bb_bot+3）+ Stoch K<20 金叉 | 超卖后动量回升即止盈 |
### ② 趋势反转止盈
| 方向 | 条件 | 说明 |
| --- | --- | --- |
| 做多 | close < BBI + bbi_dir=down，连续 3 根 | 趋势已反转 |
| 做空 | close > BBI + bbi_dir=up，连续 3 根 | 趋势已反转 |
### ③ BB 硬止损
| 方向 | 条件 | 说明 |
| --- | --- | --- |
| 做多 | close < BB 下轨 | 止损兜底 |
| 做空 | close > BB 上轨 | 止损兜底 |
### ④ Trailing Stop
| 方向 | 条件 | 说明 |
| --- | --- | --- |
| 做多 | close < peak − 2.0×ATR | 从最高点回撤锁利 |
| 做空 | close > peak + 2.0×ATR | 从最低点反弹锁利 |
## 回测结果
**最佳参数：M15 + Stoch5 + 确认3根 + DI门禁=5 + Trail=2.0×ATR**
| 指标 | 值 |
| --- | --- |
| 净 PnL | +$403 (+4.03%) |
| 交易笔数 | 312 |
| 胜率 | 36% |
| 盈亏比 | 2.09 |
| 最大赢利 | +$154 |
| 最大亏损 | -$74 |
## 参数说明
| 参数 | 取值 | 说明 |
| --- | --- | --- |
| TIMEFRAME | M15 | 主运行周期 |
| DI_GATE | 5 | ±DI 差值门禁 |
| EXIT_CONFIRM_BARS | 3 | 趋势反转出场确认 K 线数 |
| TRAIL_ATR | 2.0 | 2.0×ATR trailing stop（从极值点回撤锁利） |
| STOCH_K_OVERBOUGHT / OVERSOLD | 70 / 30 | Stoch K 入场超买 / 超卖阈值 |
| STOCH_EXIT_OVERBOUGHT / OVERSOLD | 80 / 20 | Stoch K 止盈超买 / 超卖阈值 |
| BB_EXTREME_TOLERANCE | 3 | 接近 BB 上/下轨多少点算"触碰过" |
| FIXED_LOTS | 0.01 | 固定手数 |
| MAX_SLIPPAGE | 30 | 最大滑点 |
## 数据源
- 全部指标从 DataFactory TA-Lib 读取
- 依赖指标：`close`, `bbi`, `stoch_5_3_3`, `bb`, `bb_mid_direction`, `pdi`, `ndi`, `atr`
## 风控
- 固定 0.01 手
- 3.0×ATR 宽止损兜底（超买死叉止盈 + BB 硬止损 + Trailing stop 是主要出场）
