<p align="center">
  <img src="docs/assets/logo.svg" width="120" height="120" alt="AlgoForge Logo">
</p>

<h1 align="center">AlgoForge</h1>
<p align="center"><strong>XAUUSD 黄金量化交易系统</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/Vue-3-4FC08D?logo=vue.js" alt="Vue 3">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/version-2.3.0-gold" alt="Version">
</p>

---

## 📋 项目简介

**AlgoForge**（Algorithmic + Forge = 算法锻造工坊）是一个面向 XAUUSD（黄金）的自动化量化交易系统。基于 Python + MetaTrader 4 构建，支持多策略并行、三层风控、实时 Web 监控、纸面测试及全链路信号追踪。

> 🎯 目标：通过算法组合管理，实现年化 50%+ 的稳定收益，最大回撤控制在 15% 以内。

---

## 🏗️ 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    MT4 + FreeMT4Bridge EA                │
│                    (TCP Socket :23232)                   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                  core/bridge.py                          │
│              桥接抽象层 (MT4 ⇄ Python)                   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              TradingEngine (三轨架构)                    │
│  ┌──────────────────────────────────────────────────┐   │
│  │ 轨1: DataFactory (独立线程)                      │   │
│  │      → 增量拉取 K 线  →  TA-Lib 统一计算 26 指标   │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ 轨2: 策略员 (主循环)                              │   │
│  │      → get_indicator() 读缓存  →  评分出门票      │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ 轨3: Athlete (tick 验证层)                       │   │
│  │      → _verify_entry 实时重算  →  10秒过期       │   │
│  └──────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              Dashboard (Web 监控)                        │
│  ┌──────────────┐  ┌────────────────────────────────┐   │
│  │ FastAPI 后端  │  │  Vue 3 + Naive UI 前端         │   │
│  │ :1783        │  │  lightweight-charts 图表       │   │
│  └──────────────┘  └────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 三轨架构详解

| 轨道 | 组件 | 职责 |
|:----|:----|:------|
| **轨1** | DataFactory | 独立线程，双桥接(exec+data)，增量拉取 K 线，TA-Lib 统一计算 26 个指标 |
| **轨2** | 策略员 | 主引擎循环，`get_indicator(key)` 读缓存，评分达标出门票（候选信号） |
| **轨3** | Athlete | tick 验证层，`_verify_entry` 实时重算入场条件，10 秒过期作废 |

---

## 🚀 核心特性

### 多策略并行
- 25+ 个策略同时运行，独立 Magic Number 和风控状态
- 自动扫描 `strategies/` 目录发现新策略，零配置注册
- 策略分类：趋势跟踪 / 反转交易 / 突破交易 / 评分模型 / 组合策略

### 完整风控体系
- **三层退出**：利润回撤止盈 → ATR 移动止盈 → ATR 硬止损
- **GateManager**：时间门、波动门、趋势门、连续亏损门
- **RiskManager**：单笔风险固定、总敞口限制、最大持仓数
- **TradeManager**：订单管理、滑点处理、Magic Number 隔离

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

## 📊 当前策略组合

| 策略 | 类型 | 周期 | Magic | 状态 |
|:-----|:----|:----:|:-----:|:----:|
| mfi_bb_m30_optimized | 反转 | M30 | 661002 | ✅ 运行中 |
| rsi_grading_m30_upgraded | 评分 | M30 | 660903 | ✅ 运行中 |
| m30_bb_deepreturn | 反转 | M30 | 661100 | ✅ 运行中 |
| mfi_bb_m30 | 反转 | M30 | 661000 | ✅ 运行中 |
| m30_bb_deepreturn_optimized | 反转 | M30 | 661102 | ✅ 运行中 |
| momentum_pulse_pro | 趋势 | M30 | 880101 | ✅ 运行中 |
| rsi_grading_m30 | 评分 | M30 | 660900 | ✅ 运行中 |

> 基于 3 个月回测，以上 7 个策略 PnL 为正。其余策略因回测亏损已禁用。

---

## ⚡ 快速开始

### 前置条件

