# XAUUSD 量化交易系统 v2.7.4 — CLAUDE.md

## 项目

XAUUSD 黄金自动化交易系统，基于 Python + MetaTrader 4。

- **入口:** `start.py`（一键启动）或 `dashboard/backend/main.py`（仅后端）
- **技术栈:** Python 3.10+ / FastAPI / Vue 3 + TypeScript + Vite + Naive UI / SQLite / lightweight-charts
- **桥接:** FreeMT4Bridge EA (MQL4, TCP Socket :23232) 或 MetaApi 云端
- **数据库:** `data/market_data.db` (SQLite, 含 ohlcv / trades / signals 表)
- **版本:** 2.7.4 (VERSION)

## 回测系统

- **脚本:** `scripts/backtest_6months.py` — 3~6个月全策略回测
- **数据源:** 数据库 OHLCV（M15/M30/H1/H4），TA-Lib 预计算全部 26+ 指标
- **模拟:** MockBridge（模拟 MT4 桥接），可 mock datetime.now / get_cache
- **出场:** 通用逻辑（硬止损1.5×ATR + EMA21追踪 + BB中轨止盈 + 超时平仓）
- **评分:** 6维度100分制（盈利30+风控25+信号质量15+效率10+稳定性10）
- **报告:** `data/evaluation/backtest_report.json`
- **分析文档:** `docs/strategy_analysis.md` — 策略分类+组合建议+收益率分析

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

# 全策略回测
python scripts/backtest_6months.py --months=3

# 查看回测报告
python -c "import json; r=json.load(open('data/evaluation/backtest_report.json')); [print(f'{x[\"grade\"]} {x[\"name\"]:30} PnL=\${x[\"total_pnl\"]:>+7.2f} WR={x[\"win_rate\"]:>5.1f}% PF={x[\"profit_factor\"]:>.2f}') for x in r['results']]"

# 回测
python backtest/run_backtest.py

# 纸面交易工具
python tools/paper_trader.py

# 信号分析
python tools/signal_analysis_recorder.py

# 状态监控
python tools/status_monitor.py

# 周分析报告
python tools/weekly_analysis.py

# 测试（少量现有）
python -m pytest tests/
```

## 项目结构

```
xauusd/
├── config/              # 配置 (settings.py, runtime_config.py)
├── core/                # 桥接层 (bridge.py, freemt4_bridge.py, metaapi_bridge.py, paper_bridge.py)
├── services/            # 服务层 (data_factory.py, news_filter.py, huicong_news.py, llm_provider.py, supervisor.py)
├── engine_standalone/   # 引擎主循环 (main.py, athlete.py, run.py)
├── strategies/          # 策略文件 (base.py + 各策略实现)
├── dashboard/           # Web 管理面板
│   ├── backend/         #   FastAPI 后端 (main.py, routes/, engine_runner.py)
│   └── frontend/        #   Vue 3 前端 (src/, vite.config.ts)
├── data/                # 数据库 (market_data.db) + database.py
├── tools/               # 独立工具 (监控/纸面/分析/信号记录)
├── backtest/            # 回测脚本 (大量历史回测分析)
├── docs/                # 文档 (data_factory.md, product_manual.md, strategies/)
├── models/              # ML 模型 (xaubot)
├── tests/               # 测试
├── logs/                # 运行日志
├── start.py             # 一键启动入口
└── start.bat            # Windows 菜单启动
```

## 三轨架构

- **轨1: DataFactory** — `services/data_factory.py` 独立线程，双桥接(exec+data)，增量拉取K线，TA-Lib统一计算指标
- **轨2: 策略员** — 主引擎循环，`get_indicator(key)` 读缓存指标，评分达标出门票（候选信号）
- **轨3: 运动员** — `engine_standalone/athlete.py` tick验证层，调用 `_verify_entry` 实时重算入场条件，10秒过期作废

## 通用指标缓存 (DataFactory)

> 详见 `docs/data_factory.md`

DataFactory 是**所有策略指标的唯一数据来源**。两层数据源：
1. **F043 命令**：从 MT4 EA 直接获取指标值（优先，与 MT4 图表一致）
2. **TA-Lib 本地计算**：`_talib_indicators()` 回退计算（首次加载 / F043 失败时）

### 策略读取指标的方式

```python
# 本周期指标
rsi = self.get_indicator("rsi")           # → float
ema = self.get_indicator("ema_21")        # → float
stoch = self.get_indicator("stoch_5_3_3") # → {"k": float, "d": float}
bb = self.get_indicator("bb")             # → {"upper": f, "mid": f, "lower": f}
macd = self.get_indicator("macd")         # → {"macd": f, "signal": f}

