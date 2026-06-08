# XAUUSD 量化交易系统 — 产品手册

## 目录

1. [系统概述](#1-系统概述)
2. [系统架构](#2-系统架构)
3. [快速开始](#3-快速开始)
4. [配置指南](#4-配置指南)
5. [交易引擎](#5-交易引擎)
6. [策略框架](#6-策略框架)
7. [风控体系](#7-风控体系)
8. [新闻过滤](#8-新闻过滤)
9. [Web 仪表盘](#9-web-仪表盘)
10. [监控守护进程](#10-监控守护进程)
11. [数据管理](#11-数据管理)
12. [回测系统](#12-回测系统)
13. [工具集](#13-工具集)
14. [故障排除](#14-故障排除)

---

## 1. 系统概述

XAUUSD 量化交易系统是一个专为黄金（XAUUSD）设计的自动化交易平台，通过 Python 控制 MetaTrader 4 终端执行交易。系统采用多策略并行架构，支持动态策略管理、多层风控、实时 Web 监控和独立巡检守护。

### 核心特性

- **多策略并行** — 同时运行多个独立策略，每个策略有独立的 Magic Number 和风控状态
- **动态策略管理** — 运行中可热添加/移除策略，无需重启引擎
- **三层退出体系** — 利润回撤止盈 + ATR 移动止盈 + ATR 硬止损，趋势感知乘数
- **多层风控** — 10 层风控机制，从全局到单策略全覆盖
- **新闻保护** — 集成 ForexFactory 财经日历，三级新闻防护
- **实时仪表盘** — Web 端实时查看价格、持仓、账户、日志
- **独立巡检** — 独立进程 30 秒轮询，异常自动告警
- **完整回测** — 数据库回测框架，支持策略参数优化

### 适用场景

- 黄金（XAUUSD）自动化趋势/均值回归交易
- 24 小时运行，覆盖亚盘、欧盘、美盘
- H1 主周期趋势策略 + M30 短线均值回归策略组合

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    MT4 终端 + FreeMT4Bridge EA           │
│                    (Socket 服务端, 端口 23232)             │
└──────────────────────┬──────────────────────────────────┘
                       │ TCP Socket (# 分隔协议)
┌──────────────────────▼──────────────────────────────────┐
│              core/bridge.py (桥接抽象层)                   │
│              core/freemt4_bridge.py (Socket 实现)          │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│           engine_standalone/main.py (交易引擎主循环)       │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ M30_rsi  │ │ sanqing  │ │ v6_hybrid│ │gold_auto │   │
│  │ _bb      │ │ _h1      │ │          │ │_research │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│                                                         │
│  services/news_filter.py  (ForexFactory 日历)            │
│  data/database.py         (SQLite 存储)                  │
│  data/downloader.py       (历史数据下载)                  │
└──────────┬──────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────┐
│           dashboard/backend/ (FastAPI + WebSocket)        │
│           dashboard/frontend/ (Vue 3 + Naive UI)          │
└──────────────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────┐
│           monitor/patrol_daemon.py (独立巡检守护进程)       │
└──────────────────────────────────────────────────────────┘
```

### 目录结构

```
xauusd/
├── config/
│   └── settings.py              # 全局配置（连接/策略/风控/新闻）
├── core/
│   ├── bridge.py                # 桥接抽象基类 + 数据类型
│   ├── freemt4_bridge.py        # FreeMT4 Socket 桥接
│   └── metaapi_bridge.py        # MetaApi 云端桥接（预留）
├── engine_standalone/
│   ├── main.py                  # TradingEngine 交易引擎主循环
│   └── run.py                   # 启动前置检查 + 引擎启动
├── strategies/
│   ├── base.py                  # BaseStrategy 抽象基类
│   ├── m30_rsi.py               # M30 RSI+布林带均值回归
│   ├── v6_hybrid.py             # H1 多因子 V6 混合策略
│   ├── sanqing_h1.py            # H1 EMA9/21 趋势策略
│   └── gold_autoresearch_h1.py  # H1 共识投票策略
├── services/
│   └── news_filter.py           # ForexFactory 新闻过滤
├── data/
│   ├── database.py              # SQLite OHLCV 存储
│   └── downloader.py            # 历史数据下载
├── dashboard/
│   ├── backend/                 # FastAPI 后端
│   │   ├── main.py              # 应用入口 + 生命周期
│   │   ├── config_service.py    # 运行时配置服务
│   │   ├── engine_runner.py     # 引擎线程管理
│   │   ├── web_manager.py       # WebSocket 连接管理
│   │   ├── log_service.py       # 日志捕获服务
│   │   └── routes/              # REST API 路由
│   │       ├── engine.py        # /api/engine
│   │       ├── account.py       # /api/account
│   │       ├── positions.py     # /api/positions
│   │       ├── config.py        # /api/config
│   │       ├── market.py        # /api/market
│   │       ├── logs.py          # /api/logs
│   │       ├── news.py          # /api/news
│   │       ├── trades.py        # /api/trades
│   │       ├── data.py          # /api/data
│   │       └── backtest.py      # /api/backtest
│   └── frontend/                # Vue 3 前端
│       └── src/
│           ├── views/           # 7 个页面视图
│           ├── stores/          # Pinia 状态管理
│           ├── api/             # API 客户端
│           └── components/      # UI 组件
├── monitor/
│   └── patrol_daemon.py         # 独立巡检守护进程
├── backtest/                    # 回测脚本和结果
├── tools/                       # 工具脚本
├── scripts/                     # 数据恢复脚本
└── docs/                        # 文档
```

### 连接模式

系统支持两种 MT4 连接模式（通过 `config/settings.py` 中的 `MT4_MODE` 切换）：

| 模式 | 桥接实现 | 适用场景 |
|------|---------|---------|
| `freemt4` | FreeMT4Bridge | 本地 MT4 终端，TCP Socket 直连，延迟低 |
| `metaapi` | MetaApiBridge | 云端 MT4，无需本地终端，支持 VPS（部分功能待完善） |

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
# 方式一：启动菜单
start.bat

# 方式二：直接启动引擎
python engine_standalone/run.py

# 方式三：启动完整仪表盘
python -m dashboard.backend.main
cd dashboard/frontend && npm run dev
```

### 3.4 前置检查

启动脚本 `run.py` 自动执行以下检查：

1. Python 版本 ≥ 3.10
2. 核心模块可导入
3. 配置文件有效（STRATEGY_POOL、SYMBOL、LOT_SIZE）
4. FreeMT4 EA Socket 可达（127.0.0.1:23232）
5. data/ 和 logs/ 目录存在

所有检查通过后启动交易引擎。

### 3.5 启动菜单 (start.bat)

```
========================================
  XAUUSD Trading Bot
========================================
1. 检查环境 setup
2. 开始交易
3. 运行回测
4. 后台监控
========================================
```

---

## 4. 配置指南

所有配置集中在 `config/settings.py`，支持运行时热重载。

### 4.1 MT4 连接配置

```python
MT4_MODE = "freemt4"                    # freemt4 | metaapi
FREEMT4_HOST = "127.0.0.1"
FREEMT4_PORT = 23232
```

### 4.2 交易基础参数

```python
SYMBOL = "XAUUSD"                       # 交易品种
LOT_SIZE = 0.01                         # 基础手数
SLIPPAGE = 30                           # 最大滑点（点）
```

### 4.3 策略池配置

```python
STRATEGY_POOL = {
    "M30_rsi_bb":       {"magic": 777001, "timeframe": "M30", "double_first": False, "max_positions": 1},
    "H1_v6_hybrid":     {"magic": 666666, "timeframe": "H1", "double_first": False, "max_positions": 1},
    "sanqing_h1":       {"magic": 777002, "timeframe": "H1", "double_first": False, "max_positions": 1},
    "gold_auto_research": {"magic": 777003, "timeframe": "H1", "double_first": False, "max_positions": 1},
}
```

每个策略条目包含：
- `magic` — 唯一 Magic Number，用于区分各策略的订单
- `timeframe` — 策略运行周期
- `double_first` — 首单是否双倍手数（0.02）
- `max_positions` — 最大同时持仓数

### 4.4 风控参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_DAILY_LOSS_PCT` | 12.0 | 全局硬止损（基于结算余额） |
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
| `SAFETY_LOCK_TIMEOUT_MINUTES` | 90 | 安全锁自动过期时间 |

### 4.5 新闻过滤配置

```python
NEWS_FILTER_ENABLED = True
NEWS_BEFORE_MINUTES = 30       # 事件前停止开仓
NEWS_AFTER_MINUTES = 120       # 事件后恢复交易
NEWS_PRE_TIGHTEN_MINUTES = 120 # 事件前开始收紧止损
NEWS_PRE_CLOSE_MINUTES = 15    # 事件前强制平仓
NEWS_IMPACT_FILTER = "High"    # 关注高影响事件
NEWS_CURRENCY_FILTER = "USD"   # 关注美元相关事件
```

### 4.6 运行时配置

通过 Web 仪表盘调整运行时配置，存储在 `runtime_config.json`，支持：
- 单键或批量读取/设置/重置
- 策略池动态管理
- 协调器参数调整

---

## 5. 交易引擎

交易引擎 `TradingEngine`（`engine_standalone/main.py`）是系统的核心，运行在主线程循环中。

### 5.1 主循环流程

每 20 秒执行一次 `_tick()`：

```
_tick():
  1. 配置热重载（检查 settings.py 修改时间）
  2. 桥接心跳检测 / 断线重连
  3. 每 300 秒同步 K 线数据到 SQLite
  4. 新闻风控处理（三级：收紧→强平→黑名单）
  5. 出场检查（所有策略的 check_ema20_exit）
  6. 协调器出场联动（如启用）
  7. M15/M5 反转止盈（如启用）
  8. 更新浮动盈亏
  9. 全局硬止损检查（12%）
  10. 新闻黑名单检查
  11. 安全锁检查
  12. 各策略阻断状态检查
  13. 入场（通过所有检查的策略）
```

### 5.2 入场流程

```
入场（每个策略独立）:
  1. 检查策略是否被阻断
  2. 双重确认持仓数（桥接查询 + 本地计数器）
  3. 检查 max_positions 上限
  4. 调用 strategy.on_tick() 生成信号
  5. 如有信号，执行 open_order()
```

### 5.3 出场流程

```
出场（每个策略的每个持仓独立）:
  1. 调用 strategy.check_ema20_exit()
  2. 如触发出场，执行 close_order()
  3. 记录交易详情到 closed_trades.jsonl
  4. 更新策略风控状态
```

### 5.4 动态策略管理

引擎支持运行时动态添加/移除策略：

```python
# 添加策略
engine.add_strategy("new_strategy", {"magic": 777004, "timeframe": "H1", ...})

# 移除策略
engine.remove_strategy("new_strategy", close_positions=True)
```

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

    def refresh_data(self, count=200): ...
    def on_tick(self) -> Optional[str]: ...
    def reload_config(self): ...
    def filter_positions(self, positions): ...
```

### 6.2 三层退出体系

所有策略共享统一的退出机制 `check_ema20_exit()`：

| 退出类型 | 多头条件 | 空头条件 | 说明 |
|---------|---------|---------|------|
| **利润回撤止盈** | 峰值利润 > ATR×0.5 且当前利润/峰值 < 0.75 | 同上 | 保护已有利润 |
| **ATR 移动止盈** | 最高价 - 卖价 > ATR×trail_mult | 卖价 - 最低价 > ATR×trail_mult | 追踪趋势 |
| **ATR 硬止损** | 开仓价 - 卖价 > ATR×hard_mult | 卖价 - 开仓价 > ATR×hard_mult | 限制亏损 |

**趋势感知乘数：** 出场乘数根据 H1 趋势方向动态调整：

| 趋势 | 顺势仓位 | 逆势仓位 |
|------|---------|---------|
| UP | trail=1.5, hard=3.0 | trail=1.0, hard=2.0 |
| DOWN | trail=1.5, hard=3.0 | trail=1.0, hard=2.0 |
| NEUTRAL | trail=1.2, hard=2.5 | trail=1.2, hard=2.5 |

**新闻收紧模式：** trail_mult=0.5, hard_mult=1.0, profit_drawdown_pct=0.15

**盈利/亏损分离逻辑：**
- 利润 > 0 时：使用移动止盈 + 利润回撤止盈 + 硬止损
- 利润 ≤ 0 时：仅使用硬止损（防止过早止损出局）

### 6.3 活跃策略一览

| 策略 | 周期 | Magic | 入场方式 | 关键指标 |
|------|------|-------|---------|---------|
| M30_rsi_bb | M30 | 777001 | 5因子评分≥3 + H1趋势门控 | RSI, BB, ATR, SMA200 |
| sanqing_h1 | H1 | 777002 | 6因子评分≥5 | EMA9/21, ATR, Volume |
| H1_v6_hybrid | H1 | 666666 | 8因子评分≥3 | KDJ, BB, KC, MACD, RSI |
| gold_auto_research | H1 | 777003 | 4因子共识（全票通过） | EMA, MACD, ADX, RSI, BB |

详见各策略单独文档：`docs/strategies/`

---

## 7. 风控体系

系统实现十层风控，覆盖全局、策略、订单三个级别：

### 7.1 阻断层级

```
级别 1 — 全局硬止损（基于结算余额 12%）
  触发 → 所有策略阻断，直到手动恢复

级别 2 — 新闻黑名单
  触发 → 所有策略阻断（事件前30分钟到后120分钟）

级别 3 — 安全锁
  触发 → 所有策略阻断（90分钟自动过期）
  触发条件: 平仓持仓 < 30秒且亏损

级别 4 — 已实现亏损百分比阻断（单策略 5%）
  触发 → 该策略阻断 12 小时

级别 5 — 浮动亏损阻断（单策略 10%）
  触发 → 该策略阻断，恢复后自动解除

级别 6 — 已实现亏损金额阻断（$30）
  触发 → 该策略阻断 12 小时

级别 7 — 连续亏损阻断（3次）
  触发 → 该策略阻断 4 小时

级别 8 — 快速出场阻断（5分钟内3次）
  触发 → 该策略阻断 2 小时

级别 9 — 新闻收紧模式
  触发 → 出场乘数减半（事件前120分钟到前15分钟）

级别 10 — 新闻强制平仓
  触发 → 平所有持仓（事件前15分钟到事件开始）
```

### 7.2 风控状态追踪

每个策略（按 Magic Number）维护独立的风控状态：

```python
StrategyRiskState:
    realized_pnl: float           # 累计已实现盈亏
    floating_pnl: float           # 当前浮动盈亏
    exit_timestamps: deque        # 出场时间戳队列
    realized_loss_blocked: bool   # 已实现亏损阻断
    floating_loss_blocked: bool   # 浮动亏损阻断
    rapid_exit_blocked: bool      # 快速出场阻断
    consecutive_losses: int       # 连续亏损计数
    realized_loss_amount_blocked: bool  # 亏损金额阻断
```

### 7.3 可疑持仓检测

当平仓持仓时间 < 30 秒且亏损时，引擎自动：
1. 写入 `config/safety_lock.txt`
2. 所有策略阻断 90 分钟
3. 阻断自动过期（文件 timestamp 检查）

---

## 8. 新闻过滤

### 8.1 数据源

- **来源：** ForexFactory 本周日历（`https://nfs.faireconomy.media/ff_calendar_thisweek.json`）
- **缓存：** 内存缓存，1 小时 TTL
- **过滤：** USD、High Impact 事件

### 8.2 三级防护时间线

```
     T-120min          T-15min          T        T+120min
       │                 │             │           │
       ▼                 ▼             ▼           ▼
   ┌───────┐       ┌────────┐    ┌────────┐   ┌────────┐
   │ 收紧  │       │ 强平   │    │ 黑名单  │   │ 恢复   │
   │ 止损  │       │ 所有   │    │ 禁止   │   │ 正常   │
   │ 乘数  │       │ 持仓   │    │ 开仓   │   │ 交易   │
   └───────┘       └────────┘    └────────┘   └────────┘
```

### 8.3 新闻影响模式

| 阶段 | 时间窗口 | 操作 |
|------|---------|------|
| 收紧 | 事件前 120 分钟 → 前 15 分钟 | trail_mult=0.5, hard_mult=1.0 |
| 强平 | 事件前 15 分钟 → 事件开始 | 平所有持仓 |
| 黑名单 | 事件前 30 分钟 → 后 120 分钟 | 禁止任何新开仓 |

---

## 9. Web 仪表盘

### 9.1 技术栈

| 层 | 技术 | 端口 |
|----|------|------|
| 后端 | Python FastAPI + WebSocket | 8000 |
| 前端 | Vue 3 + TypeScript + Vite + Naive UI | 5173 |

### 9.2 启动方式

```bash
# 方式一：独立启动
python -m dashboard.backend.main
# 前端分离启动
cd dashboard/frontend && npm run dev

# 方式二：一键启动（自动打开浏览器）
python dashboard/launcher.py
```

### 9.3 界面导航

左侧菜单栏 7 个页面：

| 页面 | 路由 | 功能 |
|------|------|------|
| 交易终端 | `/` | 实时价格图表、交易操作 |
| 账户持仓 | `/positions` | 当前持仓列表、平仓/修改 |
| 策略中心 | `/strategies` | 策略运行状态、信号查看 |
| 监控告警 | `/patrol` | 巡检报告、异常通知 |
| 历史成交 | `/trades` | 已平仓记录、策略统计 |
| 运行配置 | `/config` | 运行时参数调整 |
| 系统日志 | `/logs` | 实时日志查看、过滤 |

### 9.4 REST API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/engine/status` | GET | 引擎状态 |
| `/api/engine/health` | GET | 综合健康检查（RED/YELLOW/GREEN） |
| `/api/engine/start` | POST | 启动引擎 |
| `/api/engine/stop` | POST | 停止引擎 |
| `/api/engine/strategies` | GET | 策略列表 |
| `/api/engine/strategies/add` | POST | 添加策略 |
| `/api/engine/strategies/remove` | POST | 移除策略 |
| `/api/account` | GET | 账户信息 |
| `/api/positions` | GET | 持仓列表 |
| `/api/positions/{ticket}/close` | POST | 平仓 |
| `/api/positions/{ticket}/modify` | POST | 修改 SL/TP |
| `/api/config` | GET/POST | 配置读写 |
| `/api/config/{key}` | GET/POST | 单键配置 |
| `/api/config/{key}/reset` | POST | 重置配置 |
| `/api/config/strategy-pool` | GET/POST | 策略池配置 |
| `/api/config/coordinator` | GET/POST | 协调器配置 |
| `/api/market/price` | GET | 当前价格 |
| `/api/market/candles` | GET | K 线数据 |
| `/api/logs` | GET | 日志查询 |
| `/api/news` | GET | 财经事件 |
| `/api/trades/history` | GET | 历史成交 |
| `/api/trades/stats` | GET | 交易统计（MT4 报表格式） |
| `/api/trades/{ticket}/analysis` | GET | 单笔交易分析 |
| `/api/data/status` | GET | 数据库状态 |
| `/api/data/download` | POST | 触发数据下载 |

### 9.5 WebSocket 推送

连接 `/ws` 端点，接收频道消息：

| 频道 | 频率 | 数据 |
|------|------|------|
| `prices` | 2 秒 | bid, ask, spread |
| `positions` | 5 秒 | 持仓列表 |
| `account` | 10 秒 | 账户信息 |
| `logs` | 1 秒 | 新日志 |
| `status` | 15 秒 | 引擎状态 |

### 9.6 健康检查指标

`GET /api/engine/health` 返回综合健康状态：

- **GREEN** — 全部正常
- **YELLOW** — 桥接断开/引擎停止
- **RED** — 全局亏损阻断/高亏损

---

## 10. 监控守护进程

### 10.1 概述

`monitor/patrol_daemon.py` 是一个独立进程，不依赖引擎代码，只通过 REST API 通信。每 30 秒巡检一次。

### 10.2 巡检项目

1. **引擎状态** — 调用 `/api/engine/status`，异常则弹窗告警
2. **价格监控** — 检查价格偏离参考价（默认 4507）超过 20 点
3. **持仓变化** — 检测新开仓、平仓，监控特定止损位（4480.03）
4. **亏损分析** — 检测新平仓记录，自动分析亏损单原因和建议
5. **错误日志** — 报告 ERROR 级日志

### 10.3 告警方式

- **关键告警：** Windows MessageBox 弹窗（PowerShell）
- **一般通知：** 日志记录

### 10.4 启动

```bash
python monitor/patrol_daemon.py
```

### 10.5 状态文件

位置：`monitor/.patrol_state.json`
记录：持仓列表、引擎状态、已触发告警、已分析亏损单

---

## 11. 数据管理

### 11.1 SQLite 数据库

**文件：** `data/market_data.db`

**表结构：**
```sql
CREATE TABLE ohlcv (
    timeframe TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (timeframe, timestamp)
);
```

**支持的周期：** M1, M5, M15, M30, H1, H4, D1, W1

### 11.2 数据下载

三种模式：

1. **增量同步** — `download_timeframe()`，检查最新时间戳，只补充缺失数据
2. **全量回填** — `download_timeframe_paged()`，分页从最新回填到 2024-01-01
3. **全周期下载** — `download_all_paged()`，依次下载 M15/H1/H4/D1

### 11.3 交易记录

**文件：** `logs/closed_trades.jsonl`
每条记录包含：ticket、策略、方向、开平仓价、盈亏、持仓时间、出场原因等。

### 11.4 数据库恢复脚本

| 脚本 | 功能 |
|------|------|
| `scripts/extract_trades.py` | 从 GBK 编码日志文件提取历史成交 |
| `scripts/recover_trades.py` | 通过 MT4 桥接恢复历史订单 |

---

## 12. 回测系统

### 12.1 回测框架

三种回测方式：

| 方式 | 框架 | 特点 |
|------|------|------|
| 数据库回测 | 纯 Pandas | 直接从 market_data.db 读取数据，计算指标，逐根遍历 |
| Backtrader 回测 | Backtrader | 标准回测框架，支持参数优化 |
| 纯 Pandas 回测 | Pandas | 简单策略快速验证 |

### 12.2 关键回测脚本

| 脚本 | 说明 |
|------|------|
| `db_backtest_v6.py` | V6 Hybrid 策略数据库回测 |
| `db_backtest_7strategies.py` | 7 种策略同数据对比 |
| `db_backtest_mtf.py` | 多周期回测 |
| `backtest_optimization.py` | Backtrader 参数优化 |
| `backtest_cross_timeframe.py` | 跨周期对比 |
| `m30_rsi_optimize.py` | M30 RSI 参数扫描 |
| `v6_live_backtest.py` | 实盘数据回测 |

### 12.3 回测指标

遵循 MT4 Strategy Tester 标准报表格式：

- **核心盈亏：** 总净盈亏、毛利、毛损、Profit Factor、Expected Payoff
- **交易统计：** 总次数、多空分布、胜率、最大/平均单笔盈亏
- **持仓时间：** 平均持仓时间
- **连损连盈：** 最大连续亏损/盈利次数和金额
- **回撤：（待实现基于 equity 曲线的回撤计算）**

---

## 13. 工具集

| 工具 | 文件 | 功能 |
|------|------|------|
| 环境检查 | `tools/check_setup.py` | 检查 Python/依赖/MT4/端口 |
| 终端监控 | `tools/monitor.py` | 控制台实时仪表盘 |
| 账户信息 | `tools/account_info.py` | 查看账户详情 |
| 调整止损 | `tools/adjust_sl.py` | 修改持仓止损 |
| 远置止盈 | `tools/adjust_tp_far.py` | 将止盈移至远处 |
| 平盈利单 | `tools/close_profitable.py` | 仅平盈利持仓 |
| 参数扫描 | `tools/parameter_scan.py` | V6 Hybrid 参数网格搜索 |
| 模型训练 | `tools/train_xaubot.py` | ML 模型训练（预留） |

---

## 14. 故障排除

### 14.1 引擎无法启动

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| Socket 连接失败 | MT4 未运行/EA 未加载 | 检查 MT4 终端，确保 EA 已加载 |
| 配置文件错误 | settings.py 语法错误 | 检查配置文件，确认 STRATEGY_POOL 有效 |
| 端口被占用 | 旧进程残留 | 检查并关闭旧进程 |

### 14.2 桥接连断开

```
检查步骤：
1. MT4 终端是否运行
2. FreeMT4Bridge EA 是否在图表上
3. EA 自动交易是否启用
4. 端口 23232 是否可达
```

### 14.3 数据库问题

| 问题 | 解决方案 |
|------|---------|
| 数据为空 | 调用 `/api/data/download` 或运行 `data/downloader.py` |
| 数据不完整 | 运行 `download_all_paged()` 全量回填 |
| 数据库锁定 | 检查是否有其他进程占用，SQLite 使用 WAL 模式 |

### 14.4 日志重复

重启仪表盘后端：
```bash
# 检查旧进程
tasklist | findstr python
# 重启时使用 uvicorn.run(app) 而非 uvicorn.run("module:app")
```
