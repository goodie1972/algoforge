---
name: multi_confluence_quant
magic: 661601
type: 评分
display: Multi-Confluence Quant — 14因子综合评分
desc: H1 14个技术指标因子评分，≥10/14触发信号
---

**适用周期：** M30

## 评分因子
| # | 因子 | 得分 | 说明 |
|---|---|---|---|
| ① | EMA Ribbon | +1 | EMA20 > EMA50 |
| ② | 长期趋势 | +1 | close > EMA200 |
| ③ | RSI 方向 | +1 | RSI(14) > 50 |
| ④ | ADX 趋势确认 | +1 | ADX > 20（多空均加分，表示有趋势） |
| ⑤ | 线性回归斜率 | +1 | 20 根线性回归斜率 > 0 |
| ⑥ | 成交量 | +1 | 成交量 > 前 20 根均值，且为阳线 |
| ⑦ | HTF 趋势 | +1 | H1 close > H1 EMA50 |
| ⑧ | Stoch RSI | +1 | K > 50 |
| ⑨ | MACD | +1 | MACD > 0 |
| ⑩ | 波动扩张 | +1 | ATR > ATR20 × 1.1，且做多方向占优 |
| ⑪ | BB 位置 | +1 | price_pos > 0.5（在上半区） |
| ⑫ | 结构突破 | +1 | close 为 20 根最高（HH20） |
| ⑬ | DI 方向 | +1 | +DI > -DI |
| ⑭ | RSI 过度延伸 | -1 | RSI > 70 时扣分（超买不追多） |
| ① | EMA Ribbon | +1 | EMA20 < EMA50 |
| ② | 长期趋势 | +1 | close < EMA200 |
| ③ | RSI 方向 | +1 | RSI(14) < 50 |
| ④ | ADX 趋势确认 | +1 | ADX > 20（多空均加分） |
| ⑤ | 线性回归斜率 | +1 | 20 根线性回归斜率 < 0 |
| ⑥ | 成交量 | +1 | 成交量 > 前 20 根均值，且为阴线 |
| ⑦ | HTF 趋势 | +1 | H1 close < H1 EMA50 |
| ⑧ | Stoch RSI | +1 | K < 50 |
| ⑨ | MACD | +1 | MACD < 0 |
| ⑩ | 波动扩张 | +1 | ATR > ATR20 × 1.1，且做空方向占优 |
| ⑪ | BB 位置 | +1 | price_pos < 0.5（在下半区） |
| ⑫ | 结构突破 | +1 | close 为 20 根最低（LL20） |
| ⑬ | DI 方向 | +1 | -DI > +DI |
| ⑭ | RSI 过度延伸 | -1 | RSI < 30 时扣分（超卖不做空） |
**阈值：** ≥10/14 = SIGNAL，≥11/14 = God-Tier，且该方向得分须高于对手方向。
## 出场逻辑
| # | 条件 | 说明 |
|---|---|---|
| ① | 利润回撤止盈 | 峰值利润回撤 25%（峰值 > 0.5ATR） |
| ② | ATR 移动追踪 | 峰值回撤超过 1.5 ATR |
| ③ | 硬止损 | 亏损超过 2.0 ATR |
## 风控
- 方向优势：该方向得分须严格高于对手方向才触发
- 硬止损：亏损超过 2.0×ATR 出场（订单级 SL 亦按 2.0×ATR 挂出）
- 移动追踪：峰值回撤超过 1.5×ATR 出场
- 利润回撤止盈：峰值利润 >0.5×ATR 后回撤达 25% 出场
- 最大持仓：1 单（STRATEGY_POOL 配置）
## 参数说明
| 参数 | 取值 | 说明 |
|---|---|---|
| score_threshold | 10 | SIGNAL 触发阈值（≥10/14） |
| god_threshold | 11 | God-Tier 等级阈值（≥11/14） |
| ema_fast / ema_slow / ema_long | 20 / 50 / 200 | EMA Ribbon 与长期趋势均线 |
| rsi_period | 14 | RSI 计算周期 |
| sl_atr | 2.0 | 硬止损 ATR 倍数 |
| tp1_atr / tp2_atr | 2.0 / 4.0 | 订单级 TP 两档（默认挂 TP1） |
| trail_atr | 1.5 | 移动追踪 ATR 倍数 |
## 特别规则
- 覆盖趋势/动量/波动/成交量/结构 5 大类别
- 来源：TradingView Multi-Confluence Quant Crypto Engine [QuantSovereign]
- 数据源：全部指标从 DataFactory TA-Lib 读取