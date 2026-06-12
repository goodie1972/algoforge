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
10. [新闻过滤](#10-新闻过滤)
11. [策略版本管理](#11-策略版本管理)
12. [Web 仪表盘](#12-web-仪表盘)
13. [监控守护进程](#13-监控守护进程)
14. [数据管理](#14-数据管理)
15. [回测系统](#15-回测系统)
16. [工具集](#16-工具集)
17. [故障排除](#17-故障排除)

---

## 1. 系统概述

XAUUSD 量化交易系统是一个专为黄金（XAUUSD）设计的自动化交易平台，通过 Python 控制 MetaTrader 4 终端执行交易。系统采用多策略并行架构，支持动态策略管理、多层风控、实时 Web 监控和独立巡检守护。

### 核心特性

- **多策略并行** — 同时运行 4 个独立策略，每个策略有独立的 Magic Number 和风控状态
- **信号全生命周期管理** — 从信号生成、开仓、废票到平仓的全链路追踪
- **持仓位门控** — 60 根 K 线价格区间上下 10% 范围内限制逆势开仓
- **三层退出体系** — 利润回撤止盈 + ATR 移动止盈 + ATR 硬止损，趋势感知乘数
- **多策略协调器** — 跨策略联动出场 + M15 斜率归一化反向止盈
- **十层风控** — 从全局到单策略全覆盖，含独立安全锁机制
- **新闻保护** — 集成 ForexFactory 财经日历，三级新闻防护
- **实时仪表盘** — Web 端实时查看价格、持仓、信号、账户、日志
- **独立巡检** — 独立进程 30 秒轮询，异常自动告警
- **策略版本管理** — Magic Number 标准化编号，Changelog 持久化到数据库
- **完整回测** — 数据库回测框架，支持多策略多周期对比

### 适用场景

- 黄金（XAUUSD）自动化趋势/均值回归交易
- 24 小时运行，覆盖亚盘、欧盘、美盘
- H1 主周期趋势策略 + M30 短线均值回归策略组合

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
│  │ M30_rsi_bb │ │ sanqing_h1 │ │v6_hybrid │ │gold_auto │ │
│  │  (660705)  │ │  (880105)  │ │ (660606) │ │ (880306)  │ │
│  └────────────┘ └────────────┘ └──────────┘ └──────────┘ │
│                                                           │
│  独立价格轮询线程 (0.1s)     K 线缓存 (每 tick 1周期)      │
│  信号生命周期管理            Trade Sync (3层检测)           │
│  多策略协调器 (联动出场+反向止盈)                            │
│                                                           │
│  services/news_filter.py  (ForexFactory 日历)              │
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
│   └── metaapi_bridge.py        # MetaApi 云端桥接（预留）
├── start.py                     # ⭐ 一键启动脚本（端口清理+API+引擎）
├── engine_standalone/
│   ├── main.py                  # TradingEngine 交易引擎主循环
│   └── run.py                   # 启动前置检查 + 引擎启动
├── strategies/
│   ├── base.py                  # BaseStrategy 抽象基类
│   ├── m30_rsi.py               # M30 RSI+布林带均值回归 (v5, 660705)
│   ├── v6_hybrid.py             # H1 多因子 V6 混合策略 (v6, 660606)
│   ├── sanqing_h1.py            # H1 EMA9/21 趋势策略 (v4, 880105)
│   ├── gold_autoresearch_h1.py  # H1 共识投票策略 (v6, 880306)
│   ├── backup/                  # 版本备份文件
│   └── STRATEGY_VERSIONING.md   # 版本管理规范文档
├── services/
│   └── news_filter.py           # ForexFactory 新闻过滤
├── data/
│   ├── database.py              # SQLite 存储（OHLCV + signals + versions）
│   ├── downloader.py            # 历史数据下载
│   └── market_data.db           # SQLite 数据库文件
├── dashboard/
│   ├── backend/                 # FastAPI 后端
│   │   ├── main.py              # 应用入口 + 生命周期（自动启动引擎）
│   │   ├── config_service.py    # 运行时配置服务（RuntimeConfig 覆盖）
│   │   ├── engine_runner.py     # 引擎线程管理 + 缓存 + 价格轮询
│   │   ├── web_manager.py       # WebSocket 连接管理
│   │   ├── log_service.py       # 日志捕获服务
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
│   │       ├── data.py          # /api/data
│   │       └── backtest.py      # /api/backtest
│   └── frontend/                # Vue 3 前端
│       └── src/
│           ├── views/           # 页面视图
│           │   ├── DashboardView.vue      # 交易终端（内含K线+持仓+策略逻辑）
│           │   ├── PositionsView.vue      # 账户持仓
│           │   ├── StrategyCenterView.vue # 策略中心
│           │   ├── TradeHistoryView.vue   # 历史成交（含废票Tab）
│           │   ├── ConfigView.vue         # 运行配置
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
└── docs/                        # 文档
```

### 连接模式

系统支持两种 MT4 连接模式（通过 `config/settings.py` 中的 `MT4_MODE` 切换）：

| 模式 | 桥接实现 | 适用场景 |
|------|---------|---------|
| `freemt4` | FreeMT4Bridge | 本地 MT4 终端，TCP Socket 直连，延迟低 |
| `metaapi` | MetaApiBridge | 云端 MT4，无需本地终端，支持 VPS（部分功能待完善） |

### 数据流

```
价格数据流:
  MT4 Tick → FreeMT4Bridge EA → Bridge Socket
    → [独立价格轮询线程 0.1s] → _cached_price (bid/ask)
    → K线缓存更新 (每 tick 1个周期, 120s 过期)
    → Dashboard WebSocket 广播 (0.3s)
    → 前端 lightweight-charts 图表渲染 (setData 每 2s)

持仓数据流:
  MT4 订单 → _tick() 主循环
    → _update_caches() (引擎线程)
    → _cached_positions (含实时盈亏重算)
    → Dashboard WebSocket 广播 (1s)
    → 前端持仓表格

信号数据流:
  _run_strategy() → 信号生成 (status=pending)
    → 开仓成功 → status=opened (含 ticket 号)
    → 开仓失败 → status=voided (含 void_reason)
    → 平仓 → status=closed (含 exit_reason)
    → signals 表持久化存储
    → Dashboard API 查询
```

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
# ⭐ 方式一（推荐）：一键启动 — 自动清理端口 + 启动后端 + 引擎
python start.py

# 方式二：直接启动后端（引擎在 lifespan 中自动启动）
python dashboard/backend/main.py

# 方式三：仅启动交易引擎（无 Web 仪表盘）
python engine_standalone/run.py
```

**start.py 工作流程：**
1. 检查旧进程（tasklist），发送 CTRL_BREAK_EVENT 优雅停止
2. 等待 3 秒，如未停止则 taskkill /F 强制终止
3. 检查端口 8000（API）/ 5173（前端）/ 23232（MT4）占用
4. 自动修复 safety_lock.txt 路径问题
5. 启动 `dashboard/backend/main.py` 子进程
6. 等待 API 就绪（`http://127.0.0.1:8000/api/engine/status`）

> **说明：** 从 v6 版本开始，`main.py` 的 FastAPI 生命周期（lifespan）自动调用 `engine_runner.start()`，无需手动调用 POST `/api/engine/start`。

### 3.4 前置检查

启动脚本 `run.py` 自动执行以下检查：
1. Python 版本 ≥ 3.10
2. 核心模块可导入
3. 配置文件有效（STRATEGY_POOL、SYMBOL、LOT_SIZE）
4. FreeMT4 EA Socket 可达（127.0.0.1:23232）
5. data/ 和 logs/ 目录存在

---

## 4. 配置指南

所有配置集中在 `config/settings.py`，支持运行时热重载（引擎每 tick 检查文件 mtime）。

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

```python
STRATEGY_POOL = {
    "M30_rsi_bb": {
        "magic": 660705,       # PP=66(自研) NN=07 VV=05
        "timeframe": "M30",
        "double_first": False,
        "max_positions": 1,
    },
    "H1_v6_hybrid": {
        "magic": 660606,       # PP=66 NN=06 VV=06
        "timeframe": "H1",
        "double_first": False,
        "max_positions": 1,
    },
    "sanqing_h1": {
        "magic": 880105,       # PP=88(借鉴) NN=01 VV=05
        "timeframe": "H1",
        "double_first": False,
        "max_positions": 1,
    },
    "gold_auto_research": {
        "magic": 880306,       # PP=88 NN=03 VV=06
        "timeframe": "H1",
        "double_first": False,
        "max_positions": 1,
    },
}
```

每个策略条目包含：
- `magic` — 唯一 Magic Number（PP+NN+VV 格式）
- `timeframe` — 策略运行周期
- `double_first` — 首单是否双倍手数（0.02）
- `max_positions` — 最大同时持仓数

### 4.4 Magic Number 规范

6 位数字：`PP` + `NN` + `VV`

| 位段 | 位数 | 含义 |
|------|------|------|
| PP   | 2    | 策略来源：`66` = 自研，`88` = 借鉴 |
| NN   | 2    | 策略上线序号（跳过 02/04/12/14/80/81/89） |
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

### 4.7 协调器配置

```python
COORDINATOR_CONFIG = {
    "enabled": False,                            # 总开关
    "cross_exit_enabled": False,                 # 功能①：跨策略联动出场
    "signal_strategy": "H1_v6_hybrid",           # 信号源策略
    "signal_direction": "BUY",                   # 信号方向
    "target_strategies": ["M30_rsi_bb", ...],    # 被影响策略列表
    "target_direction": "SELL",                  # 目标方向
    "m15_reverse_tp_enabled": False,             # 功能②：M15 反向止盈
    "m15_reverse_tp_sensitivity": 0.5,           # 斜率归一化阈值 (0.0~1.0)
}
```

### 4.8 运行时配置

通过 Web 仪表盘调整运行时配置，存储在 `runtime_config.json`（自动创建，不受引擎重启影响），支持：
- 单键或批量读取/设置/重置
- 策略池动态管理
- 协调器参数调整（覆盖 settings.py 默认值）

---

## 5. 交易引擎

交易引擎 `TradingEngine`（`engine_standalone/main.py`）是系统的核心。引擎通过非 daemon 线程运行，支持优雅关闭。

### 5.1 引擎启动流程

```
启动:
  1. connect() MT4 桥接（带 30 次重试，每次 10 秒）
  2. 启动独立价格轮询线程 (0.1s 间隔, daemon)
  3. 校准 MT4 服务器时间
  4. 初始化各策略风控状态 (StrategyRiskState)
  5. 接管现有持仓 (takeover_existing_positions)
  6. 记录起始余额
  7. 恢复遗漏历史成交 (_recover_missing_trades)
  8. 同步数据库 K 线数据完整性
  9. 写策略版本记录到数据库
  10. 进入主循环

关闭:
  1. 设置 _shutdown_requested = True
  2. 引擎线程检测标志后退出主循环
  3. 断开桥接连接
  4. 线程 join(timeout=15)
```

### 5.2 主循环流程

每 2~5 秒执行一次 `_tick()`：

```
_tick():
  1. [桥接] 心跳检测 / 断线重连
  2. [配置] 热重载（检查 settings.py mtime）
  3. [数据] 每 300 秒同步 K 线数据到 SQLite
  4. [新闻] 新闻风控处理（三级：收紧→强平→黑名单）
  5. [出场] 出场检查（每个策略的 check_ema20_exit）
  6. [协调] 协调器出场联动（cross_exit + M15 reverse TP）
  7. [风控] 更新浮动盈亏
  8. [风控] 全局硬止损检查（12%）
  9. [风控] 新闻黑名单检查
  10. [风控] 安全锁检查
  11. [风控] 各策略阻断状态检查
  12. [入场] 入场评估（通过所有检查的策略）

  后台任务（每 tick 执行 1 项）:
  - K 线缓存刷新（1 个周期/次，优先级 H1>M30>M15>M5>H4>D1>W1>M1）
  - 遗漏持仓恢复（检测到持仓数下降时）
```

### 5.3 入场流程

```
入场（每个策略独立）:
  1. 检查策略是否被阻断
  2. 双重确认持仓数（桥接查询 + 本地 _known_position_count）
  3. 检查 max_positions 上限
  4. 检查持仓位门控（策略文件内实现）
  5. 调用 strategy.on_tick() 生成信号
  6. 记录信号到数据库（status=pending）
  7. 执行 open_order()
  8. 开仓成功 → 更新信号 status=opened + 记录 ticket
  9. 开仓失败 → 更新信号 status=voided + 记录 void_reason（如 "资金不足"）
```

### 5.4 出场流程

```
出场（每个策略的每个持仓独立）:
  1. 调用 strategy.check_ema20_exit()
  2. 如触发出场 → 记录 exit_reason（"利润回撤止盈"/"ATR移动止盈"/"ATR硬止损"）
  3. 执行 close_order()
  4. 记录成交到数据库 insert_trade()
  5. 更新信号 status=closed + exit_reason
  6. 更新策略风控状态（realized_pnl、consecutive_losses 等）
  7. 同步 _known_position_count（立即检测持仓数下降）

出场也通过以下途径触发:
  - 引擎 _run_exits() 主循环
  - _handle_news_risk() 新闻强平
  - 协调器 cross_exit / M15 reverse TP
  - 手动平仓 API
```

### 5.5 三层退出体系

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

### 5.6 独立价格轮询线程

引擎启动时创建独立 daemon 线程，每 0.1 秒采样一次 MT4 价格：

- **目的**：不受 _tick() 主循环阻塞（新闻黑名单期间 _tick 会 sleep 60 秒）
- **缓存位置**：`EngineRunner._cached_price`（bid/ask 字典）
- **数据流向**：价格 → Dashboard WebSocket (0.3s) → 前端实时显示
- **PnL 重算**：`_fresh_positions()` 用最新 bid/ask 实时重算持仓盈亏

### 5.7 K 线实时缓存

`EngineRunner._cached_candles` 维护所有周期的 K 线缓存：

- **刷新策略**：每 tick 最多刷新 1 个周期（优先级 H1 > M30 > M15 > M5 > H4 > D1 > W1 > M1）
- **过期时间**：同一周期两次刷新间隔 ≥ 120 秒
- **实时扩展**：最后一根 K 线的 `high/low/close` 用当前中间价 `(bid+ask)/2` 实时扩展
- **API 暴露**：`/api/market/candles` 从缓存读取（后端 `routes/market.py`）
- **前端渲染**：`TradingTerminal.vue` 每 2 秒调用 `setData()` 刷新

### 5.8 交易同步（Trade Sync）

三层检测机制确保 MT4 持仓与数据库记录一致：

| 层级 | 检测方式 | 触发条件 | 动作 |
|------|---------|---------|------|
| L1 | `_run_exits()` 对比 `_known_position_count` | 持仓数下降 | 立即调用 `_recover_missing_trades()` |
| L2 | `_check_trade_sync()` | 每 3600 秒 | 对比 MT4 持仓数 vs DB 记录数 |
| L3 | `_recover_missing_trades()` | L1/L2 触发 | 遍历 MT4 持仓，找回 DB 缺失的记录 |

### 5.9 动态策略管理

引擎支持运行时动态添加/移除策略：

```python
# 添加策略（由 POST /api/engine/strategies/add 触发）
engine.add_strategy("new_strategy", {"magic": 660800, "timeframe": "H1", ...})

# 移除策略（由 POST /api/engine/strategies/remove 触发）
engine.remove_strategy("new_strategy", close_positions=True)
```

### 5.10 优雅关闭

引擎支持两种关闭方式：
1. **start.py 发送 CTRL_BREAK_EVENT** → 引擎线程设置 `_shutdown_requested` → 退出主循环 → 断开桥接
2. **API POST /api/engine/stop** → 同上的关闭流程

关闭过程中 `close_order()` 不会被中断，确保已执行的平仓操作正确记录。

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
    def indicator_values(self) -> dict: ...
```

### 6.2 策略文件版本字段

每个策略文件顶部包含版本信息：

```python
STRATEGY_VERSION = "v5"          # 当前版本号
STRATEGY_MAGIC = 660705          # 当前 Magic Number
STRATEGY_CHANGELOG = [           # 版本历史列表
    {"version": "v1", "magic": 660701, "date": "2026-06-08", "desc": "初始上线"},
    {"version": "v2", "magic": 660702, "date": "2026-06-08", "desc": "修复出场逻辑"},
    ...
]
```

### 6.3 持仓位门控（Position Gate）

所有活跃策略均实现持仓位门控（v5/v6 新增）：

- **60 根 K 线价格区间**：计算最近 60 根 K 线的 `recent_high` 和 `recent_low`
- **底部 10%（价格 ≤ low + range × 0.1）**：
  - `SAFE_DN = False`，禁止开空
  - 空头信号扣 2 分（或直接返回 None）
- **顶部 10%（价格 ≥ high - range × 0.1）**：
  - `SAFE_UP = False`，禁止开多
  - 多头信号扣 2 分
- **M30 趋势门控**：当 M30 EMA20 方向与 SMA200 冲突时，加严 1 分

门控值 `price_position`、`recent_high`、`recent_low` 通过 `indicator_values()` 返回，在信号详情中展示。

### 6.4 活跃策略一览

| 策略 | 周期 | Magic | 版本 | 入场方式 | 关键指标 |
|------|------|-------|------|---------|---------|
| M30_rsi_bb | M30 | 660705 | v5 | 5因子评分≥3 + H1趋势门控 | RSI, BB, ATR, SMA200 |
| H1_v6_hybrid | H1 | 660606 | v6 | 8因子评分≥3 + 持仓位门控 | KDJ, BB, KC, MACD, RSI |
| sanqing_h1 | H1 | 880105 | v4 | 6因子评分≥5 + 持仓位门控 | EMA9/21, ATR, Volume |
| gold_auto_research | H1 | 880306 | v6 | 4因子共识（全票通过）+ 持仓位门控 | EMA, MACD, ADX, RSI, BB |

各策略完整文档见 `docs/strategies/`，版本历史见 `strategies/STRATEGY_VERSIONING.md`。

---

## 7. 风控体系

系统实现十层风控，覆盖全局、策略、订单三个级别：

### 7.1 阻断层级

```
级别 1 — 全局硬止损（基于结算余额 12%）
  触发 → 所有策略阻断，直到手动恢复

级别 2 — 新闻黑名单
  触发 → 所有策略阻断（事件前 30 分钟到后 120 分钟）

级别 3 — 安全锁
  触发 → 所有策略阻断（4 小时自动过期）
  触发条件: 平仓持仓 < 30 秒且亏损

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

### 7.2 安全锁机制

当引擎检测到平仓持仓时间 < 30 秒且亏损时，自动触发安全锁：

1. 写入 `config/safety_lock.txt`（文件内容为触发时间戳）
2. 所有策略阻断 4 小时（`SAFETY_LOCK_TIMEOUT_MINUTES = 240`）
3. 阻断自动过期（引擎每 tick 检查文件中的时间戳）
4. **注意**：安全锁文件路径在 `config/` 目录下，引擎通过 `os.path.dirname()` 计算

### 7.3 风控状态追踪

每个策略（按 Magic Number）维护独立的风控状态：

```python
StrategyRiskState:
    realized_pnl: float           # 累计已实现盈亏
    floating_pnl: float           # 当前浮动盈亏
    exit_timestamps: deque        # 出场时间戳队列（快速出场检测用）
    realized_loss_blocked: bool   # 已实现亏损阻断
    floating_loss_blocked: bool   # 浮动亏损阻断
    rapid_exit_blocked: bool      # 快速出场阻断
    consecutive_losses: int       # 连续亏损计数
    realized_loss_amount_blocked: bool  # 亏损金额阻断
```

---

## 8. 多策略协调器

协调器是引擎的可选功能模块（`COORDINATOR_CONFIG`），提供两种策略间联动逻辑。

### 8.1 功能①：跨策略联动出场

当信号策略的特定方向持仓盈利时，自动平掉目标策略的对应方向盈利单。

```
配置:
  signal_strategy: "H1_v6_hybrid"     # 信号源
  signal_direction: "BUY"             # 信号方向（BUY/SELL）
  target_strategies: ["M30_rsi_bb"]   # 目标策略列表
  target_direction: "SELL"            # 平仓方向

触发条件:
  1. 信号策略 signal_direction 方向的持仓 profit > 0
  2. 目标策略 target_direction 方向的持仓 profit > 0

动作:
  关闭所有目标策略中 target_direction 方向的盈利持仓
  ↓
  记录出场原因: "cross_exit"
```

### 8.2 功能②：M15 反向止盈

当 M15 EMA20 斜率反转时（趋势可能转变），平掉所有原方向盈利单。

```
触发条件:
  1. M15 周期已收盘的 3 根 K 线
  2. 计算 EMA20 斜率 = (ema[0] - ema[-3]) / 3
  3. 斜率归一化判定:

     计算 ATR14 = 最近 14 根 K 线平均真实波幅
     if sensitivity > 0:
       trend_up   = ema_slope >  ATR14 * sensitivity
       trend_down = ema_slope < -ATR14 * sensitivity
     else:
       # 原版逻辑：斜率 > 0 即为上涨
       trend_up   = ema_slope > 0
       trend_down = ema_slope < 0

  4. 原有多头仓位且 trend_down → 平所有多头盈利单
  5. 原有空头仓位且 trend_up   → 平所有空头盈利单

灵敏度(sensitivity) 对应触发率:
  0.0 = 关闭归一化（原版敏感逻辑）
  0.1 = 触发率 ~82%   0.5 = 触发率 ~25%（推荐）
  0.3 = 触发率 ~50%   0.8 = 触发率 ~10%
  1.0 = 触发率 ~2%
```

> **为什么移除 M5：** M5 周期过于敏感，在 H1 主趋势下频繁产生反向信号。M15 的 EMA20 斜率/ATR 归一化后更适合作为趋势反转参考。

### 8.3 运行时配置

协调器参数可通过 `POST /api/config/coordinator` 运行时调整，覆盖 settings.py 默认值。调整后的配置持久化到 `runtime_config.json`。

---

## 9. 信号生命周期

信号系统记录了从策略生成信号到持仓平仓的完整链路，存入 `signals` 表。

### 9.1 状态流转

```
                    策略 on_tick() 生成信号
                            │
                      status=pending
                     （记录信号原因、因子评分）
                      ┌────┴────┐
                      │         │
                  开仓成功   开仓失败
                      │         │
               status=opened  status=voided
               （记录 ticket） （记录 void_reason）
                      │
                   平仓触发
                      │
               status=closed
              （记录 exit_reason、
               realized_pnl）
```

### 9.2 信号字段

```python
signals 表:
    id              INTEGER PRIMARY KEY   # 自增 ID
    strategy        TEXT                  # 策略名称
    direction       TEXT                  # BUY/SELL
    price           REAL                  # 信号生成时的价格
    status          TEXT                  # pending/opened/closed/voided
    signal_reason   TEXT                  # 开仓信号原因（JSON，含因子评分）
    entry_analysis  TEXT                  # 入场分析（JSON，含指标快照）
    exit_reason     TEXT                  # 出场原因
    exit_analysis   TEXT                  # 出场分析（JSON，含退出逻辑名）
    void_reason     TEXT                  # 废票原因
    ticket          INTEGER               # MT4 订单号（opened/closed 时有值）
    magic           INTEGER               # 策略 Magic Number
    position_time   TEXT                  # 开仓时间（ISO 格式）
    close_time      TEXT                  # 平仓时间
    realized_pnl    REAL                  # 已实现盈亏
    created_at      TIMESTAMP             # 记录创建时间
```

### 9.3 废票（Voided Trades）

信号生成后开仓失败 → 标记为 `voided`。常见废票原因：
- **funds_slippage**：资金不足或滑点超限
- **market_closed**：市场已关闭
- **timeout**：价格确认超时
- **升级前记录**：信号系统上线前产生的历史记录（v6 升级时自动标记）

废票在 Dashboard 历史成交页面的独立 Tab 中展示，包含信号原因和指标快照。

### 9.4 出场原因

平仓信号的 `exit_reason` 记录了具体的出场逻辑，包括：
- **利润回撤止盈**：`profit_drawdown_pct=X%`
- **ATR 移动止盈**：`trail_stop=ATR*1.0`
- **ATR 硬止损**：`hard_stop=ATR*2.0`
- **新闻强平**：`news_force_close`
- **跨策略联动**：`cross_exit`
- **M15 反向止盈**：`m15_reverse_tp`
- **手动平仓**：`manual_close`

### 9.5 API 查询

```
GET /api/signals
  ?strategy=M30_rsi_bb      # 按策略过滤
  &direction=BUY            # 按方向过滤
  &status=opened            # 按状态过滤（pending/opened/closed/voided）
  &limit=50                 # 返回条数
  &offset=0                 # 分页偏移

GET /api/signals/{id}       # 单条信号详情

GET /api/trades/{ticket}/analysis  # 单笔成交分析（含入场/出场因子）
```

---

## 10. 新闻过滤

### 10.1 数据源

- **来源：** ForexFactory 本周日历（`https://nfs.faireconomy.media/ff_calendar_thisweek.json`）
- **缓存：** 内存缓存，1 小时 TTL
- **过滤：** USD、High Impact 事件

### 10.2 三级防护时间线

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

### 10.3 新闻影响模式

| 阶段 | 时间窗口 | 操作 |
|------|---------|------|
| 收紧 | 事件前 120 分钟 → 前 15 分钟 | trail_mult=0.5, hard_mult=1.0 |
| 强平 | 事件前 15 分钟 → 事件开始 | 平所有持仓 |
| 黑名单 | 事件前 30 分钟 → 后 120 分钟 | 禁止任何新开仓 |

---

## 11. 策略版本管理

### 11.1 规范文件

策略版本管理规范见 `strategies/STRATEGY_VERSIONING.md`，包含：
- Magic Number 编号规则（PP+NN+VV）
- 完整对照表和版本历史
- 修改策略的标准流程
- STRATEGY_CHANGELOG 格式规范
- backup/ 文件命名规范

### 11.2 数据库版本记录

引擎启动时自动将各策略的 STRATEGY_CHANGELOG 写入 `strategy_versions` 表：

```sql
CREATE TABLE strategy_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    magic INTEGER NOT NULL,
    version TEXT NOT NULL,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 11.3 修改策略的标准流程

1. **备份当前文件** → `strategies/backup/YYYYMMDD_策略文件名_版本号.py`
2. **修改策略逻辑**
3. **更新版本字段**：`STRATEGY_VERSION`、`STRATEGY_MAGIC`、`STRATEGY_CHANGELOG`
4. **更新** `config/settings.py`：STRATEGY_POOL 中对应策略的 magic
5. **重启引擎**，引擎自动将 changelog 写入数据库

### 11.4 兼容旧版 Magic

历史遗留的 777xxx 系列 magic 仍受支持，在统计分组中自动合并：

| 旧 Magic | 策略 |
|----------|------|
| 777001 | M30_rsi_bb |
| 777002 | H1_v6_hybrid |
| 777003 | gold_auto_research |

---

## 12. Web 仪表盘

### 12.1 技术栈

| 层 | 技术 | 端口 |
|----|------|------|
| 后端 | Python FastAPI + WebSocket | 8000 |
| 前端 | Vue 3 + TypeScript + Vite + Naive UI | 5173 |
| 图表 | lightweight-charts（TradingView 风格的金融图表） | — |

### 12.2 启动方式

```bash
# 方式一：一键启动（推荐）
python start.py

# 方式二：独立启动
python -m dashboard.backend.main
# 前端分离启动
cd dashboard/frontend && npm run dev
```

### 12.3 界面导航

左侧菜单栏 7 个页面：

| 页面 | 路由 | 功能 |
|------|------|------|
| 交易终端 | `/` | 实时价格图表、持仓列表、策略逻辑面板 |
| 账户持仓 | `/positions` | 当前持仓列表（可展开查看详情）、平仓/修改 |
| 策略中心 | `/strategies` | 策略运行状态、信号查看、雷达评分图 |
| 监控告警 | `/patrol` | 巡检报告、异常通知 |
| 历史成交 | `/trades` | 已平仓记录（含废票 Tab）、按策略统计（版本子分组） |
| 运行配置 | `/config` | 运行时参数调整、策略池、协调器 |
| 系统日志 | `/logs` | 实时日志查看、级别过滤 |

### 12.4 关键前端特性

**交易终端：**
- 左侧：lightweight-charts 实时 K 线图（2 秒刷新，使用缓存数据）
- 右侧：策略逻辑双栏面板（绿=多头、红=空头），每策略显示入场条件、出场条件、当前指标值
- 底部：当前持仓列表（可展开查看入场分析）

**K 线实时更新：**
- 后端缓存最后一根 K 线用当前中间价 `(bid+ask)/2` 扩展 high/low/close
- 前端每 2 秒调用 `setData()` 刷新图表
- 自动滚动到最新 K 线（`scrollToRealTime()`），暂停交互后自动恢复

**历史成交：**
- 策略统计大表格，主行显示 4 位 Magic（如 `6607`），可展开查看各版本子行（如 `660704`）
- 独立废票 Tab：显示所有 voided 信号，含信号原因和指标快照

**持仓表格：**
- 可展开行：显示入场分析、因子评分、指标快照
- 实时盈亏：通过 `_fresh_positions()` 用最新 bid/ask 重算

### 12.5 REST API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/engine/status` | GET | 引擎状态 |
| `/api/engine/health` | GET | 综合健康检查（GREEN/YELLOW/RED） |
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
| `/api/market/candles` | GET | K 线数据（从缓存读取） |
| `/api/logs` | GET | 日志查询 |
| `/api/news` | GET | 财经事件 |
| `/api/trades/history` | GET | 历史成交 |
| `/api/trades/stats` | GET | 交易统计（含版本子分组） |
| `/api/trades/{ticket}/analysis` | GET | 单笔交易分析 |
| `/api/signals` | GET | 信号列表（按状态/策略/方向过滤） |
| `/api/signals/{id}` | GET | 单条信号详情 |
| `/api/data/status` | GET | 数据库状态 |
| `/api/data/download` | POST | 触发数据下载 |

### 12.6 WebSocket 推送

连接 `/ws` 端点，通过频道消息实时推送：

| 频道 | 频率 | 数据 |
|------|------|------|
| `prices` | 0.3 秒 | bid, ask, spread |
| `positions` | 1 秒 | 持仓列表（含实时盈亏重算） |
| `account` | 10 秒 | 账户信息 |
| `logs` | 1 秒 | 新日志 |
| `status` | 15 秒 | 引擎状态 |

### 12.7 健康检查指标

`GET /api/engine/health` 返回综合健康状态：

- **GREEN** — 全部正常
- **YELLOW** — 桥接断开/引擎停止
- **RED** — 全局亏损阻断/高亏损

### 12.8 协调器配置界面

在 `/config` 页面的协调器配置面板中，支持：

- **功能①：跨策略联动出场**
  - 启用开关、信号策略选择、信号方向、受影响策略（多选）、目标方向
  - 配置后实时显示规则说明

- **功能②：M15 反向止盈**
  - 启用开关、灵敏度下拉选择（0~1.0，含对应触发率百分比）
  - 原版逻辑（sensitivity=0）作为开关的独立选项

---

## 13. 监控守护进程

### 13.1 概述

`monitor/patrol_daemon.py` 是一个独立进程，不依赖引擎代码，只通过 REST API 通信。每 30 秒巡检一次。

### 13.2 巡检项目

1. **引擎状态** — 调用 `/api/engine/status`，异常则弹窗告警
2. **价格监控** — 检查价格偏离参考价超过 20 点
3. **持仓变化** — 检测新开仓、平仓，监控特定止损位
4. **亏损分析** — 检测新平仓记录，自动分析亏损单原因和建议
5. **错误日志** — 报告 ERROR 级日志

### 13.3 告警方式

- **关键告警：** Windows MessageBox 弹窗（PowerShell）
- **一般通知：** 日志记录

### 13.4 启动

```bash
python monitor/patrol_daemon.py
```

### 13.5 状态文件

位置：`monitor/.patrol_state.json`
记录：持仓列表、引擎状态、已触发告警、已分析亏损单

---

## 14. 数据管理

### 14.1 SQLite 数据库

**文件：** `data/market_data.db`

**核心表：**
```sql
-- K 线数据
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

-- 信号生命周期
CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT,
    direction TEXT,
    price REAL,
    status TEXT DEFAULT 'pending',
    signal_reason TEXT,
    entry_analysis TEXT,
    exit_reason TEXT,
    exit_analysis TEXT,
    void_reason TEXT,
    ticket INTEGER,
    magic INTEGER,
    position_time TEXT,
    close_time TEXT,
    realized_pnl REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 策略版本历史
CREATE TABLE strategy_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    magic INTEGER NOT NULL,
    version TEXT NOT NULL,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**支持的周期：** M1, M5, M15, M30, H1, H4, D1, W1

### 14.2 数据下载

三种模式：
1. **增量同步** — `download_timeframe()`，检查最新时间戳，只补充缺失数据
2. **全量回填** — `download_timeframe_paged()`，分页从最新回填到 2024-01-01
3. **全周期下载** — `download_all_paged()`，依次下载 M15/H1/H4/D1

引擎启动时自动检查各活跃策略周期的数据完整性，缺口超过 3 根 K 线时自动下载补漏。

### 14.3 数据库恢复脚本

| 脚本 | 功能 |
|------|------|
| `scripts/extract_trades.py` | 从 GBK 编码日志文件提取历史成交 |
| `scripts/recover_trades.py` | 通过 MT4 桥接恢复历史订单 |

---

## 15. 回测系统

### 15.1 回测框架

三种回测方式：

| 方式 | 框架 | 特点 |
|------|------|------|
| 数据库回测 | 纯 Pandas | 直接从 market_data.db 读取数据，计算指标，逐根遍历 |
| Backtrader 回测 | Backtrader | 标准回测框架，支持参数优化 |
| 纯 Pandas 回测 | Pandas | 简单策略快速验证 |

### 15.2 关键回测脚本

| 脚本 | 说明 |
|------|------|
| `db_backtest_v6.py` | V6 Hybrid 策略数据库回测 |
| `db_backtest_7strategies.py` | 7 种策略同数据对比 |
| `db_backtest_mtf.py` | 多周期回测 |
| `backtest_optimization.py` | Backtrader 参数优化 |
| `backtest_cross_timeframe.py` | 跨周期对比 |
| `m30_rsi_optimize.py` | M30 RSI 参数扫描 |
| `v6_live_backtest.py` | 实盘数据回测 |

### 15.3 回测指标

遵循 MT4 Strategy Tester 标准报表格式：

- **核心盈亏：** 总净盈亏、毛利、毛损、Profit Factor、Expected Payoff
- **交易统计：** 总次数、多空分布、胜率、最大/平均单笔盈亏
- **持仓时间：** 平均持仓时间
- **连损连盈：** 最大连续亏损/盈利次数和金额
- **回撤：**（待实现基于 equity 曲线的回撤计算）

---

## 16. 工具集

| 工具 | 文件 | 功能 |
|------|------|------|
| 一键启动 | `start.py` | 端口清理+后端+引擎 |
| 环境检查 | `tools/check_setup.py` | 检查 Python/依赖/MT4/端口 |
| 终端监控 | `tools/monitor.py` | 控制台实时仪表盘 |
| 账户信息 | `tools/account_info.py` | 查看账户详情 |
| 调整止损 | `tools/adjust_sl.py` | 修改持仓止损 |
| 远置止盈 | `tools/adjust_tp_far.py` | 将止盈移至远处 |
| 平盈利单 | `tools/close_profitable.py` | 仅平盈利持仓 |
| 参数扫描 | `tools/parameter_scan.py` | V6 Hybrid 参数网格搜索 |
| 模型训练 | `tools/train_xaubot.py` | ML 模型训练（预留） |

---

## 17. 故障排除

### 17.1 引擎无法启动

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| Socket 连接失败 | MT4 未运行/EA 未加载 | 检查 MT4 终端，确保 EA 已加载 |
| 配置文件错误 | settings.py 语法错误 | 检查配置文件，确认 STRATEGY_POOL 有效 |
| 端口被占用 | 旧进程残留 | 运行 `python start.py` 自动清理或手动 taskkill |
| K 线缓存为空 | 桥接未就绪/MT4 未同步 | 查看日志，等待 MT4 数据同步 |

### 17.2 桥接连断开

```
检查步骤：
1. MT4 终端是否运行
2. FreeMT4Bridge EA 是否在图表上
3. EA 自动交易是否启用
4. 端口 23232 是否可达
```

### 17.3 持仓不同步

当引擎重启后 MT4 持仓与数据库记录不一致时：
1. 引擎自动调用 `_recover_missing_trades()` 恢复
2. 可通过 `_check_trade_sync()` 手动触发同步
3. 如问题持续，检查日志中的 trade_sync 警告

### 17.4 K 线不更新

| 问题 | 可能原因 | 解决方案 |
|------|---------|---------|
| K 线不实时 | 缓存过期/桥接阻塞 | 检查独立价格轮询线程是否运行 |
| 价格不刷新 | WebSocket 断连 | 刷新浏览器页面 |
| 图表不滚动 | autoScroll 未触发 | 点击图表区域重新激活自动滚动 |

### 17.5 安全锁误触发

安全锁文件位置：`config/safety_lock.txt`
- 如发现策略全部被阻断，首先检查该文件是否存在
- 删除文件即可手动解除安全锁
- 安全锁自动过期时间：240 分钟（`SAFETY_LOCK_TIMEOUT_MINUTES`）

### 17.6 数据库问题

| 问题 | 解决方案 |
|------|---------|
| 数据为空 | 调用 `/api/data/download` 或运行 `data/downloader.py` |
| 数据不完整 | 运行 `download_all_paged()` 全量回填 |
| 数据库锁定 | 检查是否有其他进程占用，SQLite 使用 WAL 模式 |

### 17.7 日志重复

重启仪表盘后端时需确保旧进程已终止：
```bash
# 检查旧进程
tasklist | findstr python
# 强制终止
taskkill /F /PID <pid>
```
