---
name: timeprofit_ea
magic: 880202
type: 趋势
display: TimeProfit EA — H2趋势 + M5入场 + 整数关口箱体
desc: 原始 TimeProfitEA 移植，H2趋势判断，100美金整数关口箱体交易，ATR风控
---

**适用周期：** M5（主执行）+ H2（EMA10/EMA30 趋势过滤）

## 原始出处
- **语言:** MQL5 (MT5) → Python 移植
- **作者:** caoruihua
- **说明:** 一个 H2 趋势 + M5 入场的整数关口箱体交易策略，核心文件为 `TimeProfitEA.mq5`，回测 188 笔交易，Profit Factor 2.03，胜率 38.3%。
## 评分因子
| # | 因子 | 得分 | 说明 |
| --- | --- | --- | --- |
| 1 | H2 趋势向上 | +1 | EMA10 > EMA30 且间距≥$1.0 |
| 2 | 回弹入场 | +1 | 价格从上方关口回弹到下方关口附近 |
| 3 | 突破入场 | +1 | 价格强势突破上方关口 |
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
- K 线方向需与趋势一致（可配置 `REQUIRE_CANDLE_DIRECTION`）
- 回弹方向和突破方向均需与 H2 趋势一致
## 出场逻辑
| # | 条件 | 说明 |
| --- | --- | --- |
| ① | 固定止损 | 3.0×ATR（最小 $5） |
| ② | 整数关口止盈 | 价格到达最近整数关口前 $3 止盈 |
| ③ | 最小止盈距离 | 止盈距离 < $10 时跳过该信号 |
## 参数说明
| 参数 | 取值 | 说明 |
| --- | --- | --- |
| TIMEFRAME | M5 | 主运行周期（H2 定趋势，M5 EMA120/300 回退近似） |
| TREND_FAST_EMA / TREND_SLOW_EMA | 10 / 30 | H2 趋势 EMA |
| MIN_TREND_GAP_DOLLARS | 1.0 | 最小趋势 EMA 间距（美元） |
| M5_ENTRY_EMA | 10 | 回弹入场触碰确认均线（v2） |
| M5_ENTRY_EMA_CONFIRM | True | v2：回弹入场需价格触碰 M5 EMA10 |
| REQUIRE_CANDLE_DIRECTION | True | M5 K 线方向需与趋势一致 |
| USE_PULLBACK_ENTRY / USE_BREAKOUT_ENTRY | True / True | 回弹入场 / 突破入场开关 |
| PULLBACK_DISTANCE | 70.0 | 回弹区域距关口边缘（美元） |
| LEVEL_STEP | 100.0 | 整数关口间隔（美元） |
| NO_TRADE_DISTANCE | 4.0 | 关口附近禁入距离（美元） |
| TP_BUFFER | 3.0 | 关口前止盈缓冲（美元） |
| MIN_TP_DISTANCE | 10.0 | 最小止盈距离（美元） |
| ATR_PERIOD | 14 | ATR 周期 |
| ATR_STOP_MULT | 3.0 | 止损 = ATR × 3.0 |
| MIN_STOP_DISTANCE | 5.0 | 最小止损距离（美元） |
| FIXED_LOTS | 0.01 | 固定手数 |
| COOLDOWN_MINUTES | 10 | 任何平仓后冷却分钟数 |
| _exit_cooldown_seconds | 300 | 盈利平仓后同方向冷却（秒） |
## 风控
- 止损：3.0×ATR，最小 $5（MIN_STOP_DISTANCE）；无止盈倍数，整数关口前 $3（TP_BUFFER）止盈，止盈距离 < $10（MIN_TP_DISTANCE）时改用下一关口
- 冷却机制：任何平仓后 10 分钟禁开新仓（COOLDOWN_MINUTES）；盈利平仓后同方向 5 分钟（300 秒）禁重复开仓
- 关口禁入区：价格距任一整数关口 < $4（NO_TRADE_DISTANCE）不交易，避免假突破
- 固定 0.01 手、最大滑点 30
## 特别规则
- 冷却期: 任何平仓后 10 分钟内不交易
- 盈利平仓冷却: 同方向 5 分钟内不重复开仓
- 数据源: 全部指标从 DataFactory TA-Lib 读取
