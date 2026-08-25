---
name: bakome_gold_scalper_original
magic: 880303
version: v1_original
display: BAKOME Gold Scalper Original
desc: 完整 ICT 策略（FVG + OB + Liquidity Sweep + Silver Bullet）
type: 反转
---

**适用周期：** M5（主执行）+ H4（EMA200 趋势 Bias 过滤）

## 原始出处
| 项目 | 内容 |
| --- | --- |
| 仓库 | [BAKOMEPythonGoldScalper](https://github.com/BAKOME-Hub/BAKOMEPythonGoldScalper) |
| 作者 | Bakome Fabrice Kitoko |
| 原始语言 | Python（1800+ 行） |
| 移植版本 | v1_original（完整 ICT 逻辑移植，仅适配系统接口） |
## 策略逻辑
### 核心架构
H4 EMA200 定趋势 Bias → Silver Bullet 时段 → M5 三重 ICT 确认 → ATR 风控
### 入场条件
**Bias 方向（H4 EMA200）：**
- 价格 > EMA200 → 多头偏多（BUY 方向）
- 价格 < EMA200 → 空头偏多（SELL 方向）
**三重 ICT 确认（至少 2 个成立）：**
| # | 条件 | 说明 |
| --- | --- | --- |
| 1 | Liquidity Sweep | 价格突破近期摆动高/低点后反转 |
| 2 | Fair Value Gap | 3-K线缺口模式检测 |
| 3 | Order Block | 强势突破前的反向 K 线作为支撑/阻力区 |
**时段过滤：**
- 仅 Silver Bullet 时段交易：伦敦 8-9 点、纽约 15-16 点（MT4 时区 UTC+3）
- 仅伦敦/纽约时段交易，亚洲时段静默
### 出场逻辑
| # | 条件 | 说明 |
| --- | --- | --- |
| ① | ATR 硬止损 | 亏损达到 2.0×ATR 时平仓 |
| ② | 盈亏平衡 | 盈利达到 1.0×ATR 时移止损至入场价 |
| ③ | 追踪止损 | 盈利达到 1.5×ATR 时激活，步长 0.5×ATR |
## 参数说明
| 参数 | 取值 | 说明 |
| --- | --- | --- |
| TIMEFRAME | M5 | 主运行周期（H4 EMA200 定趋势 Bias） |
| H4_EMA_SLOW | 200 | H4 趋势 Bias 均线 |
| LIQUIDITY_LOOKBACK | 50 | Liquidity Sweep 摆动点回看根数 |
| FVG_LOOKBACK | 20 | FVG 检测回看根数 |
| FVG_MIN_SIZE_ATR | 0.5 | FVG 最小缺口（×ATR） |
| SIGNAL_MIN_CONFIRMATIONS | 2 | LS/FVG/OB 三重确认最少成立数 |
| LONDON_KILL_ZONE | 8–9 | 伦敦 Silver Bullet 时段（UTC+3） |
| NY_KILL_ZONE | 15–16 | 纽约 Silver Bullet 时段（UTC+3） |
| ATR_SL_MULTIPLIER | 2.0 | 硬止损（×ATR） |
| ATR_TP_MULTIPLIER | 3.0 | 止盈（×ATR） |
| BE_TRIGGER_ATR | 1.0 | 盈亏平衡触发（×ATR） |
| TRAIL_START_ATR / TRAIL_STEP_ATR | 1.5 / 0.5 | 追踪止损激活 / 步长（×ATR） |
| MIN_ATR_POINTS | 100.0 | 最小 ATR（点），ATR < 100×0.01=1.0 禁交易 |
| MAX_SPREAD_POINTS | 50.0 | 最大点差（点） |
| FIXED_LOTS | 0.01 | 固定手数 |
| MAX_POSITIONS | 2 | 最大同时持仓 |
| MAX_DAILY_TRADES | 10 | 每日最大交易笔数 |
## 风控
- 止损止盈：硬止损 2.0×ATR，止盈 3.0×ATR（ATR 无效时回退固定百分比止损）
- 盈亏平衡：盈利达 1.0×ATR 移止损至入场价；追踪止损：盈利达 1.5×ATR 激活，距极值点 0.5×ATR 设止损线，跌破即平仓（`check_ema20_exit`）
- 低波动过滤：ATR < 1.0（MIN_ATR_POINTS×0.01）禁止交易；点差上限 50 点（MAX_SPREAD_POINTS）
- 仓位限制：固定 0.01 手、最多同时持仓 2 张、每日最多 10 笔交易
## 特别规则
- 最大同时持仓 2 张
- 每日最大交易 10 笔
- ATR < 1.0 时禁止交易（低波动过滤）
- 数据源: 全部指标从 DataFactory TA-Lib 读取
