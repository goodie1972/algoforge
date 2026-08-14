# XAUUSD 量化交易系统 v2.8.0 — CLAUDE.md

## 项目

XAUUSD 黄金自动化交易系统，基于 Python + MetaTrader 4。

- **入口:** `start.py`（一键启动）或 `dashboard/backend/main.py`（仅后端）
- **技术栈:** Python 3.10+ / FastAPI / Vue 3 + TypeScript + Vite + Naive UI / SQLite / lightweight-charts
- **桥接:** FreeMT4Bridge EA (MQL4, TCP Socket :23232) 或 MetaApi 云端
- **数据库:** `data/market_data.db` (SQLite, 含 ohlcv / trades / signals 表)
- **版本:** 2.9.0 (VERSION)
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

**策略文件已分离到独立仓库：** `https://github.com/goodie1972/algoforge-strategies.git`
- 策略文件 → `strategies/YYYYMMDD_name_vN.py`
- 策略说明 → `docs/strategies/{name}.md`
- 开发指南 → `docs/strategy_dev_guide.md`

## 三轨架构

- **轨1: DataFactory** — `services/data_factory.py` 独立线程，双桥接(exec+data)，增量拉取K线，TA-Lib统一计算指标
- **轨2: 策略员** — 主引擎循环，`get_indicator(key)` 读缓存指标，评分达标出门票（候选信号）
- **轨3: 运动员** — `engine_standalone/athlete.py` tick验证层，调用 `_verify_entry` 实时重算入场条件，10秒过期作废

## 通用指标缓存 (DataFactory)

> 详见 `docs/data_factory.md`

DataFactory 是**所有策略指标的唯一数据来源**。两层数据源：
1. **F043 命令**：从 MT4 EA 直接获取指标值（优先，与 MT4 图表一致）
2. **TA-Lib 本地计算**：`_talib_indicators()` 回退计算（首次加载 / F043 失败时）

### 完整指标表（26 个）

| key | 类型 | 参数 | 说明 |
|:----|:----|:----|:----|
| `close` | float | — | 最新收盘价 |
| `trend` | str | SMA14 | `"UP"` / `"DOWN"` |
| `rsi` | float | 14 | RSI |
| `rsi_5` | float | 5 | 快速 RSI |
| `rsi_10` | float | 10 | 中速 RSI |
| `mfi` | float | 14 | 资金流量指数 |
| `mfi_direction` | str | — | `"up"` / `"down"` / `"flat"` |
| `bb` | dict | 20,2,2 | `{"upper": f, "mid": f, "lower": f}` |
| `bb_width` | float | — | BB 带宽 = upper − lower |
| `bb_width_direction` | str | — | 带宽方向 |
| `bb_width_ratio` | float | SMA3 | 当前带宽 / 近 3 根均值 |
| `ema_9` | float | 9 | 指数移动平均 |
| `ema_21` | float | 21 | 指数移动平均 |
| `sma_14` | float | 14 | 简单移动平均 |
| `sma_20` | float | 20 | 简单移动平均 |
| `sma_50` | float | 50 | 简单移动平均 |
| `atr` | float | 14 | 平均真实波幅 |
| `atr_20` | float | 20 | 平均真实波幅 |
| `atr_list` | list[float] | 14 | ATR 历史序列 |
| `adx` | float | 14 | 趋势强度 |
| `pdi` | float | 14 | +DI 多头方向 |
| `ndi` | float | 14 | −DI 空头方向 |
| `macd` | dict | 12,26,9 | `{"macd": f, "signal": f}` |
| `stoch_5_3_3` | dict | 5,3,3 | `{"k": f, "d": f}` |
| `volume_sma_20` | float | 20 | 成交量 SMA |
| `price_position` | float | 20 周期 | 价格在 20 周期高低区间的位置 0~1 |

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