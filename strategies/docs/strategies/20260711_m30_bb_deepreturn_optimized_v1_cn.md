---
name: m30_bb_deepreturn_optimized
magic: 661102
type: 反转
display: M30 BB Deep Return — 布林带深回归
desc: M30 布林带深度回归，RSI+MFI 超卖超买入场，三重分支出场
---

**适用周期：** M30

## 入场逻辑
### 做多（超卖）
| # | 条件 | 说明 |
|---|---|---|
| 1 | RSI < 30 | 超卖 |
| 2 | MFI < 20 | 资金流极弱 |
| 3 | close ≤ BB 下轨 | 价格跌破下轨 |
### 做空（超买）
| # | 条件 | 说明 |
|---|---|---|
| 1 | RSI > 70 | 超买 |
| 2 | MFI > 80 | 资金流极强 |
| 3 | close ≥ BB 上轨 | 价格突破上轨 |
## 出场逻辑
| # | 条件 | 说明 |
|---|---|---|
| ① | 保本出场 | 走过 ≥0.3×ATR 盈利后回到成本附近 |
| ② | 趋势反转 | 多空方向改变 |
| ③ | 分支争议 | 多空条件同时出现 |
## 风控
- 动态阈值拦截：ADX>25 趋势市顺势 2 分、逆势 4 分；ADX≤25 震荡市多空均 3 分
- BB 扩张顺势拦截：带宽比率 >1.05 且开口向上、价格在中轨上方且 MFI 非下行时禁空（镜像禁多）
- 盈利平仓冷却：盈利出场后同方向 900s 内不再开仓，冷却期内达标信号清零
- 保本延迟：入场后 3600s 内不激活保本出场，由硬止损兜底
- 硬止损：亏损超过 2.0×ATR(20) 出场，对所有持仓兜底
- 最大持仓：5 单（STRATEGY_POOL 配置）
## 参数说明
| 参数 | 取值 | 说明 |
|---|---|---|
| mfi_oversold / mfi_overbought | 30 / 70 | MFI 超卖/超买阈值 |
| bb_period / bb_std | 20 / 2.0 | 布林带周期与标准差倍数 |
| score_threshold / score_threshold_trending | 3 / 2 | 震荡市阈值 / 趋势市顺势阈值 |
| adx_trend_threshold | 25 | ADX 趋势/震荡分界 |
| atr_volatility_threshold | 0.0025 | ATR 波动率加分阈值（ATR/close > 0.25%） |
| p_trailing_atr_bull / p_trailing_atr_bear | 1.5 / 1.0 | BB 顺势 / 逆势分支的 ATR 移动止盈倍数 |
| p_hard_atr | 2.0 | 硬止损 ATR 倍数 |
| profit_drawdown_pct | 0.50 | BB 逆势分支利润回撤止盈比例（峰值 >$10 收紧至 35%） |
| mfi_reversal_pct | 15.0 | BB 顺势分支 MFI 反转止盈阈值（%） |
| bounce_bb_width | 0.5 | BB 逆势分支反弹目标 = 0.5 × 当前带宽 |
| _exit_cooldown_seconds | 900 | 盈利平仓后同方向冷却（秒） |
| breakeven_delay_seconds | 3600 | 保本出场延迟激活（秒） |
## 数据源
- 依赖指标：`close`, `rsi`, `mfi`, `bb`, `atr`