<p align="center">
  <img src="docs/assets/logo.svg" width="120" height="120" alt="AlgoForge Logo">
</p>

<h1 align="center">AlgoForge</h1>

<p align="center"><strong>Production-grade algorithmic trading system for XAUUSD (Gold) — multi-strategy, 3-layer risk, real-time monitoring.</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/Vue-3-4FC08D?logo=vue.js" alt="Vue 3">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/MT4-FreeMT4Bridge-orange" alt="MT4">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/version-3.3.8-gold" alt="Version">
</p>

<p align="center">
  🌐 <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a>
</p>

---

## Why This Exists

Running a gold trading strategy shouldn't mean babysitting 10 separate scripts, manually tracking positions across sessions, or discovering at 3 AM that the bridge silently died.

AlgoForge is a **self-contained, always-on trading workstation** for XAUUSD — it watches the market 24/7, runs 10+ strategies simultaneously, enforces hard risk limits, and surfaces everything through a live web dashboard. Built on Python + MetaTrader 4, it was designed to be **fire-and-forget**: it restarts itself, protects your capital, and tells you what happened.

**What makes it different:**

- ✅ **Multi-strategy parallel** — 25+ strategies, auto-discovered from the `strategies/` directory, zero-config registration
- ✅ **3-layer risk system** — profit drawdown take-profit → ATR trailing stop → ATR hard stop, plus Gate/Risk/Trade managers
- ✅ **Self-healing** — monitors engine health every 5 minutes, auto-restarts on crash or bridge disconnect
- ✅ **Bilingual dashboard** — Chinese/English UI, LLM-driven news sentiment, live K-line charts
- ✅ **Paper trading** — validate strategies with simulated fills before risking real capital

---

## Quick Start — Running in 60 Seconds

### Prerequisites

| Dependency | Purpose |
|:-----------|:--------|
| Python 3.10+ | Engine & backend |
| MetaTrader 4 | Logged into a XAUUSD account |
| FreeMT4Bridge EA | Loaded on an XAUUSD chart (M5 timeframe) |
| Node.js 18+ | Frontend build |

### One-command start

```bash
python start.py
```

Or start the backend + engine directly:

```bash
python dashboard/backend/main.py
```

### Open the dashboard

```
http://localhost:1783
```

That's it — the engine boots, connects to MT4, loads all active strategies, and the dashboard comes alive.

---

## Strategy Directory

### Active Strategies

| Strategy | Type | Timeframe | Magic | Note |
|:---------|:-----|:---------:|:-----:|:-----|
| `sanqing_h1_upgraded` | Trend | H1 | 880108 | ADX adaptive exits |
| `gold_auto_research` | Scoring | H1 | 880306 | Stoch/RSI/EMA composite |
| `stoch_trend_h1_optimized` | Trend | H1 | 661202 | Stoch + trend gate |
| `goodma` | Trend | H1 | 880401 | 60MA direction + pullback |
| `kiss` | Trend | H1 | 880501 | H4 MACD + H1 MA + pivot |
| `rsi_grading_m30_upgraded` | Scoring | M30 | 660904 | RSI gradient scoring |
| `m30_bb_deepreturn_optimized` | Reversal | M30 | 661102 | BB deep return |
| `fish_eaten` | Reversal | M30 | 661301 | RSI+MFI+BB fish exit, backtest +3.46% |
| `m30_followave` | Trend | M30 | 661402 | Stoch+BBI+BB + 2.0×ATR trailing, backtest +6.58% |
| `m15_followave` | Trend | M15 | 661401 | Stoch+BBI+BB trend following, backtest +4.03% |
| `timeprofit_ea` | Scalping | M5 | 880202 | Time-based profit EA |

> Full strategy source & docs live in the separate **algoforge-strategies** repository.

### Strategy Framework

- **Three-rail architecture** — DataFactory (indicators) → Strategist (signals) → Athlete (tick verification)
- **26 shared indicators** from one DataFactory cache (RSI, MFI, BB, ATR, ADX, MACD, Stoch…)
- **Chaos-proof exits** — fish-exit logic waits for both indicators to reach extremes before reversing

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│               MT4 + FreeMT4Bridge EA (TCP :23232)       │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                  core/bridge.py                         │
│              abstraction layer (MT4 ⇄ Python)           │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              TradingEngine (Three-Rail)                 │
│  ┌──────────────────────────────────────────────────┐   │
│  │ Rail 1: DataFactory (thread)                     │   │
│  │   → incremental K-line fetch → 26 TA-Lib        │   │
│  │     indicators in one shared cache               │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ Rail 2: Strategist (main loop)                   │   │
│  │   → get_indicator() → score → candidate ticket  │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ Rail 3: Athlete (tick verify)                    │   │
│  │   → re-check entry → 10s expiry                  │   │
│  └──────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              Dashboard (Web)                            │
│  ┌──────────────┐  ┌────────────────────────────────┐   │
│  │ FastAPI       │  │ Vue 3 + Naive UI              │   │
│  │ :1783 + WS    │  │ lightweight-charts            │   │
│  └──────────────┘  └────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Three-Rail Detail

