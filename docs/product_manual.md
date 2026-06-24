# XAUUSD 量化交易系统 — 产品手册

## 目录

1. [系统概述](#1-系统概述)
2. [系统架构](#2-系统架构)
3. [快速开始](#3-快速开始)
4. [配置指南](#4-配置指南)
5. [交易引擎](#5-交易引擎)
6. [策略框架](#6-策略框架)
7. [风控体系](#7-风控体系)
8. [多策略协调器](#8-多策略协调器)
9. [信号生命周期](#9-信号生命周期)
10. [新闻过滤与预判](#10-新闻过滤与预判)
11. [策略版本管理](#11-策略版本管理)
12. [Web 仪表盘](#12-web-仪表盘)
13. [版本更新机制](#13-版本更新机制)
14. [监控守护进程](#14-监控守护进程)
15. [数据管理](#15-数据管理)
16. [回测系统](#16-回测系统)
17. [故障排除](#17-故障排除)

---

## 1. 系统概述

XAUUSD 量化交易系统是一个专为黄金（XAUUSD）设计的自动化交易平台，通过 Python 控制 MetaTrader 4 终端执行交易。系统采用多策略并行架构，支持动态策略管理、策略池热同步、多层风控、实时 Web 监控、版本更新检查和独立巡检守护。

### 核心特性

- **多策略并行** — 同时运行 6 个独立策略（3 个 H1 + 3 个 M30），各有独立 Magic Number 和风控状态
- **策略池热同步** — 在 Dashboard 策略中心调整策略池后，引擎自动识别增删变更，无需重启
- **信号全生命周期管理** — 从信号生成、开仓、废票到平仓的全链路追踪
- **持仓位门控** — 60 根 K 线价格区间上下 10% 范围内限制逆势开仓
- **三层退出体系** — 利润回撤止盈 + ATR 移动止盈 + ATR 硬止损，趋势感知乘数
- **多策略协调器** — 跨策略联动出场 + M15 斜率归一化反向止盈
- **十层风控** — 从全局到单策略全覆盖，含独立安全锁机制
- **新闻保护** — 集成 ForexFactory 财经日历 + AI 预判偏多/偏空方向
- **实时仪表盘** — Web 端实时查看价格、K 线、持仓、信号、账户、日志
- **版本更新检查** — 自动检查 GitHub 远程新版本，红点提示 + 一键 git pull
- **独立巡检** — 独立进程 30 秒轮询，异常自动告警
- **策略版本管理** — Magic Number 标准化编号，Changelog 持久化到数据库
- **完整回测** — 数据库回测框架，支持多策略多周期对比

### 适用场景

- 黄金（XAUUSD）自动化趋势/均值回归交易
- 24 小时运行，覆盖亚盘、欧盘、美盘
- H1 主周期趋势策略 + M30 短线震荡/趋势组合

---

## 2. 系统架构

```
┌──────────────────────────────────────────────────────────┐
│              MT4 终端 + FreeMT4Bridge EA                  │
│              (Socket 服务端, 端口 23232, 单客户端)          │
└─────────────────────┬────────────────────────────────────┘
                      │ TCP Socket (# 分隔协议)
┌─────────────────────▼────────────────────────────────────┐
│              core/bridge.py (桥接抽象层)                    │
│              core/freemt4_bridge.py (Socket 实现)          │
└─────────────────────┬────────────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────────────┐
│    engine_standalone/main.py (TradingEngine 主循环)        │
│                                                           │
│  ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌──────────┐ │
│  │ M30_rsi_bb │ │ sanqing_h1 │ │gold_auto │ │mtf_reso  │ │
│  │  (660706)  │ │  (880107)  │ │ (880306) │ │ (660801)  │ │
│  └────────────┘ └────────────┘ └──────────┘ └──────────┘ │
│  ┌──────────────┐ ┌──────────────┐                        │
│  │stoch_trend   │ │rsi_grading   │                        │
│  │  (660903)    │ │  (660902)    │                        │
│  └──────────────┘ └──────────────┘                        │
│                                                           │
│  独立价格轮询线程 (0.1s)     K 线缓存 (每 tick 1周期)      │
│  策略池热同步 (每 tick 自动 diff)                           │
│  信号生命周期管理            Trade Sync (3层检测)           │
│  多策略协调器 (联动出场+反向止盈)                            │
│                                                           │
│  services/news_filter.py  (ForexFactory 日历)              │
│  core/bias_state.py       (新闻预判偏多/偏空)               │
│  data/database.py         (SQLite: ohlcv + signals + 版本) │
│  data/downloader.py       (历史数据下载)                    │
└──────────┬────────────────────────────────────────────────┘
           │
┌──────────▼────────────────────────────────────────────────┐
│  dashboard/backend/ (FastAPI + WebSocket + EngineRunner)   │
│    ├── config_service.py  (RuntimeConfig 运行时配置覆盖)    │
│    ├── engine_runner.py   (引擎线程 + 缓存 + 价格轮询)      │
│    ├── web_manager.py     (WebSocket 连接管理)             │
│    ├── log_service.py     (日志捕获)                       │
│    └── routes/            (REST API 路由)                 │
│                                                           │
│  dashboard/frontend/ (Vue 3 + Naive UI + lightweight-charts)│
│    端口 1783 (FastAPI 直接 serve 前端 dist)                 │
└───────────────────────────────────────────────────────────┘
```

### 目录结构

```
xauusd/
├── config/
│   ├── settings.py              # 全局配置（连接/策略/风控/新闻）
│   ├── safety_lock.txt          # 安全锁文件（自动生成）
│   └── runtime_config.json      # 运行时配置覆盖（仪表盘生成）
├── core/
│   ├── bridge.py                # 桥接抽象基类 + 数据类型
│   ├── freemt4_bridge.py        # FreeMT4 Socket 桥接
│   ├── metaapi_bridge.py        # MetaApi 云端桥接（预留）
│   ├── runtime_config.py        # RuntimeConfig 运行时配置单例
│   ├── version.py               # 版本信息 + 远程更新检查 + git pull
│   └── bias_state.py            # 新闻预判偏多/偏空状态
├── engine_standalone/
│   ├── main.py                  # TradingEngine 交易引擎主循环
│   └── run.py                   # 启动前置检查 + 引擎启动
├── strategies/
│   ├── base.py                  # BaseStrategy 抽象基类
│   ├── m30_rsi.py               # M30 RSI+布林带均值回归 (v7, 660706)
│   ├── sanqing_h1.py            # H1 EMA9/21 趋势策略 (v6r, 880107)
│   ├── gold_autoresearch_h1.py  # H1 共识投票策略 (v6, 880306)
│   ├── mtf_resonance_h1.py      # H1 多周期共振策略 (660801)
│   ├── stoch_trend_m30.py       # M30 Stoch 三模趋势叠加 (v3, 660903)
│   ├── rsi_grading_m30.py       # M30 RSI 分级评分策略 (660902)
│   ├── v6_hybrid.py             # [已下架] H1 V6 混合策略
│   ├── stoch_m30.py             # [停用] M30 Stoch 纯震荡
│   ├── bakome_backup.py         # [备用]
│   ├── xaubot_backup.py         # [备用]
│   ├── backup/                  # 版本备份文件
│   └── STRATEGY_VERSIONING.md   # 版本管理规范文档
├── services/
│   ├── news_filter.py           # ForexFactory 新闻过滤
│   └── news_evaluator.py        # 新闻影响评估
├── data/
│   ├── database.py              # SQLite 存储（OHLCV + signals + versions）
│   ├── downloader.py            # 历史数据下载
│   └── market_data.db           # SQLite 数据库文件
├── dashboard/
│   ├── backend/                 # FastAPI 后端（端口 1783）
│   │   ├── main.py              # 应用入口 + 生命周期（自动启动引擎）
│   │   ├── config_service.py    # 运行时配置服务（RuntimeConfig 覆盖）
│   │   ├── engine_runner.py     # 引擎线程管理 + 缓存 + 价格轮询
│   │   ├── web_manager.py       # WebSocket 连接管理
│   │   ├── log_service.py       # 日志捕获服务
│   │   ├── strategy_registry.py # 策略注册表（显示元数据）
│   │   └── routes/              # REST API 路由
│   │       ├── engine.py        # /api/engine
│   │       ├── account.py       # /api/account
│   │       ├── positions.py     # /api/positions
│   │       ├── config.py        # /api/config
│   │       ├── market.py        # /api/market（K线从缓存读取）
│   │       ├── logs.py          # /api/logs
│   │       ├── news.py          # /api/news
│   │       ├── trades.py        # /api/trades（含分析+统计+版本子分组）
│   │       ├── signals.py       # /api/signals（信号生命周期查询）
│   │       ├── version.py       # /api/version（版本+changelog+更新）
│   │       ├── strategies.py    # /api/strategies
│   │       ├── reports.py       # /api/reports（日报/周报）
│   │       ├── news_bias.py     # /api/news-bias
│   │       ├── data.py          # /api/data
│   │       └── backtest.py      # /api/backtest
│   └── frontend/                # Vue 3 前端（Vite 构建）
│       └── src/
│           ├── AppShell.vue     # 主布局（侧栏+顶栏+版本badge+弹窗）
│           ├── views/           # 页面视图
│           │   ├── DashboardView.vue      # 交易终端
│           │   ├── PositionsView.vue      # 账户持仓
│           │   ├── StrategyCenterView.vue # 策略中心
│           │   ├── TradeHistoryView.vue   # 历史成交
│           │   ├── ConfigView.vue         # 运行配置
│           │   ├── ReportView.vue         # 日报周报
│           │   ├── PatrolView.vue         # 监控告警
│           │   └── LogsView.vue           # 系统日志
│           ├── stores/          # Pinia 状态管理
│           ├── api/             # API 客户端
│           └── components/      # UI 组件
├── monitor/
│   ├── patrol_daemon.py         # 独立巡检守护进程
│   └── .patrol_state.json       # 巡检状态文件
├── backtest/                    # 回测脚本和结果
├── tools/                       # 工具脚本
├── scripts/                     # 数据恢复脚本
├── docs/                        # 文档
├── VERSION                      # 版本号文件（当前 0.7.8）
└── start.py                     # 一键启动脚本
```

### 连接模式

系统支持两种 MT4 连接模式（通过 `config/settings.py` 中的 `MT4_MODE` 切换）：

| 模式 | 桥接实现 | 适用场景 |
|------|---------|---------|
| `freemt4` | FreeMT4Bridge | 本地 MT4 终端，TCP Socket 直连，延迟低 |
| `metaapi` | MetaApiBridge | 云端 MT4，无需本地终端，支持 VPS（部分功能待完善） |

### 端口一览

| 组件 | 端口 | 说明 |
|------|------|------|
| Backend API + Frontend | `127.0.0.1:1783` | FastAPI + Vue SPA（前端由后端 serve） |
| MT4 Bridge | `127.0.0.1:23232` | FreeMT4 TCP socket |
| Vite Dev Server | `127.0.0.1:5173` | 前端开发模式（仅开发时使用） |

---

## 3. 快速开始

### 3.1 环境要求

- Python ≥ 3.10
- MetaTrader 4 已安装并登录交易账户
- FreeMT4Bridge EA 已加载到 MT4 图表

### 3.2 MT4 端设置

1. 将 FreeMT4Bridge.ex4 复制到 `MQL4/Experts/`
2. 在 MT4 中打开 XAUUSD 图表（任意周期）
3. 将 FreeMT4Bridge EA 拖放到图表
4. 确保 EA 自动交易已启用（工具 → 选项 → 智能交易系统 → 允许算法交易）
5. 确认端口 23232（默认）未被占用

### 3.3 启动交易系统

```bash
# 方式一（推荐）：启动后端（引擎在 lifespan 中自动启动）
cd /d/backup/BaoBao/PythonProgram/xauusd
python dashboard/backend/main.py &

# 方式二：一键启动脚本
python start.py

# 方式三：仅启动交易引擎（无 Web 仪表盘）
python engine_standalone/run.py
```

启动后打开浏览器访问 `http://127.0.0.1:1783/`。

> **注意：** 从 v6 版本开始，`main.py` 的 FastAPI 生命周期（lifespan）自动调用 `engine_runner.start()`，无需手动调用 POST `/api/engine/start`。API 端口从 8000 变更为 1783。

### 3.4 重启引擎

```bash
# 1. API 优雅停止
curl -s -X POST http://127.0.0.1:1783/api/engine/stop

# 2. 强制杀进程（如果 API 失败）
ps aux | grep python | grep -v grep
kill -9 <PID>

# 3. 启动
python dashboard/backend/main.py &
```

### 3.5 策略池热同步

在 Dashboard → 策略中心调整策略池后，**无需重启引擎**。引擎在下一个 tick 自动检测配置变更：

- 禁用策略 → 自动移除运行中策略（如有持仓自动平仓）
- 启用策略 → 自动加载并初始化新策略
- 修改 max_positions/double_first → 自动更新实例属性

---

## 4. 配置指南

系统有两层配置：静态默认值（`config/settings.py`）和运行时覆盖（`dashboard/runtime_config.json`，通过 Dashboard 操作）。

### 4.1 MT4 连接配置

```python
MT4_MODE = "freemt4"                    # freemt4 | metaapi
FREEMT4_HOST = "127.0.0.1"
FREEMT4_PORT = 23232
```

### 4.2 交易基础参数

```python
SYMBOL = "XAUUSD"              # 交易品种
LOT_SIZE = 0.01                # 基础手数
SLIPPAGE = 30                  # 最大滑点（点）
MAGIC_NUMBER = 888888          # EA 魔术号（旧版兼容）
```

### 4.3 策略池配置

当前启用 6 个策略（其余 4 个停用）：

```python
STRATEGY_POOL = {
    "M30_rsi_bb":       { "magic": 660706, "timeframe": "M30", "max_positions": 1 },
    "sanqing_h1":       { "magic": 880107, "timeframe": "H1",  "max_positions": 1 },
    "gold_auto_research": { "magic": 880306, "timeframe": "H1", "max_positions": 1 },
    "mtf_resonance_h1": { "magic": 660801, "timeframe": "H1",  "max_positions": 1 },
    "stoch_trend_m30":  { "magic": 660903, "timeframe": "M30", "max_positions": 1 },
    "rsi_grading_m30":  { "magic": 660902, "timeframe": "M30", "max_positions": 1 },
}
```

### 4.4 Magic Number 规范

6 位数字：`PP` + `NN` + `VV`

| 位段 | 位数 | 含义 |
|------|------|------|
| PP   | 2    | 策略来源：`66` = 自研，`88` = 借鉴 |
| NN   | 2    | 策略上线序号 |
| VV   | 2    | 版本号，从 01 开始按修改次数递增 |

完整对照表见 `strategies/STRATEGY_VERSIONING.md`。

### 4.5 风控参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_DAILY_LOSS_PCT` | 12.0 | 全局硬止损（基于结算余额百分比） |
| `FLOATING_LOSS_WARN_PCT` | 5.0 | 浮动亏损警告阈值 |
| `FLOATING_LOSS_BLOCK_PCT` | 10.0 | 浮动亏损阻断阈值（恢复后自动解除） |
| `PER_STRATEGY_REALIZED_LOSS_PCT` | 5.0 | 单策略已实现亏损上限 |
| `PER_STRATEGY_LOSS_BLOCK_HOURS` | 12 | 策略亏损阻断冷却时间 |
| `PER_STRATEGY_REALIZED_LOSS_AMOUNT` | 30.0 | 绝对亏损冷却阈值（$） |
| `MAX_CONSECUTIVE_LOSSES` | 3 | 连续亏损阻断次数 |
| `CONSECUTIVE_LOSS_COOLDOWN_HOURS` | 4 | 连续亏损冷却时长 |
| `MAX_RAPID_EXITS` | 3 | 快速出场窗口最大次数 |
| `RAPID_EXIT_WINDOW_SECONDS` | 300 | 快速出场检测窗口（5 分钟） |
| `RAPID_EXIT_COOLDOWN_SECONDS` | 7200 | 快速出场冷却（2 小时） |
| `SAFETY_LOCK_TIMEOUT_MINUTES` | 240 | 安全锁自动过期时间（4 小时） |

### 4.6 新闻过滤配置

```python
NEWS_FILTER_ENABLED = True
NEWS_BEFORE_MINUTES = 30         # 事件前停止开仓
NEWS_AFTER_MINUTES = 120         # 事件后恢复交易
NEWS_PRE_TIGHTEN_MINUTES = 120   # 事件前开始收紧止损
NEWS_PRE_CLOSE_MINUTES = 15      # 事件前强制平仓
NEWS_IMPACT_FILTER = "High"      # 关注高影响事件
NEWS_CURRENCY_FILTER = "USD"     # 关注美元相关事件
```

### 4.7 新闻预判配置

```python
NEWS_BIAS_ENABLED = True                     # 启用新闻预判
NEWS_BIAS_REPORT_HOURS = "8,20"              # 报告生成时间（8点/20点）
BLOCK_LONG_WHEN_BIAS_BEARISH = True          # 偏空时禁多
BLOCK_SHORT_WHEN_BIAS_BULLISH = True         # 偏多时禁空
NEWS_BIAS_BLOCK_REFRESH_SECONDS = 60         # 缓存刷新间隔
```

### 4.8 运行时配置

通过 Dashboard → 运行配置调整，存储在 `runtime_config.json`：
- 风控参数、连接配置、新闻过滤、协调器
- 策略池管理在策略中心页面操作
- 所有配置持久化，引擎重启后保留

---

## 5. 交易引擎

交易引擎 `TradingEngine`（`engine_standalone/main.py`）是系统的核心。

### 5.1 引擎启动流程

```
启动:
  1. connect() MT4 桥接（带 30 次重试，每次 10 秒）
  2. 启动独立价格轮询线程 (0.1s 间隔, daemon)
  3. 校准 MT4 服务器时间
  4. 初始化各策略风控状态
  5. 接管现有持仓
  6. 记录起始余额
  7. 恢复遗漏历史成交
  8. 同步数据库 K 线数据完整性
  9. 写策略版本记录到数据库
  10. 进入主循环
```

### 5.2 主循环流程

每 tick 执行一次 `_tick()`（无阻塞时约 2~5 秒）：

```
_tick():
  1. [桥接] 心跳检测 / 断线重连
  2. [配置] 热重载（检查 settings.py mtime）
  3. [策略池] 热同步（自动增删策略，无需重启）
  4. [数据] 每 300 秒同步 K 线数据到 SQLite
  5. [新闻] 新闻风控处理（三级：收紧→强平→黑名单）
  6. [出场] 出场检查（每个策略的 check_ema20_exit）
  7. [协调] 协调器出场联动（cross_exit + M15 reverse TP）
  8. [风控] 更新浮动盈亏 + 全局硬止损检查
  9. [风控] 新闻黑名单/安全锁/各策略阻断检查
  10. [入场] 入场评估（通过所有检查的策略）
```

### 5.3 三层退出体系

所有策略共享统一的退出机制 `check_ema20_exit()`：

| 退出类型 | 说明 |
|---------|------|
| **利润回撤止盈** | 峰值利润回撤到设定比例时止盈 |
| **ATR 移动止盈** | 价格从极值反弹超过 ATR×trail_mult 时止盈 |
| **ATR 硬止损** | 亏损超过 ATR×hard_mult 时止损 |

**趋势感知乘数**：出场乘数根据当前趋势动态调整，顺势仓位更宽松，逆势仓位更收紧。

| 趋势 | 顺势仓位 | 逆势仓位 |
|------|---------|---------|
| UP/DOWN | trail=2.5, hard=4.0 | trail=1.0, hard=2.0 |
| NEUTRAL | trail=1.5, hard=3.0 | trail=1.5, hard=3.0 |

**新闻收紧模式**：事件前 120 分钟开始，trail=0.5, hard=1.0。

### 5.4 独立价格轮询线程

- 每 0.1 秒采样一次 MT4 价格（不受 _tick 主循环阻塞）
- 缓存位置：`EngineRunner._cached_price`
- 数据流向：价格 → Dashboard WebSocket (0.3s) → 前端实时显示
- PnL 重算：用最新 bid/ask 实时重算持仓盈亏

### 5.5 策略池热同步

引擎每 tick 自动执行 `_sync_strategy_pool()`：

1. 读取 RuntimeConfig 中的策略池配置（共享内存，API 写入后立即可见）
2. 与运行中的 `self.strategies` 列表做 diff
3. 禁用/移除的策略 → 自动调用 `remove_strategy()`（持仓自动平仓）
4. 新启用的策略 → 自动调用 `add_strategy()`（接管现有持仓）
5. 参数变更（max_positions/double_first）→ 自动更新实例属性

### 5.6 交易同步（Trade Sync）

三层检测机制确保 MT4 持仓与数据库记录一致：

| 层级 | 触发条件 | 动作 |
|------|---------|------|
| L1 | 持仓数下降 | 立即恢复遗漏成交 |
| L2 | 每 3600 秒 | 对比 MT4 vs DB 记录数 |
| L3 | L1/L2 触发 | 遍历 MT4 持仓找回缺失记录 |

### 5.7 优雅关闭

引擎支持两种关闭方式：
1. **API `POST /api/engine/stop`** → 设置停止标志 → 退出主循环 → 断开桥接
2. **强制杀进程** → `kill -9 <PID>` 或 `taskkill //F //PID <PID>`

---

## 6. 策略框架

### 6.1 BaseStrategy 基类

所有策略继承自 `strategies/base.py` 中的 `BaseStrategy`：

```python
class BaseStrategy(ABC):
    name: str           # 策略名称
    bridge: Bridge      # MT4 桥接
    symbol: str         # 交易品种
    magic: int          # 策略 Magic Number
    timeframe: str      # 运行周期
    candles: list       # K 线数据缓存

    @abstractmethod
    def generate_signal(self) -> Optional[OrderType]: ...
    def on_tick(self) -> Optional[str]: ...
    def reload_config(self): ...
    def check_ema20_exit(self, position, bid, ask) -> bool: ...
```

### 6.2 活跃策略一览

| 策略 | 周期 | Magic | 类型 | 入场方式 | 关键指标 |
|------|------|-------|------|---------|---------|
| M30_rsi_bb | M30 | 660706 | 均值回归 | 评分≥3 + H1趋势门控 | RSI, BB, ATR, DI |
| sanqing_h1 | H1 | 880107 | 趋势跟踪 | 评分≥5（ADX>25降为4） | EMA9/21, ATR, ADX |
| gold_auto_research | H1 | 880306 | 共识投票 | 四维度全票通过 | EMA, MACD, ADX, RSI, BB |
| mtf_resonance_h1 | H1 | 660801 | 多周期共振 | 多周期信号共振确认 | 多周期趋势对齐 |
| stoch_trend_m30 | M30 | 660903 | 三模自适应 | 窄幅/宽幅/趋势自动切换 | Stoch, BB, ADX, DI |
| rsi_grading_m30 | M30 | 660902 | 分级评分 | 因子评分+ADX阈值提升 | RSI, BB, MA, ADX |

各策略完整文档见 `docs/strategies/`，版本历史见 `strategies/STRATEGY_VERSIONING.md`。

### 6.3 停用/下架策略

| 策略 | 原因 | 说明 |
|------|------|------|
| H1_v6_hybrid | 已下架 | 602 笔回测亏损 $166，4 个超卖因子全亏 |
| stoch_m30 | 已停用 | 被 stoch_trend_m30 取代 |
| bakome_backup | 备用 | 未启用 |
| xaubot_backup | 备用 | 未启用 |

### 6.4 持仓位门控（Position Gate）

所有活跃策略均实现持仓位门控：

- **60 根 K 线价格区间**：计算 `recent_high` 和 `recent_low`
- **底部 10%**：禁止开空
- **顶部 10%**：禁止开多
- **M30 趋势门控**：M30 EMA20 方向与 SMA200 冲突时加严评分

---

## 7. 风控体系

系统实现十层风控，覆盖全局、策略、订单三个级别：

### 7.1 阻断层级

```
级别 1  — 全局硬止损（基于结算余额 12%）→ 所有策略阻断
级别 2  — 新闻黑名单 → 所有策略阻断（事件前30分钟到后120分钟）
级别 3  — 安全锁 → 所有策略阻断（4小时自动过期）
级别 4  — 已实现亏损百分比阻断（单策略 5%）→ 阻断12小时
级别 5  — 浮动亏损阻断（单策略 10%）→ 恢复后自动解除
级别 6  — 已实现亏损金额阻断（$30）→ 阻断12小时
级别 7  — 连续亏损阻断（3次）→ 阻断4小时
级别 8  — 快速出场阻断（5分钟内3次）→ 阻断2小时
级别 9  — 新闻收紧模式 → 出场乘数减半
级别 10 — 新闻强制平仓 → 平所有持仓
```

### 7.2 安全锁机制

当引擎检测到平仓持仓时间 < 30 秒且亏损时，自动触发安全锁：
1. 写入 `config/safety_lock.txt`
2. 所有策略阻断 4 小时
3. 自动过期检查（每 tick）

### 7.3 风控状态追踪

每个策略维护独立的 `StrategyRiskState`：
- `realized_pnl`、`floating_pnl`、`exit_timestamps`
- `realized_loss_blocked`、`floating_loss_blocked`
- `rapid_exit_blocked`、`consecutive_losses`

---

## 8. 多策略协调器

协调器提供两种策略间联动逻辑，通过 Dashboard → 运行配置调整。

### 8.1 功能①：跨策略联动出场

当信号策略的特定方向持仓盈利时，自动平掉目标策略的对应方向盈利单。

```
配置:
  signal_strategy: "H1_v6_hybrid"     # 信号源
  signal_direction: "BUY"             # 信号方向
  target_strategies: ["M30_rsi_bb"]   # 目标策略列表
  target_direction: "SELL"            # 平仓方向
```

### 8.2 功能②：M15 反向止盈

当 M15 EMA20 斜率反转时（趋势可能转变），平掉所有原方向盈利单。

灵敏度(sensitivity) 对应触发率：
- 0.0 = 原版敏感逻辑
- 0.5 = 触发率 ~25%（推荐）
- 1.0 = 触发率 ~2%

### 8.3 运行时配置

通过 `POST /api/config/coordinator` 运行时调整，持久化到 `runtime_config.json`。

---

## 9. 信号生命周期

信号系统记录了从策略生成信号到持仓平仓的完整链路。

### 9.1 状态流转

```
策略 on_tick() 生成信号 → status=pending
  ├── 开仓成功 → status=opened（记录 ticket）
  └── 开仓失败 → status=voided（记录 void_reason）
        ↓
     平仓触发 → status=closed（记录 exit_reason, realized_pnl）
```

### 9.2 废票（Voided Trades）

常见废票原因：`funds_slippage`、`market_closed`、`timeout`、`升级前记录`

### 9.3 出场原因

- `profit_drawdown` — 利润回撤止盈
- `trail_stop` — ATR 移动止盈
- `hard_stop` — ATR 硬止损
- `news_force_close` — 新闻强平
- `cross_exit` — 跨策略联动
- `m15_reverse_tp` — M15 反向止盈
- `manual_close` — 手动平仓

---

## 10. 新闻过滤与预判

### 10.1 数据源

- **日历：** ForexFactory（`https://nfs.faireconomy.media/ff_calendar_thisweek.json`）
- **过滤：** USD、High Impact 事件
- **预判：** 基于历史数据评估新闻影响方向（偏多/偏空/中性）

### 10.2 三级防护时间线

```
T-120min          T-15min          T        T+120min
  │                 │             │           │
  ▼                 ▼             ▼           ▼
收紧止损        强平所有        黑名单        恢复
乘数减半        持仓            禁止开仓      正常交易
```

### 10.3 新闻预判（Bias）

系统自动分析即将到来的新闻事件，给出偏多/偏空判断：

- 预判结果存储在数据库中，每日 8:00/20:00 自动更新
- 偏多时自动禁用空头开仓（`block_short_when_bias_bullish`）
- 偏空时自动禁用多头开仓（`block_long_when_bias_bearish`）
- Dashboard 弹窗展示最新预判结果

---

## 11. 策略版本管理

### 11.1 规范文件

见 `strategies/STRATEGY_VERSIONING.md`，包含 Magic Number 编号规则、版本历史和修改流程。

### 11.2 数据库版本记录

引擎启动时自动将各策略的 STRATEGY_CHANGELOG 写入 `strategy_versions` 表。

### 11.3 修改策略流程

1. 备份当前文件 → `strategies/backup/YYYYMMDD_文件名_版本.py`
2. 修改策略逻辑
3. 更新版本字段：`STRATEGY_VERSION`、`STRATEGY_MAGIC`、`STRATEGY_CHANGELOG`
4. 通过 Dashboard → 策略中心更新配置（引擎自动热同步，无需重启）

---

## 12. Web 仪表盘

### 12.1 技术栈

| 层 | 技术 | 端口 |
|----|------|------|
| 后端 | Python FastAPI + WebSocket | **1783** |
| 前端 | Vue 3 + TypeScript + Vite + Naive UI | 1783（后端 serve）/ 5173（开发模式） |
| 图表 | lightweight-charts（TradingView 风格） | — |

### 12.2 访问方式

浏览器打开 `http://127.0.0.1:1783/`

前端构建：
```bash
cd dashboard/frontend
npx vite build
# 重启后端以加载新 dist
```

### 12.3 界面导航

左侧菜单栏 8 个页面：

| 页面 | 路由 | 功能 |
|------|------|------|
| 交易终端 | `/` | 实时 K 线图、价格、策略列表、持仓 |
| 账户持仓 | `/positions` | 当前持仓列表（可展开查看详情） |
| 策略中心 | `/strategies` | 策略池管理、启停开关、Magic/周期配置 |
| 历史成交 | `/trades` | 已平仓记录（含废票 Tab）、按策略统计 |
| 运行配置 | `/config` | 风控参数、连接配置、新闻过滤、协调器 |
| 日报周报 | `/report` | 日报/周报查看 |
| 监控告警 | `/patrol` | 巡检报告、异常通知 |
| 系统日志 | `/logs` | 实时日志查看、级别过滤 |

### 12.4 版本 Badge（右上角）

版本 badge 显示当前版本号，功能定位为"检查 GitHub 更新"：

- **`v0.7.8 ✓`** — 绿色勾，表示已是最新版本
- **`v0.7.8 ● (3)`** — 红点亮起，数字为落后 commit 数
- **点击** → 弹窗显示待拉取的 commits + "版本更新"按钮
- **一键更新** → 执行 `git pull --ff-only`（仅增量拉取）
- **按钮灰色** → 工作区有未提交修改时禁用
- 每 5 分钟自动轮询检查远程更新

### 12.5 REST API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/engine/status` | GET | 引擎状态 |
| `/api/engine/health` | GET | 综合健康检查 |
| `/api/engine/start` | POST | 启动引擎 |
| `/api/engine/stop` | POST | 停止引擎 |
| `/api/engine/strategies` | GET | 运行中策略列表 |
| `/api/engine/strategies/add` | POST | 添加策略 |
| `/api/engine/strategies/remove` | POST | 移除策略 |
| `/api/account` | GET | 账户信息 |
| `/api/positions` | GET | 持仓列表 |
| `/api/config` | GET/POST | 配置读写 |
| `/api/config/strategy-pool` | GET/POST | 策略池配置 |
| `/api/config/coordinator` | GET/POST | 协调器配置 |
| `/api/market/price` | GET | 当前价格 |
| `/api/market/candles` | GET | K 线数据 |
| `/api/logs` | GET | 日志查询 |
| `/api/news` | GET | 财经事件 |
| `/api/news/bias` | GET | 新闻预判 |
| `/api/version` | GET | 版本信息（含远程更新状态） |
| `/api/version/changelog` | GET | 本地 commit 列表 |
| `/api/version/remote-changelog` | GET | 远程新 commit 列表 |
| `/api/version/update` | POST | 一键 git pull 更新 |
| `/api/trades/history` | GET | 历史成交 |
| `/api/trades/stats` | GET | 交易统计 |
| `/api/signals` | GET | 信号列表 |
| `/api/reports` | GET | 日报/周报 |
| `/api/strategies/available` | GET | 可用策略列表 |

### 12.6 WebSocket 推送

连接 `/ws` 端点：

| 频道 | 频率 | 数据 |
|------|------|------|
| `prices` | 0.3 秒 | bid, ask, spread |
| `positions` | 1 秒 | 持仓列表（含实时盈亏重算） |
| `account` | 10 秒 | 账户信息 |
| `logs` | 1 秒 | 新日志 |
| `status` | 15 秒 | 引擎状态 |
| `news_bias_popup` | 事件触发 | 新闻预判弹窗 |

### 12.7 策略中心

策略中心采用三段式布局：
1. **策略库** — 所有可用策略列表（含默认 Magic/周期）
2. **策略池** — 当前启用的策略，可开关、修改参数
3. **详情面板** — 选中策略的详细信息和版本历史

保存策略池后，引擎在下一个 tick 自动同步（无需重启）。

---

## 13. 版本更新机制

### 13.1 工作原理

右上角版本 badge 自动检查 GitHub 远程仓库是否有新版本：

1. 每 5 分钟 `git fetch origin` 静默更新 remote refs
2. 计算 `git rev-list --count HEAD..origin/main` 落后 commit 数
3. 有更新时红点亮起，显示落后数量
4. 点击弹窗显示待拉取的 commits 列表

### 13.2 一键更新

1. 点击"版本更新"按钮
2. 后端执行 `git pull --ff-only`（只拉取增量 commit）
3. 成功后版本信息自动刷新
4. **注意**：更新代码后需要重启引擎和后端才能生效

### 13.3 安全条件

- 工作区有未提交修改时，"版本更新"按钮自动禁用
- 提示用户先提交或暂存本地修改

---

## 14. 监控守护进程

### 14.1 概述

`monitor/patrol_daemon.py` 独立进程，每 30 秒通过 REST API 巡检一次。

### 14.2 巡检项目

1. **引擎状态** — 调用 `/api/engine/status`，异常则弹窗告警
2. **价格监控** — 检查价格偏离参考价超过 20 点
3. **持仓变化** — 检测新开仓、平仓
4. **亏损分析** — 自动分析亏损单原因和建议
5. **错误日志** — 报告 ERROR 级日志

### 14.3 启动

```bash
python monitor/patrol_daemon.py
```

---

## 15. 数据管理

### 15.1 SQLite 数据库

**文件：** `data/market_data.db`

**核心表：** ohlcv（K 线）、signals（信号生命周期）、trades（成交记录）、strategy_versions（策略版本）、account_snapshots（账户快照）、risk_states（风控状态）、news_calendar（新闻日历）、news_evaluations（新闻评估）、news_bias_reports（预判报告）

### 15.2 数据下载

三种模式：增量同步、全量回填、全周期下载。

### 15.3 数据库恢复脚本

| 脚本 | 功能 |
|------|------|
| `scripts/extract_trades.py` | 从日志文件提取历史成交 |
| `scripts/recover_trades.py` | 通过 MT4 桥接恢复历史订单 |

---

## 16. 回测系统

### 16.1 回测框架

三种方式：数据库回测（Pandas）、Backtrader 回测、纯 Pandas 回测。

### 16.2 关键回测脚本

| 脚本 | 说明 |
|------|------|
| `db_backtest_v6.py` | V6 Hybrid 策略数据库回测 |
| `db_backtest_7strategies.py` | 多策略同数据对比 |
| `db_backtest_mtf.py` | 多周期回测 |
| `m30_rsi_optimize.py` | M30 RSI 参数扫描 |

---

## 17. 故障排除

### 17.1 引擎无法启动

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| 桥接连接失败 | MT4 未运行/EA 未加载 | 检查 MT4 终端，确保 EA 已加载 |
| 端口被占用 | 旧进程残留 | `ps aux \| grep python` → `kill -9 <PID>` |
| 引擎显示 stopped | MT4 桥接断开 | 确认 MT4 终端运行中 + EA 已加载 |

### 17.2 桥接连断开

```
检查步骤：
1. MT4 终端是否运行
2. FreeMT4Bridge EA 是否在图表上
3. EA 自动交易是否启用
4. 端口 23232 是否可达
```

### 17.3 日志编码问题

GBK 终端下中文日志显示为乱码，通过 `/api/logs` API 读取正常。用 PowerShell 或 API 查看日志可避免编码问题。

### 17.4 安全锁误触发

安全锁文件位置：`config/safety_lock.txt`
- 如发现策略全部被阻断，首先检查该文件是否存在
- 删除文件即可手动解除安全锁
- 自动过期时间：240 分钟

### 17.5 版本更新失败

| 问题 | 原因 | 解决 |
|------|------|------|
| 版本更新按钮灰色 | 工作区有未提交修改 | 先提交或暂存代码 |
| git pull 失败 | 远程有冲突 | 手动 `git pull` 解决冲突 |
