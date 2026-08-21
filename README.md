<p align="center">
  <img src="docs/assets/logo.svg" width="120" height="120" alt="AlgoForge Logo">
</p>

<h1 align="center">AlgoForge</h1>

<p align="center"><strong>XAUUSD 黄金自动化交易系统 · Algorithmic + Forge = 算法锻造工坊</strong> — 多策略并行、全面风控、实时 Web 监控的专业黄金自动化交易平台。</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/MetaTrader4-FreeMT4Bridge-orange" alt="MT4">
  <img src="https://img.shields.io/badge/SQLite-003B57?logo=sqlite" alt="SQLite">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/version-3.3.8-gold" alt="Version">
</p>

<p align="center">
  🌐 <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a>
</p>

---

## Features

> 从数据采集到交易执行，从信号回放到复盘，**全链路追踪**。

### 🎯 多策略并行
- **25+ 策略同时运行**，独立 Magic Number 和风控状态
- 自动扫描 `strategies/` 目录发现新策略，**零配置注册**
- 分类覆盖：趋势跟踪 / 反转交易 / 突破交易 / 评分模型 / 组合策略

### 🏗️ 三轨架构
- **DataFactory**（数据采集 + 指标计算）→ **策略员**（信号评分）→ **Athlete**（tick 验证入场）
- 分工明确、职责单一，实时重算入场条件，10 秒过期作废

### 🛡️ 完整风控
- **三层止盈出场** + **ATR 移动止盈** + **ATR 硬止损**
- **GateManager**（时间/波动/趋势/亏损门）· **RiskManager**（单笔/敞口/持仓上限）· **TradeManager**（订单/滑点/Magic 隔离）三层管理体系

### 📊 数据驱动
- DataFactory 统一计算 **26 个 TA-Lib 指标**，F043 MT4 值优先
- 指标在策略间**共享**，绝不重复计算
- M5 / M15 / M30 / H1 / H4 多周期覆盖

### 🧪 纸面测试
- 信号全量模拟入场 + 出场，按策略规则模拟平仓
- 真实成交价计算盈亏，**上线前充分验证**

### 💪 自修复监控
- 5 分钟自动检查引擎状态，崩溃 / 桥接断线**自动重启**
- 实时 WebSocket 推送，日志全链路追踪

---

## Quick Start — 60 Seconds

### Prerequisites

| Dependency | Purpose |
|:-----------|:--------|
| Python 3.10+ | Engine & backend |
| MetaTrader 4 | Logged into an XAUUSD account |
| FreeMT4Bridge EA | Loaded on an XAUUSD chart (M5 timeframe) |
| Node.js 18+ | Frontend build |

### One-command start

```bash
python start.py
```

Or start backend + engine directly:

```bash
python dashboard/backend/main.py
```

### Open the dashboard

```
http://localhost:1783
```

---

## Architecture

```
Data Flow:  MT4 → FreeMT4Bridge EA → core/bridge.py → DataFactory → 策略员 → Athlete → 下单
```

