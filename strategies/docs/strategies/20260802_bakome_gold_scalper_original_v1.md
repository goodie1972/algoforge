---
name: bakome_gold_scalper_original
magic: 880303
version: v1_original
display: BAKOME Gold Scalper Original
display_en: BAKOME Gold Scalper Original
desc: 完整 ICT 策略（FVG + OB + Liquidity Sweep + Silver Bullet）
desc_en: Complete ICT Strategy (FVG + OB + Liquidity Sweep + Silver Bullet) type: Reversal
type: 反转
---

## 原始出处

| 项目 | 内容 |
|:----|:-----|
| 仓库 | [BAKOMEPythonGoldScalper](https://github.com/BAKOME-Hub/BAKOMEPythonGoldScalper) |
| 作者 | Bakome Fabrice Kitoko |
| 原始语言 | Python（1800+ 行） |
| 移植版本 | v1_original（完整 ICT 逻辑移植，仅适配系统接口） |

### 原始仓库说明

> Professional algorithmic trading system for XAUUSD (Gold) implementing ICT concepts (FVG, Order Blocks, Liquidity Sweeps, Silver Bullet) with full risk management, backtesting engine, and live trading capabilities.

## Original Source

| 项目 | 内容 |
|:----|:-----|
| 仓库 | [BAKOMEPythonGoldScalper](https://github.com/BAKOME-Hub/BAKOMEPythonGoldScalper) |
| 作者 | Bakome Fabrice Kitoko |
| 原始语言 | Python（1800+ 行） |
| 移植版本 | v1_original（完整 ICT 逻辑移植，仅适配系统接口） |

### 原始仓库说明

> Professional algorithmic trading system for XAUUSD (Gold) implementing ICT concepts (FVG, Order Blocks, Liquidity Sweeps, Silver Bullet) with full risk management, backtesting engine, and live trading capabilities.

## 策略逻辑

### 核心架构

H4 EMA200 定趋势 Bias → Silver Bullet 时段 → M5 三重 ICT 确认 → ATR 风控

### 入场条件

**Bias 方向（H4 EMA200）：**
- 价格 > EMA200 → 多头偏多（BUY 方向）
- 价格 < EMA200 → 空头偏多（SELL 方向）

**三重 ICT 确认（至少 2 个成立）：**
| # | 条件 | 说明 |
|:-:|:----|:----|
| 1 | Liquidity Sweep | 价格突破近期摆动高/低点后反转 |
| 2 | Fair Value Gap | 3-K线缺口模式检测 |
| 3 | Order Block | 强势突破前的反向 K 线作为支撑/阻力区 |

**时段过滤：**
- 仅 Silver Bullet 时段交易：伦敦 8-9 点、纽约 15-16 点（MT4 时区 UTC+3）
- 仅伦敦/纽约时段交易，亚洲时段静默

### Entry Conditions

**Bias Direction (H4 EMA200):**
- Price > EMA200 → Bullish bias (BUY direction)
- Price < EMA200 → Bearish bias (SELL direction)

**Triple ICT Confirmation (at least 2 must hold):**
| # | Condition | Description |
|:-:|:---------|:------------|
| 1 | Liquidity Sweep | Price breaks recent swing high/low then reverses |
| 2 | Fair Value Gap | 3-candle gap pattern detection |
| 3 | Order Block | Reversal candle before strong breakout as S/R zone |

**Session Filter:**
- Silver Bullet sessions only: London 8-9, New York 15-16 (MT4 UTC+3)
- London/New York sessions only, Asian session quiet

### 出场逻辑
### Exit Logic

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR 硬止损 | 亏损达到 2.0×ATR 时平仓 |
| ② | 盈亏平衡 | 盈利达到 1.0×ATR 时移止损至入场价 |
| ③ | 追踪止损 | 盈利达到 1.5×ATR 时激活，步长 0.5×ATR |

### Exit Logic

| # | Condition | Description |
|:-:|:---------|:------------|
| ① | ATR Hard Stop | Close at 2.0×ATR loss |
| ② | Breakeven | Move SL to entry after 1.0×ATR profit |
| ③ | Trailing Stop | Activate at 1.5×ATR profit, step 0.5×ATR |

## Strategy Logic

### 核心架构

H4 EMA200 定趋势 Bias → Silver Bullet 时段 → M5 三重 ICT 确认 → ATR 风控

### 入场条件

**Bias 方向（H4 EMA200）：**
- 价格 > EMA200 → 多头偏多（BUY 方向）
- 价格 < EMA200 → 空头偏多（SELL 方向）

**三重 ICT 确认（至少 2 个成立）：**
| # | 条件 | 说明 |
|:-:|:----|:----|
| 1 | Liquidity Sweep | 价格突破近期摆动高/低点后反转 |
| 2 | Fair Value Gap | 3-K线缺口模式检测 |
| 3 | Order Block | 强势突破前的反向 K 线作为支撑/阻力区 |

**时段过滤：**
- 仅 Silver Bullet 时段交易：伦敦 8-9 点、纽约 15-16 点（MT4 时区 UTC+3）
- 仅伦敦/纽约时段交易，亚洲时段静默

### Entry Conditions

**Bias Direction (H4 EMA200):**
- Price > EMA200 → Bullish bias (BUY direction)
- Price < EMA200 → Bearish bias (SELL direction)

**Triple ICT Confirmation (at least 2 must hold):**
| # | Condition | Description |
|:-:|:---------|:------------|
| 1 | Liquidity Sweep | Price breaks recent swing high/low then reverses |
| 2 | Fair Value Gap | 3-candle gap pattern detection |
| 3 | Order Block | Reversal candle before strong breakout as S/R zone |

**Session Filter:**
- Silver Bullet sessions only: London 8-9, New York 15-16 (MT4 UTC+3)
- London/New York sessions only, Asian session quiet

### 出场逻辑
### Exit Logic

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | ATR 硬止损 | 亏损达到 2.0×ATR 时平仓 |
| ② | 盈亏平衡 | 盈利达到 1.0×ATR 时移止损至入场价 |
| ③ | 追踪止损 | 盈利达到 1.5×ATR 时激活，步长 0.5×ATR |

### Exit Logic

| # | Condition | Description |
|:-:|:---------|:------------|
| ① | ATR Hard Stop | Close at 2.0×ATR loss |
| ② | Breakeven | Move SL to entry after 1.0×ATR profit |
| ③ | Trailing Stop | Activate at 1.5×ATR profit, step 0.5×ATR |

## 特别规则

- 最大同时持仓 2 张
- 每日最大交易 10 笔
- ATR < 1.0 时禁止交易（低波动过滤）
- 数据源: 全部指标从 DataFactory TA-Lib 读取

## Special Rules

- 最大同时持仓 2 张
- 每日最大交易 10 笔
- ATR < 1.0 时禁止交易（低波动过滤）
- 数据源: 全部指标从 DataFactory TA-Lib 读取