# 跨周期数据
from services.data_factory import get_cache
h4 = get_cache("H4")          # → dict，含 candles + 全部 26 个指标
m30 = get_cache("M30")        # M30 周期
h4_ema = h4.get("ema_21")     # H4 的 EMA21
h4_candles = h4.get("candles", [])
```

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
# 正确
from config.settings import LOCAL_TZ
datetime.fromtimestamp(ts, tz=LOCAL_TZ)

# 或使用工具函数
from config.settings import dt_local
dt_local(ts)
```

**数据存储说明：**
- `ohlcv` 表的 `timestamp` 列：MT4 服务器时间（UTC+3），存储为 Unix 整数。读取时需用上述规则转换显示。
- `trades` 表的 `open_time / close_time`：已由引擎 `_mt4_to_local()` 转为 UTC+8（整型存储），与用户期望的 UTC+8 一致。
- `signals.timestamp` 及其他 `created_at / updated_at`：Python `datetime.now()` 设置，系统时区 UTC+8。

## 数据源铁律 (CRITICAL)

**DataFactory + TA-Lib 是唯一数据来源的充要条件。** 所有策略的指标读写必须通过 `get_indicator(key)` 访问 DataFactory 缓存。禁止：
- ❌ 禁止在策略中自算任何 TA-Lib 已提供的指标（RSI, MFI, BB, EMA, SMA, ATR, ADX, Stoch, MACD 等）
- ❌ 禁止使用 `bridge.get_candles()` 获取 K 线数据（应使用 `self.candles` 或 `get_cache(timeframe)`）
- ❌ 禁止 `_calc_ema`、`_calc_rsi`、`_calc_stoch`、`_calc_adx` 等任何自算方法

**策略编写规范：**
- ✅ 所有公共指标 → `self.get_indicator(key)` 从 DataFactory 读取
- ✅ 跨周期数据 → `from services.data_factory import get_cache` → `get_cache("H4")`
- ✅ 自定义逻辑（K线实体、评分体系等）可使用 `self.candles` 自行计算，但标准指标不得自算
- ⚡ **优先使用 TA-Lib**：任何涉及数组计算的地方（平均值、滚动窗口、标准差等），必须使用 TA-Lib 函数（SMA、STDDEV 等），禁止手动 for 循环或列表推导。如果 TA-Lib 确实无法实现，必须提前说明原因。
- 📖 指标完整列表及类型 → 见上方「通用指标缓存 (DataFactory)」表格，或 `docs/data_factory.md`
- ⚠️ **指标可能为 None**：策略必须对 `get_indicator()` 返回值做空值检查
- 🔄 **数据来源优先级**：F043 MT4 值 > TA-Lib 本地计算，策略无需关心来源，统一用 `get_indicator()` 读取

**策略文件文档标准：**
- 第 1 行：`策略显示名 — 简短描述`（用作系统 UI 的 display 字段）
- 末行：`数据源: 全部指标从 DataFactory TA-Lib 读取`
- 新增策略必须包含 `STRATEGY_VERSION`、`STRATEGY_MAGIC`、`STRATEGY_CHANGELOG`

**策略说明书标准（系统展示用 — 必需遵守）：**
- 完整规范定义文件: `docs/strategy_doc_standard.md`，含评分型/条件型/组合型/移植策略模板
- **文件名命名规则:** `docs/strategies/{策略类名}.md`，不能带版本号后缀
- **YAML frontmatter** 的 `name` 字段必须精确匹配策略类的 `name` 属性，`type` 字段标记策略类型
- **表格格式:** 入场因子表 `# | 因子 | 得分 | 说明` 四列；出场逻辑表 `# | 条件 | 说明` 三列
- **末行必须为:** `数据源: 全部指标从 DataFactory TA-Lib 读取`
- 系统 API `GET /api/strategies/{name}/logic` 从此文件读取并返回结构化 JSON 给前端展示
- 新增策略三步曲：(1) 创建策略 `.py` 文件 (2) 创建 `docs/strategies/{name}.md` (3) 注册到配置

## 策略注册流程

1. 创建策略文件到 `strategies/` 目录
2. 在 `dashboard/backend/strategy_registry.py` 注册（策略中心可见的前提）
3. 在 `engine_standalone/main.py` 的 `STRATEGY_MAP` 注册（引擎加载的前提）
4. 在 `dashboard/runtime_config.json` 的 `strategy_pool` 添加（enabled=false 默认禁用）
5. 可选：在 `config/settings.py` 的 `STRATEGY_POOL` 添加（RuntimeConfig 的回退）
6. 用户在策略中心 UI 手动启用后，重启引擎生效

## 其他规则

- 引擎操作：发现引擎停止后自动重启（参照 memory：feedback_auto_restart_engine.md）
- 提交代码前：双轮测试（编译验证 + Playwright 实际页面测试）
- 代码修改只改必要行，不添加无意义注释
