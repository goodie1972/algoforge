# XAUUSD 量化交易系统 v2.8.0 — CLAUDE.md

## 项目

XAUUSD 黄金自动化交易系统，基于 Python + MetaTrader 4。

- **入口:** `start.py`（一键启动）或 `dashboard/backend/main.py`（仅后端）
- **技术栈:** Python 3.10+ / FastAPI / Vue 3 + TypeScript + Vite + Naive UI / SQLite / lightweight-charts
- **桥接:** FreeMT4Bridge EA (MQL4, TCP Socket :23232) 或 MetaApi 云端
- **数据库:** `data/market_data.db` (SQLite, 含 ohlcv / trades / signals 表)
- **版本:** 3.4.0 (VERSION)
- **策略仓库:** [algoforge-strategies](https://github.com/goodie1972/algoforge-strategies.git)

## 仓库结构

```
xauusd/                    # 系统代码（algoforge）
├── config/                # 配置 (settings.py, runtime_config.py)
├── core/                  # 桥接层 (bridge.py, freemt4_bridge.py, metaapi_bridge.py, paper_bridge.py)
├── services/              # 服务层 (data_factory.py, news_filter.py, huicong_news.py, llm_provider.py, supervisor.py)
├── engine_standalone/     # 引擎主循环 (main.py, athlete.py, run.py)
├── dashboard/             # Web 管理面板
│   ├── backend/           #   FastAPI 后端 (main.py, routes/, engine_runner.py)
│   └── frontend/          #   Vue 3 前端 (src/, vite.config.ts)
├── data/                  # 数据库 (market_data.db) + database.py
├── tools/                 # 独立工具 (监控/纸面/分析/信号记录)
├── backtest/              # 回测脚本
├── docs/                  # 系统文档 (data_factory.md, product_manual.md)
├── logs/                  # 运行日志
├── start.py               # 一键启动入口
└── start.bat              # Windows 菜单启动
```

**策略文件在主仓库 `strategies/` 目录中（普通目录，非 submodule）：**
- 策略文件 → `strategies/YYYYMMDD_name_vN.py`
- 策略说明 → `strategies/docs/strategies/{name}.md`
- 基类 → `strategies/base.py`
- 扫描器 → `strategies/scanner.py`（自动发现策略类）
- 命名规范 → `strategies/STRATEGY_VERSIONING.md`
- 策略手册 → `strategies/strategy_manual.md`
- 历史备份 → `strategies/backup/`
- 开发指南 → `docs/strategy_dev_guide.md`

## 三轨架构

- **轨1: DataFactory** — `services/data_factory.py` 独立线程，增量拉取K线；指标以 MT4 F043(EA) 直供为优先、TA-Lib 本地计算回退（v3 起 EA 掉线超 30s 自动回退）
- **轨2: 策略员** — 主引擎循环，`get_indicator(key)` 读缓存指标，评分达标出门票（候选信号）
- **轨3: 运动员** — `engine_standalone/athlete.py` tick验证层，调用 `_verify_entry` 实时重算入场条件，10秒过期作废

## 通用指标缓存 (DataFactory)

> 完整 46 键权威来源表（EA 直供 / EA派生 / TA‑Lib 逐字段对照、勘误、F043 协议细节）见 `docs/data_factory.md`

DataFactory 是**所有策略指标的唯一数据来源**。三层数据源（优先级从高到低）：
1. **MT4 F043 命令**（EA 直供）— 与 MT4 图表完全一致，优先采用
2. **TA‑Lib 本地计算**（`_ta_only_indicators()`）— 首次加载 / EA 掉线超 30s 时回退
3. **SQLite 数据库** — 启动恢复 + 桥接数据不足时补充历史 K 线

**v3 回退保护（关键）**：`_sync_tf` 仅当 EA 在 `_EA_PROVIDED_TTL`（30 秒）内确实提供过某键时才保护该 EA 值不被 TA‑Lib 覆盖。EA 正常在线受保护；EA 掉线 >30s 自动回退 TA‑Lib 实时值；缓存中尚无该键时直接取 TA‑Lib 值。

**指标按来源分三类（共 46 键）：**
- **EA 直供（24）**：`close`、`rsi`/`rsi_5`/`rsi_10`、`mfi`、`bb`、`ema_9`/`ema_21`/`ema_34`/`ema_50`/`ema_200`、`sma_14`/`sma_20`/`sma_50`、`atr`/`atr_20`、`adx`/`pdi`/`ndi`、`macd`、`stoch_5_3_3`、`linear_reg_slope`、`volume_sma_20`、`cci`
- **EA 值本地派算（2）**：`bb_width`（由 `bb` 算）、`cci_direction`（当前 vs 前一根 CCI）
- **仅 TA‑Lib 计算（20）**：`stoch_14_3_3`、`stoch_rsi`、`stoch_k_prev`/`stoch_d_prev`、`bbi`、`roc_10`、`trend`、`price_position`、`rsi_dir_3bar`、`mfi_direction`/`mfi_dir_50`、`bb_width_direction`/`bb_width_ratio`/`bb_mid_direction`、`atr_list_val`/`atr_ma_5`/`atr_sma20`/`atr_ratio_30`、`candle_pattern_dir`/`candle_pattern_name`

> ⚠️ 蜡烛形态**没有** `cdl_*` 逐形态键，应读 `candle_pattern_dir` + `candle_pattern_name`；`stoch_rsi` 与蜡烛形态仅由 TA‑Lib 计算（MQL4 无内置）。

## 时区规则 (CRITICAL)

- **用户期望的本地时间：UTC+8**
- 系统服务器时区：UTC+8（与本地一致）
- MT4 服务器时区：UTC+3（夏令时）

**绝对规则：** 任何时间显示，禁止裸用 `datetime.fromtimestamp(ts)`。必须使用 `config.settings.LOCAL_TZ`（UTC+8）的 timezone-aware 调用：
```python
from config.settings import LOCAL_TZ
datetime.fromtimestamp(ts, tz=LOCAL_TZ)
# 或使用工具函数
from config.settings import dt_local
dt_local(ts)
```

**数据存储说明：**
- `ohlcv` 表的 `timestamp` 列：MT4 服务器时间（UTC+3），存储为 Unix 整数。
- `trades` 表的 `open_time / close_time`：已由引擎 `_mt4_to_local()` 转为 UTC+8（整型存储）。
- `signals.timestamp` 及其他 `created_at / updated_at`：Python `datetime.now()` 设置，系统时区 UTC+8。

## Commands

```bash
# 一键启动（端口清理 + 后端 + 引擎）
python start.py

# 或直接启动后端（引擎在 lifespan 中自动启动）
python dashboard/backend/main.py

# 前端开发（独立启动）
cd dashboard/frontend && npm run dev

# 前端构建
cd dashboard/frontend && npm run build

# 环境检查
python tools/check_setup.py

# 纸面交易工具
python tools/paper_trader.py

# 信号分析
python tools/signal_analysis_recorder.py

# 状态监控
python tools/status_monitor.py

# 测试（少量现有）
python -m pytest tests/
```

## 其他规则

- 引擎操作：发现引擎停止后自动重启
- 提交代码前：双轮测试（编译验证 + Playwright 实际页面测试）
- 代码修改只改必要行，不添加无意义注释
- **先确认再说话**：涉及配置数据、运行时状态等事实性问题，必须先读取实际数据再回答，严禁凭记忆或猜测作答
- **版本号每次提交前更新**：小改动 +0.01，大改动 +0.1，同步更新 VERSION、package.json、CLAUDE.md、CHANGELOG.md