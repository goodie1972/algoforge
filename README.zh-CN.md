<p align="center">
  <img src="docs/assets/logo.svg" width="120" height="120" alt="AlgoForge Logo">
</p>

<h1 align="center">AlgoForge</h1>

<p align="center"><strong>面向 XAUUSD（黄金）的生产级量化交易系统 —— 多策略并行 · 三层风控 · 实时监控。</strong></p>

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

## 为什么需要本项目

跑黄金策略不应该意味着盯着 10 个脚本、跨会话手动跟踪持仓，或者在凌晨 3 点发现桥接静默断开。

AlgoForge 是一台**自包含、永不掉线的 XAUUSD 交易工作站** —— 7×24 盯市，同时运行 10+ 个策略，强制风控上限，并通过实时 Web 仪表盘呈现一切。基于 Python + MetaTrader 4 构建，设计目标是**点火即忘**：自动重启、守护资金、事后汇报。

**核心差异：**

- ✅ **多策略并行** —— 25+ 策略，自动扫描 `strategies/` 目录，零配置注册
- ✅ **三层风控** —— 利润回撤止盈 → ATR 移动止盈 → ATR 硬止损，外加 Gate/Risk/Trade 管理器
- ✅ **自愈能力** —— 每 5 分钟检查引擎健康，崩溃/桥接断连自动重启
- ✅ **双语仪表盘** —— 中英双语 UI、LLM 新闻情绪研判、实时 K 线图
- ✅ **纸面测试** —— 先用模拟成交验证策略，再上真金白银

---

## 快速开始 —— 60 秒跑起来

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

完成 —— 引擎启动、连接 MT4、加载全部在线策略，仪表盘即刻可用。

---

## 策略目录

### 在线策略

| 策略 | 类型 | 周期 | Magic | 备注 |
|:-----|:----|:----:|:-----:|:----|
| `sanqing_h1_upgraded` | 趋势 | H1 | 880108 | ADX 自适应出场 |
| `gold_auto_research` | 评分 | H1 | 880306 | Stoch/RSI/EMA 组合 |
| `stoch_trend_h1_optimized` | 趋势 | H1 | 661202 | Stoch + 趋势门禁 |
| `goodma` | 趋势 | H1 | 880401 | 60MA 方向 + 回踩 |
| `kiss` | 趋势 | H1 | 880501 | H4 MACD + H1 均线 + 枢轴 |
| `rsi_grading_m30_upgraded` | 评分 | M30 | 660904 | RSI 梯度评分 |
| `m30_bb_deepreturn_optimized` | 反转 | M30 | 661102 | BB 深度回归 |
| `fish_eaten` | 反转 | M30 | 661301 | RSI+MFI+BB 吃鱼出场，回测 +3.46% |
| `m30_followave` | 趋势 | M30 | 661402 | Stoch+BBI+BB + 2.0×ATR 移动止盈，回测 +6.58% |
| `m15_followave` | 趋势 | M15 | 661401 | Stoch+BBI+BB 趋势跟踪，回测 +4.03% |
| `timeprofit_ea` | 剥头皮 | M5 | 880202 | 时间利润 EA |

> 策略源码与文档托管在独立的 **algoforge-strategies** 仓库。

### 策略框架

- **三轨架构** —— DataFactory（指标）→ 策略员（信号）→ Athlete（tick 验证）
- **26 个共享指标** 来自单一 DataFactory 缓存（RSI、MFI、BB、ATR、ADX、MACD、Stoch…）
- **抗震荡出场** —— 吃鱼出场逻辑等待两个指标都进入极限区后才反转

---

## 架构总览

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
│  │   → 增量拉取K线 → TA-Lib 统一计算 26 指标          │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ 轨2: 策略员（主循环）                             │   │
│  │   → get_indicator() 读缓存 → 评分出门票           │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ 轨3: Athlete（tick 验证层）                      │   │
│  │   → 实时重算入场 → 10 秒过期                      │   │
│  └──────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              Dashboard（Web 监控）                       │
│  ┌──────────────┐  ┌────────────────────────────────┐   │
│  │ FastAPI       │  │ Vue 3 + Naive UI              │   │
│  │ :1783 + WS    │  │ lightweight-charts            │   │
│  └──────────────┘  └────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 三轨架构详解

