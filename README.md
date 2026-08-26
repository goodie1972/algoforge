<p align="center">
  <img src="docs/assets/logo.svg" width="120" height="120" alt="AlgoForge Logo">
</p>

<h1 align="center">AlgoForge</h1>

<p align="center"><strong>XAUUSD Algorithmic Trading System · Algorithmic + Forge</strong> — Multi-strategy parallel, comprehensive risk control, real-time Web monitoring — professional gold trading platform.</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/MetaTrader4-FreeMT4Bridge-orange" alt="MT4">
  <img src="https://img.shields.io/badge/SQLite-003B57?logo=sqlite" alt="SQLite">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/version-3.4.0-gold" alt="Version">
</p>

<p align="center">
  🌐 <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a>
</p>

---

## Features

> Full-chain traceability: from data collection to trade execution, from signal replay to review.

### 🎯 Multi-Strategy Parallel
- **25+ strategies run simultaneously** with independent Magic Numbers and risk states
- Auto-scans the `strategies/` directory for new strategies — **zero-config registration**
- Categories: trend following / reversal / scoring / breakout / scalping
- Stoch threshold **K70** (followave) · ADX **22** (fish_eaten) — backtest-optimized parameters

### 🏗️ Three-Rail Architecture
- **DataFactory** (data + indicators) → **Strategist** (signal scoring) → **Athlete** (tick verification)
- Clear separation of duties, real-time entry re-computation, 10s expiry
- **Engine restart recovery**: positions automatically regain exit state on restart — no orphan trades

### 🛡️ Complete Risk Control
- **Three-layer take-profit** + **ATR trailing stop** + **ATR hard stop**
- **GateManager** (time/volatility/trend/loss gates) · **RiskManager** (per-trade/exposure/position caps) · **TradeManager** (orders/slippage/Magic isolation) — three-layer management
- **Magic fallback**: orphan positions auto-assigned to nearest strategy

### 📊 Data-Driven
- DataFactory computes **26 TA-Lib indicators**, F043 MT4 values preferred
- **Shared** across strategies, zero redundant computation
- M5 / M15 / M30 / H1 / H4 multi-timeframe coverage
- **Lazy multi-timeframe loading**: prioritized by display order, non-blocking startup

### 🗞️ Multi-Source News
- **4 sources**: 汇通 + 金十 (Chinese) + **FXStreet + Kitco** (English)
- Direction judgment: **LLM-first** with keyword fallback, bilingual
- Language-aware display: Chinese sources on CN, English sources on EN
- Source label + original URL link in full-list view

### 📝 Strategy Docs (Bilingual)
- Every strategy has **parallel `_cn.md` / `_en.md`** docs — one-to-one content mapping
- Entry/exit logic tables, parameter reference, backtest results — all bilingual
- Frontend auto-selects by UI language

### 💪 Self-Healing Monitor
- Auto health check every 5 minutes, **auto-restart** on crash / bridge disconnect
- Real-time WebSocket push, full log tracking

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
Data Flow:  MT4 → FreeMT4Bridge EA → core/bridge.py → DataFactory → Strategist → Athlete → Order
```

```
┌─────────────────────────────────────────────────────────┐
│               MT4 + FreeMT4Bridge EA (TCP :23232)       │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                  core/bridge.py                         │
│              bridge abstraction (MT4 ⇄ Python)                     │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              TradingEngine (Three-Rail)                    │
│  ┌──────────────────────────────────────────────────┐   │
│  │ Rail 1: DataFactory (dedicated thread)                      │   │
│  │   → Incremental K-line fetch → 26 TA-Lib indicators computed   │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ Rail 2: Strategist (main loop)                             │   │
│  │   → get_indicator() cache read → scoring emits tickets           │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ Rail 3: Athlete (tick verification)                      │   │
│  │   → _verify_entry real-time recheck → 10s expiry           │   │
│  └──────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              Dashboard (Web)                              │
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

> Backtest-validated strategies currently running (categories: trend / reversal / scoring / breakout / scalping).

| Strategy | Type | Timeframe | Magic | Note |
|:---------|:-----|:---------:|:-----:|:-----|
| `sanqing_h1_upgraded` | Trend | H1 | 880108 | ADX adaptive exits |
| `gold_auto_research` | Scoring | H1 | 880306 | Stoch/RSI/EMA composite |
| `stoch_trend_h1_optimized` | Trend | H1 | 661202 | Stoch + trend gate |
| `goodma` | Trend | H1 | 880401 | 60MA direction + pullback |
| `kiss` | Trend | H1 | 880501 | H4 MACD + H1 MA + pivot |
| `rsi_grading_m30_upgraded` | Scoring | M30 | 660904 | RSI gradient scoring |
| `m30_bb_deepreturn_optimized` | Reversal | M30 | 661102 | BB deep return |
| `fish_eaten` | Reversal | M30 | 661301 | RSI+MFI+BB fish exit, ADX 22 gate |
| `m30_followave` | Trend | M30 | 661402 | Stoch+BBI+BB, K70, 2.0×ATR trailing |
| `m15_followave` | Trend | M15 | 661401 | Stoch+BBI+BB, K70, trend following |
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