| 依赖 | 说明 |
|:----|:------|
| Python 3.10+ | 运行引擎和后端 |
| MetaTrader 4 | 已安装并登录 XAUUSD 账户 |
| FreeMT4Bridge EA | 加载到 XAUUSD 图表（M5 周期） |
| Node.js 18+ | 前端构建 |

### 一键启动

```bash
# 启动引擎 + 后端
python start.py

# 或分别启动
python dashboard/backend/main.py   # 后端 + 引擎
```

### 访问监控

```
http://localhost:1783
```

---

## 🔧 技术栈

| 层级 | 技术 | 用途 |
|:----|:-----|:-----|
| 桥接 | FreeMT4Bridge EA (MQL4) | TCP Socket 通信 |
| 引擎 | Python 3.10+ | 策略执行、风控、订单管理 |
| 后端 | FastAPI + WebSocket | REST API、实时数据推送 |
| 前端 | Vue 3 + TypeScript + Vite | 监控仪表盘 |
| UI | Naive UI | 组件库 |
| 图表 | lightweight-charts | K 线展示 |
| 数据库 | SQLite | 行情、交易、信号存储 |

---

## 📁 项目结构

```
AlgoForge/
├── config/                  # 配置
│   └── settings.py          # 全局配置
├── core/                    # 核心
│   ├── bridge.py            # MT4 桥接
│   ├── risk_manager.py      # 风险管理
│   ├── trade_manager.py     # 订单管理
│   └── gate_manager.py      # 时间/波动/趋势门
├── engine_standalone/       # 引擎
│   ├── main.py              # 主入口
│   ├── run.py               # 启动脚本
│   └── athlete.py           # tick 验证
├── strategies/              # 策略库 (25+)
│   ├── base.py              # 基类
│   ├── scanner.py           # 自动扫描器
│   └── *.py                 # 策略实现
├── dashboard/               # Web 仪表盘
│   ├── backend/             # FastAPI 后端
│   └── frontend/            # Vue 3 前端
├── services/                # 服务
│   └── data_factory.py      # 数据工厂
├── scripts/                 # 工具脚本
│   ├── backtest_6months.py  # 回测引擎
│   └── status_monitor.py    # 状态监控
├── data/                    # 数据
├── logs/                    # 日志
└── docs/                    # 文档
```

---

## 📈 回测表现

3 个月回测（$10,000 本金，0.01 手固定）：

| 策略 | 总盈亏 | 胜率 | 盈亏比 | 最大回撤 | 评分 |
|:-----|:-----:|:----:|:------:|:-------:|:----:|
| m30_bb_deepreturn | +$213.95 | 54.6% | 1.32 | 1.39% | 75 |
| mfi_bb_m30 | +$198.33 | 54.2% | 1.30 | 1.39% | 70 |
| rsi_grading_m30_upgraded | +$117.79 | 54.5% | 1.55 | 1.57% | 70 |
| m30_bb_deepreturn_optimized | +$92.80 | 51.0% | 1.09 | 1.50% | 60 |
| rsi_grading_m30 | +$72.37 | 46.4% | 1.46 | 0.82% | 60 |
| mfi_bb_m30_optimized | +$66.60 | 57.6% | 1.38 | 0.51% | 70 |
| momentum_pulse_pro | +$63.83 | 53.9% | 1.09 | 1.64% | 55 |

---

## 📚 文档

| 文档 | 说明 |
|:----|:------|
| [CLAUDE.md](CLAUDE.md) | AI 开发助手配置 |
| [策略文档](/docs/strategies/) | 各策略详细逻辑 |
| [回测分析](/docs/strategy_analysis.md) | 策略分类 + 回测分析 |
| [评测方案](/docs/evaluation_plan.md) | 7 天纸面评测方案 |
| [三级体系](/docs/tiered_strategy_plan.md) | 组合改造方案 |
| [策略文档规范](/docs/strategy_doc_standard.md) | 文档编写标准 |

---

## 📄 License

MIT © goodie1972

---

<p align="center">
  <sub>Built with ❤️ for XAUUSD gold trading</sub>
</p>