---
name: viprasol_sniper
magic: 661401
type: 其他
display: Viprasol Sniper — 7因子共识 + 多级RR出场
desc: H1 7因子评分系统，多级RR出场（1R/2R/3R/4R/5R）
---

**适用周期：** M30

## 评分因子
| # | 因子 | 得分 | 说明 |
|---|---|---|---|
| ① | 价格 vs EMA | +1 | close > EMA21（VWAP 替代） |
| ② | RSI 方向 | +1 | RSI(14) > 50 |
| ③ | MACD 方向 | +1 | MACD(12,26,9) > 0 |
| ④ | EMA 排列 | +1 | EMA9 > EMA21 |
| ⑤ | ADX+DI | +1 | ADX>25 且 +DI > -DI |
| ⑥ | 成交量确认 | +1 | 成交量 > 前 20 根均值 × 1.2，且为阳线 |
| ⑦ | 次级 RSI | +1 | M15 RSI(14) > 50 |
| ① | 价格 vs EMA | +1 | close < EMA21 |
| ② | RSI 方向 | +1 | RSI(14) < 50 |
| ③ | MACD 方向 | +1 | MACD(12,26,9) < 0 |
| ④ | EMA 排列 | +1 | EMA9 < EMA21 |
| ⑤ | ADX+DI | +1 | ADX>25 且 -DI > +DI |
| ⑥ | 成交量确认 | +1 | 成交量 > 前 20 根均值 × 1.2，且为阴线 |
| ⑦ | 次级 RSI | +1 | M15 RSI(14) < 50 |
**阈值：** ≥4/7 因子触发，且优势方向得分必须大于另一方。
## 出场逻辑
| # | 条件 | 说明 |
|---|---|---|
| ① | TP1（1R） | 触发后移至保本 |
| ② | TP2（2R） | 盈利 2 倍风险出局 |
| ③ | TP3（3R） | 盈利 3 倍风险出局 |
| ④ | TP4（4R） | 盈利 4 倍风险出局 |
| ⑤ | TP5（5R） | 盈利 5 倍风险出局 |
| ⑥ | ATR 移动追踪 | 峰值回撤超过 1.0 ATR 且峰值利润 > 0.5ATR |
| ⑦ | 硬止损 | 亏损超过 1.5 ATR |
**RR 出场：** 入场时锁定 1R = SL_ATR × ATR，各级 TP 价位基于锁定的 1R（不随后续 ATR 漂移）。
## 风控
- 方向优势：优势方向得分必须严格大于另一方且 ≥阈值才触发
- 初始止损：1.5×ATR（=1R），订单级挂出
- 保本移位：盈利触及 1R 后将订单 SL 移至入场价
- 移动追踪：峰值回撤超过 1.0×ATR 且峰值利润 >0.5×ATR 才触发出场
- 硬止损：亏损超过 1.5×ATR 出场
- 最大持仓：1 单（STRATEGY_POOL 配置）
## 参数说明
| 参数 | 取值 | 说明 |
|---|---|---|
| score_threshold | 4 | 7 因子触发阈值（≥4/7） |
| sl_atr | 1.5 | 初始止损 ATR 倍数（=1R） |
| breakeven_r | 1.0 | 保本激活级别（1R 命中后移动止损至入场价） |
| rr_levels | [2, 3, 4, 5] | 逐级出场 RR 级别（2R/3R/4R/5R） |
| trail_atr | 1.0 | 移动追踪 ATR 倍数 |
| rsi_period / atr_period | 14 / 14 | RSI、ATR 计算周期 |
| ema_fast / ema_slow | 9 / 21 | EMA 排列快慢线 |
## 特别规则
- 来源：TradingView Viprasol Sniper Confluence Entry/Exit
- K 线收盘确认入场
- 数据源：全部指标从 DataFactory TA-Lib 读取