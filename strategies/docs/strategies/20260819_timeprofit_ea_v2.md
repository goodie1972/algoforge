---
name: timeprofit_ea
magic: 880202

type: 趋势
display: TimeProfit EA — H2趋势 + M5入场 + 整数关口箱体
display_en: TimeProfit EA — H2 Trend + M5 Entry + Round Number Box
desc: 原始 TimeProfitEA 移植，H2趋势判断，100美金整数关口箱体交易，ATR风控
desc_en: Original TimeProfitEA port, H2 trend, 00 round-number box trading
---

## 原始出处

- **GitHub:** [caoruihua/sanqing-ea-mt5](https://github.com/caoruihua/sanqing-ea-mt5)
- **语言:** MQL5 (MT5) → Python 移植
- **作者:** caoruihua
- **说明:** 一个 H2 趋势 + M5 入场的整数关口箱体交易策略，核心文件为 `TimeProfitEA.mq5`，回测 188 笔交易，Profit Factor 2.03，胜率 38.3%。

## 评分因子

### BUY（做多）
### BUY (Long)
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| 1 | H2 趋势向上 | +1 | EMA10 > EMA30 且间距≥$1.0 |
| 2 | 回弹入场 | +1 | 价格从上方关口回弹到下方关口附近 |
| 3 | 突破入场 | +1 | 价格强势突破上方关口 |

### SELL（做空）
### SELL (Short)
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| 1 | H2 趋势向下 | +1 | EMA10 < EMA30 且间距≥$1.0 |
| 2 | 回弹入场 | +1 | 价格从下方关口反弹到上方关口附近 |
| 3 | 突破入场 | +1 | 价格跌破下方关口 |

## 入场逻辑

### 趋势判断（H2）
- 快 EMA: 10 (H2) / M5 替代: 120
- 慢 EMA: 30 (H2) / M5 替代: 300
- 最小趋势间距: $1.0 (避免盘整期)
- 趋势中性时不交易

### 整数关口箱体（100 美金间隔）
- XAUUSD 在 100 美金整数关口（如 2300, 2400, 2500...）存在明显的支撑/阻力
- 关口附近 ±$4 为禁入区（避免假突破）
- 回弹区域：距关口 $70 以内（趋势中的回弹）
- 突破入场：价格突破关口 $4 以上

### M5 入场确认
- K 线方向需与趋势一致（可配置 `REQUIRE_CANDLE_DIRECTION`）
- 回弹方向和突破方向均需与 H2 趋势一致

## 出场逻辑

## Exit Logic

| # | 条件 | 说明 |  |
|:-:|:----|:----|
| ① | Fixed Stop | 3.0×ATR (minimum $5) |  |
| ② | Round-Number TP | Take profit $3 before price reaches nearest round number level |  |
| ③ | Min TP Distance | Skip signal when take-profit distance < $10 |  |

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 固定止损 | 3.0×ATR（最小 $5） |
| ② | 整数关口止盈 | 价格到达最近整数关口前 $3 止盈 |
| ③ | 最小止盈距离 | 止盈距离 < $10 时跳过该信号 |

## 特别规则

- 冷却期: 任何平仓后 10 分钟内不交易
- 盈利平仓冷却: 同方向 5 分钟内不重复开仓
- 数据源: 全部指标从 DataFactory TA-Lib 读取

## Special Rules

- 冷却期: 任何平仓后 10 分钟内不交易
- 盈利平仓冷却: 同方向 5 分钟内不重复开仓
- 数据源: 全部指标从 DataFactory TA-Lib 读取