```
┌─────────────────────────────────────────────────────────┐
│               MT4 + FreeMT4Bridge EA (TCP :23232)       │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                  core/bridge.py                         │
│              桥接抽象层 (MT4 ⇄ Python)                    │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              TradingEngine（三轨架构）                    │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 轨1: DataFactory（独立线程）                      │   │
│  │   → 增量拉取 K 线 → TA-Lib 统一计算 26 指标        │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ 轨2: 策略员（主循环）                             │   │
│  │   → get_indicator() 读缓存 → 评分出门票           │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ 轨3: Athlete（tick 验证层）                      │   │
│  │   → _verify_entry 实时重算 → 10 秒过期           │   │
│  └──────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              Dashboard（Web 监控）                       │
│  ┌──────────────┐  ┌────────────────────────────────┐   │
│  │ FastAPI :1783│  │ Vue 3 + Naive UI              │   │
│  │ + WebSocket  │  │ lightweight-charts            │   │
│  └──────────────┘  └────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Three-Rail Detail

| Rail | Component | Responsibility |
|:-----|:----------|:---------------|
| **1** | DataFactory | Dedicated thread, incremental K-line fetch, 26 TA-Lib indicators |
| **2** | Strategist | Main loop, `get_indicator(key)` cache, scoring emits tickets |
| **3** | Athlete | Tick verification, `_verify_entry` real-time recheck, 10s expiry |

---

## Screenshots

| Module | Highlights |
|:-------|:-----------|
| **Dashboard** | Engine status, account overview, real-time signals |
| **Strategy Hub** | Strategy management, on/off control, Magic config |
| **Positions** | Real-time positions, manual close, PnL stats |
| **Trades** | Trade history, PnL analysis, filter & search |
| **Logs** | Full-chain log tracking, real-time filtering |

---

## Strategy Directory

> 基于回测筛选，以下策略当前在线运行（分类：趋势 / 反转 / 评分 / 突破 / 剥头皮）。

| Strategy | Type | Timeframe | Magic | Note |
|:---------|:-----|:---------:|:-----:|:-----|
| `sanqing_h1_upgraded` | Trend | H1 | 880108 | ADX adaptive exits |
| `gold_auto_research` | Scoring | H1 | 880306 | Stoch/RSI/EMA composite |
| `stoch_trend_h1_optimized` | Trend | H1 | 661202 | Stoch + trend gate |
| `goodma` | Trend | H1 | 880401 | 60MA direction + pullback |
| `kiss` | Trend | H1 | 880501 | H4 MACD + H1 MA + pivot |
| `rsi_grading_m30_upgraded` | Scoring | M30 | 660904 | RSI gradient scoring |
| `m30_bb_deepreturn_optimized` | Reversal | M30 | 661102 | BB deep return |
| `fish_eaten` | Reversal | M30 | 661301 | RSI+MFI+BB fish exit |
| `m30_followave` | Trend | M30 | 661402 | Stoch+BBI+BB + 2.0×ATR trailing |
| `m15_followave` | Trend | M15 | 661401 | Stoch+BBI+BB trend following |
| `timeprofit_ea` | Scalping | M5 | 880202 | Time-based profit EA |

> Strategy source & docs live in the separate **algoforge-strategies** repository.

---

## Technology Stack

| Layer | Tech | Purpose |
|:------|:-----|:--------|
| Bridge | FreeMT4Bridge EA (MQL4) | TCP socket comms |
| Engine | Python 3.10+ | Strategy exec, risk, orders |
| Backend | FastAPI + WebSocket | REST API, real-time push |
| Frontend | Vue 3 + TypeScript + Vite | Monitoring dashboard |
| UI | Naive UI | Component library |
| Charts | lightweight-charts | K-line rendering |
| Database | SQLite | Market, trades, signals |

---

## Repository Structure

```
AlgoForge/
├── config/                  # Configuration
├── core/                    # bridge / risk / trade / gate managers
├── engine_standalone/       # TradingEngine (three-rail loop)
├── strategies/              # Framework (base/scanner) — strategies live in algoforge-strategies
├── dashboard/
│   ├── backend/             # FastAPI + routes
│   └── frontend/            # Vue 3 + Naive UI
├── services/                # data_factory / news / llm / supervisor
├── backtest/                # backtest scripts & results
├── data/                    # SQLite database
├── logs/                    # runtime logs
└── docs/                    # documentation
```

> **Strategies live in [algoforge-strategies](https://github.com/goodie1972/algoforge-strategies)** — strategy code, docs, and versioning are managed there.

---

## Documentation

| Doc | Purpose |
|:----|:--------|
| [strategy_dev_guide.md](docs/strategy_dev_guide.md) | Strategy development guide, BaseStrategy reference, MQL4 porting |
| [data_factory.md](docs/data_factory.md) | DataFactory metric reference (26 indicators) |
| [product_manual.md](docs/product_manual.md) | Product manual |
| [mt4_guide.md](docs/mt4_guide.md) | MT4 + EA setup guide |

---

## Contributing

We welcome contributions!

- **Add a strategy** — write it against `strategies/base.py`, drop it in the algoforge-strategies repo
- **Fix a bug** — PRs welcome, run `python -m pytest tests/` first
- **Improve docs** — every strategy ships with a doc

---

## License

MIT © goodie1972

---

<p align="center">
  <sub>Built with ❤️ for XAUUSD gold trading — version 3.3.8</sub>
</p>