| Rail | Component | Responsibility |
|:-----|:----------|:---------------|
| **1** | DataFactory | Dedicated thread, dual bridge (exec+data), incremental K-line fetch, 26 TA-Lib indicators |
| **2** | Strategist | Main engine loop, `get_indicator(key)` cache reads, scoring emits tickets |
| **3** | Athlete | Tick verification, `_verify_entry` real-time recheck, 10-second expiry |

---

## Features

### Multi-Strategy Parallel
- 25+ strategies running simultaneously, independent magic numbers & risk states
- Auto-scan `strategies/` directory — new strategies register with zero config
- Categories: trend-following / mean-reversion / breakout / scoring / combo

### Complete Risk System
- **Three-layer exit**: profit drawdown take-profit → ATR trailing stop → ATR hard stop
- **GateManager**: time gate, volatility gate, trend gate, losing-streak gate
- **RiskManager**: per-trade risk, total exposure cap, max position count
- **TradeManager**: order management, slippage handling, magic-number isolation

### News-Driven Sentiment
- HuiCheng (汇通网) 7×24 gold news + Jin10 dual-source fetching
- LLM-powered direction judgment (bullish/bearish/neutral), zh/en auto-translate
- Economic calendar marquee, click to expand
- Auto-refresh every 4 hours, historical accuracy review

### Data-First
- **DataFactory**: single source of truth, F043 MT4 values preferred, TA-Lib local fallback
- 26 shared indicators across strategies
- M5/M15/M30/H1/H4 multi-timeframe coverage

### Paper Trading
- Full signal simulation with realistic fills
- Strategy-rule-based position closing
- Real-price PnL calculation

### Monitoring & Self-Healing
- Engine health check every 5 minutes
- Auto-restart on crash / bridge disconnect
- Real-time web dashboard + logs

---

## Backtest Highlights

100% backtest on $10k, fixed 0.01 lot:

| Strategy | Net PnL | Win Rate | Profit Factor |
|:---------|:-------:|:--------:|:-------------:|
| m30_followave | +$658 | 37% | 2.20 |
| m15_followave | +$403 | 36% | 2.09 |
| fish_eaten (M30) | +$346 | 62% | — |
| rsi_grading_m30_upgraded | +$118 | 54.5% | 1.55 |

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
├── strategies/              # → separate repo: algoforge-strategies
├── dashboard/
│   ├── backend/             # FastAPI + routes
│   └── frontend/            # Vue 3 + Naive UI
├── services/                # data_factory / news / llm / supervisor
├── backtest/                # backtest scripts & results
├── data/                    # SQLite database
├── logs/                    # runtime logs
└── docs/                    # documentation
```

> **Strategies live in [algoforge-strategies](https://github.com/goodie1972/algoforge-strategies)** — strategy code, docs, and versioning are managed in that repository only.

---

## Documentation

| Doc | Purpose |
|:----|:--------|
| [CLAUDE.md](CLAUDE.md) | AI dev assistant config |
| [strategy_dev_guide.md](docs/strategy_dev_guide.md) | Strategy development guide, BaseStrategy reference, MQL4 porting |
| [product_manual.md](docs/product_manual.md) | Product manual |
| [data_factory.md](docs/data_factory.md) | DataFactory metric reference (26 indicators) |

---

## Contributing

We welcome contributions!

- **Add a strategy** — write it against `strategies/base.py`, drop it in `strategies/`, it's auto-discovered
- **Fix a bug** — PRs welcome, please run `python -m pytest tests/` first
- **Improve docs** — every strategy should ship with a doc in `docs/strategies/`

### Strategy inclusion criteria

A strategy belongs in the active pool if:
1. It passes **backtest with positive PnL** over 3+ months of history
2. It has a **complete doc** (entry/exit logic, risk, backtest results)
3. It survives **paper trading** without violating risk limits

---

## Links

- 📈 **Strategies repo**: [algoforge-strategies](https://github.com/goodie1972/algoforge-strategies)
- 🖥️ **Dashboard**: `http://localhost:1783`
- 📊 **Backtest**: `python -m backtest.<script>`
- 📋 **Status monitor**: `python tools/status_monitor.py`

---

## License

MIT © goodie1972

---

<p align="center">
  <sub>Built with ❤️ for XAUUSD gold trading — version 3.3.8</sub>
</p>