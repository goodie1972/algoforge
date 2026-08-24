---
name: viprasol_sniper
magic: 661401

type: 其他
display: Viprasol Sniper — 7因子共识 + 多级RR出场
display_en: Viprasol Sniper — 7-Factor Consensus + Multi-Level RR Exit
desc: H1 7因子评分系统，多级RR出场（1R/2R/3R/4R/5R）
desc_en: H1 7-factor scoring, multi-level RR exit (1R/2R/3R/4R/5R)
---

## 评分因子

### BUY（做多）
### BUY (Long)
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | 价格 vs EMA | +1 | close > EMA21（VWAP 替代） |
| ② | RSI 方向 | +1 | RSI(14) > 50 |
| ③ | MACD 方向 | +1 | MACD(12,26,9) > 0 |
| ④ | EMA 排列 | +1 | EMA9 > EMA21 |
| ⑤ | ADX+DI | +1 | ADX>25 且 +DI > -DI |
| ⑥ | 成交量确认 | +1 | 成交量 > 前 20 根均值 × 1.2，且为阳线 |
| ⑦ | 次级 RSI | +1 | M15 RSI(14) > 50 |

### SELL（做空）
### SELL (Short)
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | 价格 vs EMA | +1 | close < EMA21 |
| ② | RSI 方向 | +1 | RSI(14) < 50 |
| ③ | MACD 方向 | +1 | MACD(12,26,9) < 0 |
| ④ | EMA 排列 | +1 | EMA9 < EMA21 |
| ⑤ | ADX+DI | +1 | ADX>25 且 -DI > +DI |
| ⑥ | 成交量确认 | +1 | 成交量 > 前 20 根均值 × 1.2，且为阴线 |
| ⑦ | 次级 RSI | +1 | M15 RSI(14) < 50 |

**阈值：** ≥4/7 因子触发，且优势方向得分必须大于另一方。

## Scoring Factors

### BUY（做多）
### BUY (Long)
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | 价格 vs EMA | +1 | close > EMA21（VWAP 替代） |
| ② | RSI 方向 | +1 | RSI(14) > 50 |
| ③ | MACD 方向 | +1 | MACD(12,26,9) > 0 |
| ④ | EMA 排列 | +1 | EMA9 > EMA21 |
| ⑤ | ADX+DI | +1 | ADX>25 且 +DI > -DI |
| ⑥ | 成交量确认 | +1 | 成交量 > 前 20 根均值 × 1.2，且为阳线 |
| ⑦ | 次级 RSI | +1 | M15 RSI(14) > 50 |

### SELL（做空）
### SELL (Short)
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | 价格 vs EMA | +1 | close < EMA21 |
| ② | RSI 方向 | +1 | RSI(14) < 50 |
| ③ | MACD 方向 | +1 | MACD(12,26,9) < 0 |
| ④ | EMA 排列 | +1 | EMA9 < EMA21 |
| ⑤ | ADX+DI | +1 | ADX>25 且 -DI > +DI |
| ⑥ | 成交量确认 | +1 | 成交量 > 前 20 根均值 × 1.2，且为阴线 |
| ⑦ | 次级 RSI | +1 | M15 RSI(14) < 50 |

**阈值：** ≥4/7 因子触发，且优势方向得分必须大于另一方。

## 出场逻辑

## Exit Logic

| # | 条件 | 说明 |  |
|:-:|:----|:----|
| ① | TP1 (1R) | Move stop to breakeven after trigger |  |
| ② | TP2 (2R) | Exit at 2x risk profit |  |
| ③ | TP3 (3R) | Exit at 3x risk profit |  |
| ④ | TP4 (4R) | Exit at 4x risk profit |  |
| ⑤ | TP5 (5R) | Exit at 5x risk profit |  |
| ⑥ | ATR Moving Trailing | Peak drawdown exceeds 1.0 ATR and peak profit > 0.5 ATR |  |
| ⑦ | Hard Stop | Loss exceeds 1.5 ATR |  |

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | TP1（1R） | 触发后移至保本 |
| ② | TP2（2R） | 盈利 2 倍风险出局 |
| ③ | TP3（3R） | 盈利 3 倍风险出局 |
| ④ | TP4（4R） | 盈利 4 倍风险出局 |
| ⑤ | TP5（5R） | 盈利 5 倍风险出局 |
| ⑥ | ATR 移动追踪 | 峰值回撤超过 1.0 ATR 且峰值利润 > 0.5ATR |
| ⑦ | 硬止损 | 亏损超过 1.5 ATR |

**RR 出场：** 入场时锁定 1R = SL_ATR × ATR，各级 TP 价位基于锁定的 1R（不随后续 ATR 漂移）。

## 特别规则

- 来源：TradingView Viprasol Sniper Confluence Entry/Exit
- K 线收盘确认入场
- 数据源：全部指标从 DataFactory TA-Lib 读取

## Special Rules

- 来源：TradingView Viprasol Sniper Confluence Entry/Exit
- K 线收盘确认入场
- 数据源：全部指标从 DataFactory TA-Lib 读取
