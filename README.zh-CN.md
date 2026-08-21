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

## 核心特性

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

## 快速开始 — 60 秒跑起来

### 前置条件

| 依赖 | 用途 |
|:----|:----|
| Python 3.10+ | 引擎与后端 |
| MetaTrader 4 | 已登录 XAUUSD 账户 |
| FreeMT4Bridge EA | 加载到 XAUUSD 图表（M5 周期） |
| Node.js 18+ | 前端构建 |

### 一键启动

```bash
python start.py
```

或直接启动后端 + 引擎：

```bash
python dashboard/backend/main.py
```

### 打开仪表盘

```
http://localhost:1783
```

---

## 架构总览

```
数据流:  MT4 → FreeMT4Bridge EA → core/bridge.py → DataFactory → 策略员 → Athlete → 下单
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

### 三轨架构详解

| 轨道 | 组件 | 职责 |
|:----|:----|:----|
| **轨1** | DataFactory | 独立线程，增量拉取 K 线，TA-Lib 统一计算 26 个指标 |
| **轨2** | 策略员 | 主循环，`get_indicator(key)` 读缓存，评分达标出门票 |
| **轨3** | Athlete | tick 验证，`_verify_entry` 实时重算入场，10 秒过期 |

---

## 界面预览

| 模块 | 亮点 |
|:----|:----|
| **仪表盘** | 引擎状态、账户概览、实时信号 |
| **策略中心** | 策略管理、开关控制、Magic 配置 |
| **持仓管理** | 实时持仓、手动平仓、盈亏统计 |
| **历史成交** | 成交记录、盈亏分析、过滤搜索 |
| **系统日志** | 全链路日志追踪、实时过滤 |

---

## 当前策略组合

> 基于回测筛选，以下策略当前在线运行（分类：趋势 / 反转 / 评分 / 突破 / 剥头皮）。

| 策略 | 类型 | 周期 | Magic | 备注 |
|:-----|:----|:----:|:-----:|:----|
| `sanqing_h1_upgraded` | 趋势 | H1 | 880108 | ADX 自适应出场 |
| `gold_auto_research` | 评分 | H1 | 880306 | Stoch/RSI/EMA 组合 |
| `stoch_trend_h1_optimized` | 趋势 | H1 | 661202 | Stoch + 趋势门禁 |
| `goodma` | 趋势 | H1 | 880401 | 60MA 方向 + 回踩 |
| `kiss` | 趋势 | H1 | 880501 | H4 MACD + H1 均线 + 枢轴 |
| `rsi_grading_m30_upgraded` | 评分 | M30 | 660904 | RSI 梯度评分 |
| `m30_bb_deepreturn_optimized` | 反转 | M30 | 661102 | BB 深度回归 |
| `fish_eaten` | 反转 | M30 | 661301 | RSI+MFI+BB 吃鱼出场 |
| `m30_followave` | 趋势 | M30 | 661402 | Stoch+BBI+BB + 移动止盈 |
| `m15_followave` | 趋势 | M15 | 661401 | Stoch+BBI+BB 趋势跟踪 |
| `timeprofit_ea` | 剥头皮 | M5 | 880202 | 时间利润 EA |

> 策略源码与文档托管在独立的 **algoforge-strategies** 仓库。

---

## 技术栈

| 层级 | 技术 | 用途 |
|:----|:-----|:----|
| 桥接 | FreeMT4Bridge EA (MQL4) | TCP Socket 通信 |
| 引擎 | Python 3.10+ | 策略执行、风控、订单管理 |
| 后端 | FastAPI + WebSocket | REST API、实时数据推送 |
| 前端 | Vue 3 + TypeScript + Vite | 监控仪表盘 |
| UI | Naive UI | 组件库 |
| 图表 | lightweight-charts | K 线展示 |
| 数据库 | SQLite | 行情、交易、信号存储 |

---

## 仓库结构

```
AlgoForge/
├── config/                  # 配置
├── core/                    # 桥接 / 风控 / 订单 / 门禁管理器
├── engine_standalone/       # 交易引擎（三轨循环）
├── strategies/              # 框架（base/scanner）— 策略实现在 algoforge-strategies
├── dashboard/
│   ├── backend/             # FastAPI + 路由
│   └── frontend/            # Vue 3 + Naive UI
├── services/                # 数据工厂 / 新闻 / LLM / 监管
├── backtest/                # 回测脚本与结果
├── data/                    # SQLite 数据库
├── logs/                    # 运行日志
└── docs/                    # 文档
```

> **策略托管在 [algoforge-strategies](https://github.com/goodie1972/algoforge-strategies)** —— 策略代码、文档与版本管理只在该仓库维护。

---

## 文档

| 文档 | 说明 |
|:----|:----|
| [strategy_dev_guide.md](docs/strategy_dev_guide.md) | 策略开发全流程 + BaseStrategy 参考 + MQL4 移植指南 |
| [data_factory.md](docs/data_factory.md) | DataFactory 指标参考（26 个指标） |
| [product_manual.md](docs/product_manual.md) | 产品手册 |
| [mt4_guide.md](docs/mt4_guide.md) | MT4 + EA 配置指南 |

---

## 参与贡献

欢迎贡献！

- **新增策略** —— 基于 `strategies/base.py` 编写，提交到 algoforge-strategies 仓库
- **修复 Bug** —— 欢迎 PR，请先运行 `python -m pytest tests/`
- **完善文档** —— 每个策略都应附带说明文档

---

## License

MIT © goodie1972

---

<p align="center">
  <sub>Built with ❤️ for XAUUSD gold trading — version 3.3.8</sub>
</p>