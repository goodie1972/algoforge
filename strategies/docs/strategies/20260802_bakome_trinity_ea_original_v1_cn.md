---
name: bakome_trinity_ea_original
magic: 880304
version: v1_original
display: BAKOME Trinity EA Original
desc: 多资产趋势追踪（H1 EMA34 + H4 EMA200）
type: 趋势
---

**适用周期：** M5（主执行）+ H1/H4（EMA34/EMA200 双时间框架趋势过滤）

## 原始出处
| 项目 | 内容 |
| --- | --- |
| 仓库 | [BakomeTrinityEA](https://github.com/BAKOME-Hub/BakomeTrinityEA) |
| 作者 | Bakome Fabrice Kitoko |
| 原始语言 | MQL5 |
| 移植版本 | v1_original（完整移植到 Python 系统） |
## 策略逻辑
### 核心架构
H1 EMA34 + H4 EMA200 双时间框架趋势 → M5 入场确认 → ATR 风控
### 入场条件
**趋势判断（H1 + H4 双时间框架）：**
| # | 条件 | 方向 |
| --- | --- | --- |
| 1 | H1 EMA34 > H4 EMA200 | 多头（BUY） |
| 2 | H1 EMA34 < H4 EMA200 | 空头（SELL） |
**M5 入场确认：**
- M5 收盘价位于趋势方向一侧（允许 0.5% 偏差）
- 多头趋势时 M5 不应大幅低于 H1 EMA34
- 空头趋势时 M5 不应大幅高于 H1 EMA34
**时段过滤：**
- 伦敦（7-11, UTC+3）和纽约（13-17, UTC+3）时段交易
- 亚洲时段静默
- 经济新闻前后 30/20 分钟禁止交易
### 出场逻辑
| # | 条件 | 说明 |
| --- | --- | --- |
| ① | ATR 硬止损 | 亏损达到 2.0×ATR 时平仓 |
| ② | 盈亏平衡 | 盈利达到 1.0×ATR 时移止损至入场价 |
| ③ | 追踪止损 | 盈利达到 1.5×ATR 时激活，步长 0.5×ATR |
## 参数说明
| 参数 | 取值 | 说明 |
| --- | --- | --- |
| TIMEFRAME | M5 | 主运行周期（H1+H4 双时间框架定趋势） |
| H1_EMA_FAST / H4_EMA_SLOW | 34 / 200 | H1 快线 / H4 慢线趋势均线 |
| LONDON_START_HOUR | 7 | 伦敦时段起点（+4h，UTC+3） |
| NEW_YORK_START_HOUR | 13 | 纽约时段起点（+4h，UTC+3） |
| USE_NEWS_FILTER | True | 经济新闻过滤开关 |
| NEWS_BLOCK_MINUTES_BEFORE / AFTER | 30 / 20 | 新闻前 / 后禁入分钟数 |
| ATR_SL_MULTIPLIER | 2.0 | 硬止损（×ATR） |
| ATR_TP_MULTIPLIER | 3.0 | 止盈（×ATR） |
| BE_TRIGGER_ATR | 1.0 | 盈亏平衡触发（×ATR） |
| TRAIL_START_ATR / TRAIL_STEP_ATR | 1.5 / 0.5 | 追踪止损激活 / 步长（×ATR） |
| MIN_ATR_POINTS | 100.0 | 最小 ATR（点），ATR < 100×0.01=1.0 禁交易 |
| MAX_SPREAD_POINTS | 50.0 | 最大点差（点） |
| FIXED_LOTS | 0.01 | 固定手数 |
| MAX_POSITIONS | 1 | 最大同时持仓 |
| MAX_DAILY_TRADES | 10 | 每日最大交易笔数 |
## 风控
- 止损止盈：硬止损 2.0×ATR，止盈 3.0×ATR（ATR 无效时回退固定百分比止损）
- 盈亏平衡：盈利达 1.0×ATR 移止损至入场价；追踪止损：盈利达 1.5×ATR 激活，距极值点 0.5×ATR 设止损线，跌破即平仓（`check_ema20_exit`）
- 低波动过滤：ATR < 1.0（MIN_ATR_POINTS×0.01）禁止交易；点差上限 50 点（MAX_SPREAD_POINTS）
- 新闻过滤：NFP 8:30 / FOMC 14:00 / CPI 13:30 前 30 分钟、后 20 分钟禁止交易（`_is_news_block`）
- 仓位限制：固定 0.01 手、最多同时持仓 1 张、每日最多 10 笔交易
## 特别规则
- 最大同时持仓 1 张
- 每日最大交易 10 笔
- 经济新闻过滤（NFP/FOMC/CPI 前后禁入）
- 数据源: 全部指标从 DataFactory TA-Lib 读取
