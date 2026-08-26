---
name: m15_followave
magic: 661401
type: 趋势跟踪
display: M15 FollowAve — Stoch+BBI+BB 趋势跟踪
desc: M15 趋势跟踪，±DI 门禁 + Stoch 金叉/死叉 + BBI 方向 + BB 中轨确认，无 trailing stop
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
### 趋势反转出场（主出场）
| 方向 | 条件 | 说明 |
| --- | --- | --- |
| **做多** | close < BBI 连续 **3 根** K 线 | 趋势确认反转 |
| **做空** | close > BBI 连续 **3 根** K 线 | 趋势确认反转 |
| 做多 | close < BB 下轨 | 价格跌破下轨，趋势完全逆转 |
| 做空 | close > BB 上轨 | 价格突破上轨，趋势完全逆转 |
## 回测结果
**最佳参数：M15 + Stoch5 + 确认3根 + DI门禁=5 + 无 Trail**
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
| TRAIL_ATR | 0 | 不使用 trailing stop |
| STOCH_K_OVERBOUGHT / OVERSOLD | 70 / 20 | Stoch K 超买 / 超卖阈值 |
| FIXED_LOTS | 0.01 | 固定手数 |
| MAX_SLIPPAGE | 30 | 最大滑点 |
## 数据源
- 全部指标从 DataFactory TA-Lib 读取
- 依赖指标：`close`, `bbi`, `stoch_5_3_3`, `bb`, `bb_mid_direction`, `pdi`, `ndi`, `atr`
## 风控
- 固定 0.01 手
- 3.0×ATR 宽止损兜底（BB 硬止损是主要出场）