| 轨道 | 组件 | 职责 |
|:----|:----|:----|
| **轨1** | DataFactory | 独立线程，双桥接(exec+data)，增量拉取 K 线，TA-Lib 统一计算 26 个指标 |
| **轨2** | 策略员 | 主引擎循环，`get_indicator(key)` 读缓存，评分达标出门票（候选信号） |
| **轨3** | Athlete | tick 验证层，`_verify_entry` 实时重算入场条件，10 秒过期作废 |

---

## 核心特性

### 多策略并行
- 25+ 策略同时运行，独立 Magic Number 和风控状态
- 自动扫描 `strategies/` 目录发现新策略，零配置注册
- 策略分类：趋势跟踪 / 反转交易 / 突破交易 / 评分模型 / 组合策略

### 完整风控体系
- **三层退出**：利润回撤止盈 → ATR 移动止盈 → ATR 硬止损
- **GateManager**：时间门、波动门、趋势门、连续亏损门
- **RiskManager**：单笔风险固定、总敞口限制、最大持仓数
- **TradeManager**：订单管理、滑点处理、Magic Number 隔离

### 多源新闻预判
- 汇通网 7×24 黄金快讯 + 金十数据双源抓取
- LLM 驱动方向判断（利多/利空/中性），自动翻译中英文
- 经济日历跑马灯滚动展示，点击放大查看完整列表
- 4 小时自动刷新，历史准确性复盘评估

### 数据驱动
- **DataFactory**：唯一指标来源，F043 MT4 值优先，TA-Lib 本地回退
- 26 个通用指标跨策略共享（RSI, MFI, BB, ATR, ADX, MACD, Stoch 等）
- M5/M15/M30/H1/H4 多周期覆盖

### 纸面测试系统
- 信号全量模拟入场 + 出场
- 按策略规则模拟平仓
- 真实成交价计算盈亏

### 监控与自修复
- 5 分钟自动检查引擎状态
- 崩溃 / 桥接断连自动重启
- 实时 Web 仪表盘 + 日志

---

## 回测亮点

$10,000 本金、固定 0.01 手回测：

| 策略 | 净盈亏 | 胜率 | 盈亏比 |
|:-----|:----:|:----:|:----:|
| m30_followave | +$658 | 37% | 2.20 |
| m15_followave | +$403 | 36% | 2.09 |
| fish_eaten（M30） | +$346 | 62% | — |
| rsi_grading_m30_upgraded | +$118 | 54.5% | 1.55 |

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
├── strategies/              # → 独立仓库：algoforge-strategies
├── dashboard/
│   ├── backend/             # FastAPI + 路由
│   └── frontend/            # Vue 3 + Naive UI
├── services/                # 数据工厂 / 新闻 / LLM / 监管
├── backtest/                # 回测脚本与结果
├── data/                    # SQLite 数据库
├── logs/                    # 运行日志
└── docs/                    # 文档
```

> **策略托管在 [algoforge-strategies](https://github.com/goodie1972/algoforge-strategies)** —— 策略代码、说明文档与版本管理只在该仓库维护。

---

## 文档

| 文档 | 说明 |
|:----|:----|
| [CLAUDE.md](CLAUDE.md) | AI 开发助手配置 |
| [strategy_dev_guide.md](docs/strategy_dev_guide.md) | 策略开发全流程 + BaseStrategy 参考 + MQL4 移植指南 |
| [product_manual.md](docs/product_manual.md) | 产品手册 |
| [data_factory.md](docs/data_factory.md) | DataFactory 指标参考（26 个指标） |

---

## 参与贡献

欢迎贡献！

- **新增策略** —— 基于 `strategies/base.py` 编写，放入 `strategies/` 目录即可自动发现
- **修复 Bug** —— 欢迎 PR，请先运行 `python -m pytest tests/`
- **完善文档** —— 每个策略都应附带 `docs/strategies/` 下的说明文档

### 策略入选标准

策略进入在线池需满足：
1. **3 个月以上回测 PnL 为正**
2. **文档完整**（入场/出场逻辑、风控、回测结果）
3. **纸面测试通过**且不违反风控上限

---

## 链接

- 📈 **策略仓库**：[algoforge-strategies](https://github.com/goodie1972/algoforge-strategies)
- 🖥️ **仪表盘**：`http://localhost:1783`
- 📊 **回测**：`python -m backtest.<script>`
- 📋 **状态监控**：`python tools/status_monitor.py`

---

## License

MIT © goodie1972

---

<p align="center">
  <sub>Built with ❤️ for XAUUSD gold trading — version 3.3.8</sub>
</p>