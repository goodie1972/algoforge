---
name: bakome_trinity_ea_original
magic: 880304
version: v1_original
display: BAKOME Trinity EA Original
display_en: BAKOME Trinity EA Original
desc: 多资产趋势追踪（H1 EMA34 + H4 EMA200）
desc_en: Multi-Asset Trend Following (H1 EMA34 + H4 EMA200) Type: Trend
type: 趋势
---

## 原始出处

| 项目 | 内容 |
|:----|:-----|
| 仓库 | [BakomeTrinityEA](https://github.com/BAKOME-Hub/BakomeTrinityEA) |
| 作者 | Bakome Fabrice Kitoko |
| 原始语言 | MQL5 |
| 移植版本 | v1_original（完整移植到 Python 系统） |

### 原始仓库说明

> Bakome Trinity EA - Multi-Asset Trading System supporting XAUUSD, GBPUSD, BTCUSD with Economic News Filter, No Grid/Martingale, Adaptive Risk.

## 策略逻辑

### 核心架构

H1 EMA34 + H4 EMA200 双时间框架趋势 → M5 入场确认 → ATR 风控

### 入场条件

**趋势判断（H1 + H4 双时间框架）：**
| # | 条件 | 方向 |
|:-:|:----|:----:|
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

### Entry Conditions

**Trend Judgment (H1 + H4 Dual Timeframe):**
| # | Condition | Direction |
|:-:|:---------|:--------:|
| 1 | H1 EMA34 > H4 EMA200 | Long (BUY) |
| 2 | H1 EMA34 < H4 EMA200 | Short (SELL) |

**M5 Entry Confirmation:**
- M5 close on the trend side (0.5% tolerance allowed)
- In bullish trend, M5 should not be significantly below H1 EMA34
- In bearish trend, M5 should not be significantly above H1 EMA34

**Session Filter:**
- London (7-11, UTC+3) and New York (13-17, UTC+3) sessions
- Asian session quiet
- No trading 30/20 min before/after economic news

### 出场逻辑
n### Exit Logic

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

- 最大同时持仓 1 张
- 每日最大交易 10 笔
- 经济新闻过滤（NFP/FOMC/CPI 前后禁入）
- 数据源: 全部指标从 DataFactory TA-Lib 读取