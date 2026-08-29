# AGENTS.md — AlgoForge XAUUSD 量化交易系统

## 项目概述

AlgoForge 是一个基于 Python + MetaTrader 4 的 XAUUSD 黄金自动化交易系统。采用三轨架构（DataFactory → 策略员 → 运动员），支持 25+ 策略并行运行，具备完整风控链路和实时 Web 监控面板。

- **技术栈:** Python 3.10+ / FastAPI / Vue 3 + TypeScript + Vite + Naive UI / SQLite / lightweight-charts
- **桥接:** FreeMT4Bridge EA (MQL4, TCP Socket :23232) 或 MetaApi 云端
- **版本:** 见 `VERSION` 文件
- **策略仓库:** [algoforge-strategies](https://github.com/goodie1972/algoforge-strategies.git)

---

## 模块职责

### `core/` — 桥接与基础设施层

MT4 通信抽象和系统级基础组件。

| 文件 | 职责 |
|:-----|:-----|
| `bridge.py` | 桥接抽象基类 (`MT4BridgeBase`)，定义 MT4 ⇄ Python 统一接口 |
| `freemt4_bridge.py` | FreeMT4Bridge EA 实现（TCP Socket :23232），K线/指标/交易指令 |
| `metaapi_bridge.py` | MetaApi 云端桥接实现 |
| `paper_bridge.py` | 纸面交易桥接（模拟环境，无真实下单） |
| `bias_state.py` | 市场偏置状态管理 |
| `runtime_config.py` | 运行时配置热加载 |
| `time_utils.py` | 时区工具（UTC+8 本地时间转换） |
| `version.py` | 版本信息读取与远程更新检查 |

### `dashboard/` — Web 监控面板

前后端一体的 Web 管理界面，端口 1783。

**`dashboard/backend/`** — FastAPI 后端

| 文件 | 职责 |
|:-----|:-----|
| `main.py` | FastAPI 主入口，生命周期管理、路由注册、WebSocket、后台轮询任务 |
| `engine_runner.py` | 引擎线程管理器，在后台线程启动/停止 TradingEngine |
| `config_service.py` | 策略池配置持久化与读写 |
| `web_manager.py` | WebSocket 连接管理（旧版兼容通道） |
| `broadcast_hub.py` | WebSocket 广播中枢（背压控制） |
| `log_service.py` | 日志捕获与实时推送 |
| `auto_update.py` | 自动更新：远程版本检查、预下载、冷更新应用 |
| `paper_engine_manager.py` | 纸面引擎子进程生命周期管理 |
| `ai_service.py` | AI 聊天服务（LLM 对话 + 工具调用） |
| `trade_analysis_ai.py` | 交易分析 AI 服务 |
| `strategy_logics.py` | 策略逻辑管理服务 |
| `strategy_registry.py` | 策略注册表 |
| `routes/` | REST API 路由（engine, account, positions, config, market, trades, news, signals, reports 等） |

**`dashboard/frontend/`** — Vue 3 前端

- Vue 3 + TypeScript + Vite + Naive UI + lightweight-charts
- 实时展示引擎状态、持仓、K线、信号、日志

### `engine_standalone/` — 交易引擎核心

三轨架构的核心执行循环，独立于 Web 层运行。

| 文件 | 职责 |
|:-----|:-----|
| `main.py` | TradingEngine 主类，三轨循环编排（DataFactory → 策略员 → 运动员） |
| `core_loop.py` | 引擎核心循环，策略扫描/评分/门票分发 |
| `athlete.py` | 运动员（轨3），tick 验证层，最多 3 tick 验证后开仓或作废 |
| `position_mgr.py` | 持仓管理，出场状态机、止盈止损跟踪 |
| `risk_mgr.py` | 风控管理（GateManager + RiskManager + TradeManager 三层） |
| `events.py` | 引擎事件定义与分发 |
| `run.py` | 引擎独立启动脚本（含环境检查、连通性验证） |
| `paper_main.py` | 纸面引擎入口（模拟交易，无真实下单） |

### `services/` — 服务层

数据、新闻、AI Agent 等共享服务。

| 文件 | 职责 |
|:-----|:-----|
| `data_factory.py` | DataFactory（轨1），独立线程增量拉取 K 线，TA-Lib 计算 26+ 指标，所有策略的唯一指标源 |
| `news_filter.py` | 新闻过滤器，多源新闻聚合与方向判断 |
| `huicong_news.py` | 汇通/金十中文新闻源适配器 |
| `llm_provider.py` | LLM 提供商管理（多模型切换） |
| `supervisor.py` | 引擎监督者，5 分钟健康检查 + 自动重启 |
| `mtf_coordinator.py` | 多时间框架协调器 |
| `log_messages.py` | 日志消息常量定义 |
| `agent/` | AI Agent 子系统（MCP 运行时、工具注册、Agent 设置持久化） |

---

## 启动入口与验证命令

### 启动

```bash
# 一键启动（端口清理 → 后端 API → 引擎线程 → MT4 连接）
python start.py

# 仅启动后端（引擎在 lifespan 中自动启动）
python dashboard/backend/main.py

# 引擎独立启动（含环境检查）
python engine_standalone/run.py

# 前端开发模式（独立启动）
cd dashboard/frontend && npm run dev
```

### 验证

```bash
# 环境检查（Python 版本、依赖、配置）
python tools/check_setup.py

# 测试套件
python -m pytest tests/

# 引擎状态 API（启动后）
curl http://localhost:1783/api/engine/status

# 前端构建
cd dashboard/frontend && npm run build
```

### 服务端口

| 服务 | 地址 |
|:-----|:-----|
| REST API | `http://localhost:1783/api` |
| Dashboard | `http://localhost:1783` |
| WebSocket | `ws://localhost:1783/ws` |
| MT4 Bridge | TCP :23232 |

---

## 范围边界

### 本仓库包含

- 交易引擎核心（三轨架构、风控、持仓管理）
- Web 监控面板（前后端）
- 数据服务（DataFactory、新闻过滤、LLM）
- AI Agent 子系统（MCP、工具注册）
- 桥接层（FreeMT4 / MetaApi / Paper）
- 回测脚本（`backtest/`）
- 工具集（`tools/`：监控、纸面交易、信号分析）
- 配置与文档（`config/`、`docs/`）

### 本仓库不包含

- **策略源码** → 独立仓库 [algoforge-strategies](https://github.com/goodie1972/algoforge-strategies)（`strategies/` 目录仅含框架基类和扫描器）
- **MT4 EA 源码** → FreeMT4Bridge EA（MQL4，加载在 MT4 图表上）
- **生产数据库** → `data/market_data.db` 为运行时生成，不入版本控制

---

## 其他模块简述

| 模块 | 职责 |
|:-----|:-----|
| `config/` | 系统配置（`settings.py` 全局常量、`runtime_config.py` 热配置、`config_schema.py` 配置校验） |
| `strategies/` | 策略框架（`base.py` 基类、`scanner.py` 自动扫描），策略源码在外部仓库 |
| `data/` | 数据库层（`database.py` ORM、`market_data.db` SQLite） |
| `indicators/` | 自定义指标计算辅助模块 |
| `backtest/` | 回测脚本与结果存储 |
| `tools/` | 独立工具（状态监控、纸面交易、信号分析、环境检查） |
| `models/` | 数据模型定义 |
| `monitor/` | 外部监控脚本 |
| `scripts/` | 运维脚本 |
| `tests/` | 测试套件 |
| `docs/` | 项目文档（产品手册、策略开发指南、DataFactory 参考） |
