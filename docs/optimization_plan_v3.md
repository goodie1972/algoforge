# AlgoForge 系统优化方案 v3.0

> **版本**: v2.9.5 → v3.0 目标  
> **范围**: 非策略部分（后端引擎、前端界面、基础设施）  
> **创建日期**: 2026-08-14  
> **预估总工期**: 3-4 周（可并行）  
> **原则**: 每阶段完成后双轮验证（vite build + Playwright），通过后 git 提交推送

---

## 一、现状分析

### 1.1 代码规模

| 模块 | 文件 | 行数 | 状态 |
|------|------|------|------|
| 引擎核心 `engine_standalone/main.py` | 1 | 2,077 | ⚠️ 单文件过大，多职责混杂 |
| PaperBridge `core/paper_bridge.py` | 1 | 536 | ⚠️ SL/TP 模拟 + CSV 持久化 + 持仓管理混合 |
| 后端入口 `dashboard/backend/main.py` | 1 | 323 | ⚠️ 全局单例 + 手动注入 15+ 路由 |
| 后端引擎 `dashboard/backend/engine_runner.py` | 1 | 678 | 可接受，但有 sleep(3) 硬等 |
| 路由模块 `dashboard/backend/routes/` | 16 | ~6,000 | 分散，部分文件过大 (trades.py 28K) |
| 前端主图表 `TradingTerminal.vue` | 1 | 1,306 | ⚠️ 单组件承载 K线 + 9副图 + 联动 + WS |
| 前端总文件 | ~40 | ~5,300 | 类型定义分散，大量 `any` |
| **合计** | ~60 | ~17,000 | — |

### 1.2 核心痛点

| # | 痛点 | 影响 | 严重度 |
|---|------|------|--------|
| 1 | TradingTerminal.vue 1,306 行单文件 | 维护困难、HMR 慢、类型推导卡 | 🔴 高 |
| 2 | engine_standalone/main.py 2,077 行 | 修改风险高、无法单元测试 | 🔴 高 |
| 3 | 后端依赖注入靠全局变量 + 手动赋值 | 难以测试、循环依赖 | 🟡 中 |
| 4 | 数据库每次查询新建连接 | 高并发下性能差 | 🟡 中 |
| 5 | 指标计算每次全量重算 | 前端新数据时卡 45ms | 🟡 中 |
| 6 | WebSocket 广播无背压控制 | 启动/网络塞时消息堆积 | 🟡 中 |
| 7 | 日志系统无结构化、无分级存储 | 排障困难、重启丢失 | 🟢 低 |
| 8 | 配置无 schema 校验 | 修改配置可能引入运行时错误 | 🟢 低 |
| 9 | 零单元测试覆盖 | 回归风险高 | 🟢 低 |
| 10 | 前端构建单 chunk 700KB | 首屏加载慢 | 🟢 低 |

---

## 二、优化方案详述

### P0 — 高优先级（本周完成）

#### P0-1: TradingTerminal.vue 拆分

**目标**: 1,306 行 → 4 个文件，每个 ≤ 350 行

**拆分方案**:

```
dashboard/frontend/src/components/dashboard/
├── TradingTerminal.vue      # 主调度 (≤ 200 行)
│   - 布局骨架、周期切换、指标开关
│   - 加载数据、协调子组件
│
├── MainChart.vue            # 主K线图 (≤ 300 行)
│   - createChart + candleSeries
│   - 叠加指标: EMA / SMA / BB
│   - 主图十字光标事件
│
├── IndicatorPanes.vue       # 9个副图容器 (≤ 350 行)
│   - RSI / Stoch / MACD / ATR / Volume / ADX / DI / MFI / BBI
│   - 各 applyXxx() 函数
│   - paneCharts / paneSeries 生命周期
│
└── chartSync.ts             # 图表联动工具 (≤ 200 行)
    - syncAllChartsFrom()
    - attachCrosshairSync()
    - indexSeriesValues()
    - getPaneSeriesList()
    - updateCrosshairTimeLabel()
```

**数据流**:
```
TradingTerminal (props: tf, showXxx)
  ├── MainChart (emit: crosshairMove)
  └── IndicatorPanes (emit: crosshairMove)
        ↑ 共享 chartSync.ts 工具函数
```

**实施步骤**:
1. 先抽离 `chartSync.ts`（纯函数，零依赖）→ 验证 build
2. 抽离 `MainChart.vue`（K线 + overlay）→ 验证 build
3. 抽离 `IndicatorPanes.vue`（9 个副图）→ 验证 build
4. `TradingTerminal.vue` 瘦身为调度层 → 验证 build + Playwright

**验证标准**:
- `vite build` 零错误
- Playwright: 主图渲染、9 个副图可开关、十字光标联动、时间标签正确
- 文件行数: TradingTerminal ≤ 200, MainChart ≤ 300, IndicatorPanes ≤ 350

---

#### P0-2: 指标增量计算

**目标**: 前端刷新时只计算新增 K 线的指标增量，而非全量重算

**当前**:
```typescript
// 每次 fetchLatestCandles 后全量重算
function afterDataLoad() {
  applyRSI()    // calcRSI(全部2000根) ~5ms
  applyMACD()   // calcMACD(全部) ~5ms
  applyADX()    // ...
  // 9个副图 × 5ms = 45ms 主线程阻塞
}
```

**优化后**:
```typescript
// utils/indicators.ts 新增增量接口
export function calcRSIIncremental(
  prevRSI: number[],
  newCandles: CandleData[],
  period: number
): number[] {
  // 只算新增部分，拼接历史结果
}
```

**实施步骤**:
1. 在 `utils/indicators.ts` 为 RSI / MACD / ADX / Stoch / MFI / ATR 添加增量版本
2. `IndicatorPanes.vue` 缓存上一次的完整结果数组
3. 刷新时调用增量版本，只 `setData` 新增的尾部点
4. 周期切换时 fallback 到全量计算

**验证标准**:
- 2,000 根 K 线 + 9 副图：刷新耗时 45ms → ≤ 10ms
- Playwright 无 console error
- 周期切换后指标正确（全量 fallback 正常）

---

#### P0-3: WebSocket 背压控制

**目标**: 用 `asyncio.Queue` 替代固定 sleep 轮询，支持背压丢弃

**当前** (`dashboard/backend/main.py`):
```python
async def broadcast_prices():
    while PollerState.running:
        cached = engine_runner._cached_price
        if cached:
            await ws_manager.broadcast("prices", {...})
        await asyncio.sleep(0.3)  # 固定间隔，无背压
```

**优化后**:
```python
class BroadcastHub:
    """生产者-消费者模式，队列满时丢弃旧消息"""
    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}
    
    def subscribe(self, channel: str) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=50)
        self._queues[channel] = q
        return q
    
    async def publish(self, channel: str, data: any):
        q = self._queues.get(channel)
        if q and not q.full():
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass  # 丢弃，保实时性
```

**实施步骤**:
1. 新建 `dashboard/backend/broadcast_hub.py`
2. 引擎线程 → `hub.publish("prices", data)` (非阻塞)
3. 广播协程 → `await q.get()` → `ws_manager.broadcast` (消费)
4. 前端断开时自动清理队列

**验证标准**:
- 100 次 / 秒价格推送不堆积
- 客户端断开后队列不泄漏
- 重启后无残留消息

---

### P1 — 中优先级（下周完成）

#### P1-1: engine_standalone/main.py 拆分

**目标**: 2,077 行 → 5 个文件，每个 ≤ 500 行

**拆分方案**:
```
engine_standalone/
├── main.py              # 引擎类骨架 + 入口 (≤ 400 行)
├── core_loop.py         # _tick / _run 主循环 (≤ 400 行)
├── entry_exit.py        # 入场评分 + 出场检查 (≤ 500 行)
├── position_mgr.py     # 持仓管理 + takeover + 恢复 (≤ 300 行)
├── risk_mgr.py          # 风控 / SafetyLock / 冷却 (≤ 300 行)
└── events.py            # 日志 + 事件总线 (≤ 200 行)
```

**实施步骤**:
1. 先抽离 `events.py`（纯日志函数，零依赖）
2. 抽离 `risk_mgr.py`（风控逻辑独立类）
3. 抽离 `position_mgr.py`（持仓操作）
4. 抽离 `entry_exit.py`（入场/出场）
5. `main.py` 瘦身为调度 + `core_loop.py`

**风险**: 引擎核心逻辑改动有运行时风险，需逐步迁移 + 每步语法检查 + 引擎启动验证

---

#### P1-2: 后端依赖注入重构

**目标**: 用 FastAPI Depends 替代全局变量 + 手动赋值

**当前**:
```python
# main.py 头部 60 行全局实例化
config_service = RuntimeConfig()
ws_manager = WebSocketManager()
engine_runner = EngineRunner(config_service=config_service)
# 然后手动注入到 15+ 个路由模块
route_account.run_bridge = run_bridge
route_positions.run_bridge = run_bridge
```

**优化后**:
```python
# deps.py — 集中依赖容器
from functools import lru_cache

@lru_cache
def get_config() -> RuntimeConfig:
    return RuntimeConfig()

@lru_cache
def get_engine_runner() -> EngineRunner:
    return EngineRunner(config_service=get_config())

@lru_cache
def get_ws_manager() -> WebSocketManager:
    return WebSocketManager()

# 路由中使用
@router.get("/account")
async def get_account(engine: EngineRunner = Depends(get_engine_runner)):
    return engine._cached_account
```

**实施步骤**:
1. 新建 `dashboard/backend/deps.py`
2. 逐路由迁移: account → positions → trades → market → ...
3. 删除 main.py 中的全局变量和手动注入
4. 验证所有 API 端点正常

**验证标准**:
- 所有 API 端点 200
- 无循环 import
- 引擎正常启停

---

#### P1-3: 数据库连接池

**目标**: 每次查询不再新建连接

**当前**:
```python
# data/database.py
def get_connection():
    return sqlite3.connect(DB_PATH)  # 每次新建
```

**优化后**:
```python
import threading
from contextlib import contextmanager

_connection_lock = threading.Lock()
_connection = None

def get_connection():
    global _connection
    if _connection is None:
        _connection = sqlite3.connect(DB_PATH, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
    return _connection

@contextmanager
def get_db():
    with _connection_lock:
        yield _connection
```

**或升级为 aiosqlite (异步)**:
```python
import aiosqlite

async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db
```

**实施步骤**:
1. 修改 `data/database.py` 为单连接 + 线程锁
2. 所有 `get_connection()` 调用改为 `with get_db() as conn:`
3. 压测：100 并发查询无锁死
4. （可选）迁移到 aiosqlite 异步版本

---

### P2 — 低优先级（两周内持续）

#### P2-1: 结构化日志

**目标**: 用 `loguru` 替代标准 logging，支持文件轮转 + JSON 格式

**实施**:
```python
from loguru import logger

logger.add(
    "logs/app_{time:YYYY-MM-DD}.log",
    rotation="10 MB",
    retention="7 days",
    serialize=True,  # JSON 格式
    level="INFO",
)
logger.add("logs/error_{time:YYYY-MM-DD}.log", level="ERROR", rotation="5 MB")
```

**中英文双语日志模板** (`services/log_messages.py` 已有基础):
```python
LOG_MESSAGES = {
    "engine_started": {"zh": "引擎启动成功", "en": "Engine started successfully"},
    "position_closed": {"zh": "持仓已平仓 ticket={ticket}", "en": "Position closed ticket={ticket}"},
    # ...
}
```

---

#### P2-2: 配置 Schema 校验

**目标**: 用 pydantic 校验 runtime_config.json，防止配置错误

**实施**:
```python
from pydantic import BaseModel, validator

class StrategyPoolEntry(BaseModel):
    name: str
    enabled: bool = False
    max_positions: int = 1
    magic: int
    
    @validator('max_positions')
    def max_pos_positive(cls, v):
        if v < 0: raise ValueError("max_positions must be >= 0")
        return v

class RuntimeConfigSchema(BaseModel):
    strategy_pool: dict[str, StrategyPoolEntry]
    max_positions: int = 7
    # ...
```

---

#### P2-3: 前端构建优化

**目标**: Vite manualChunks 分包，首屏加载 -40%

**实施** (`vite.config.ts`):
```typescript
build: {
  rollupOptions: {
    output: {
      manualChunks: {
        'vendor-vue': ['vue', 'vue-router', 'pinia'],
        'vendor-charts': ['lightweight-charts'],
        'vendor-naive': ['naive-ui'],
        'vendor-i18n': ['vue-i18n'],
      },
    },
  },
  chunkSizeWarningLimit: 600,
}
```

---

#### P2-4: 前端类型收紧

**目标**: 消除 `any`，启用 `noImplicitAny: true`

**实施**:
1. 定义 `ChartSeriesMap`、`PaneConfig`、`IndicatorParams` 等核心类型
2. 逐文件替换 `as any` 为精确类型
3. `tsconfig.json` 开启 `"strict": true`

---

### P3 — 持续改进

#### P3-1: 单元测试

**目标**: 核心模块 60%+ 覆盖率

**范围**:
- `core/paper_bridge.py` (SL/TP 触发、CSV 恢复、持仓管理)
- `core/version.py` (版本检查、后台 fetch)
- `utils/indicators.ts` (所有指标计算函数)
- `dashboard/backend/broadcast_hub.py` (P0-3 新建)

**框架**: `pytest + pytest-asyncio` (后端) / `vitest` (前端)

---

#### P3-2: E2E 测试

**目标**: 建立 `tests/e2e/` 固定测试套件

**测试场景**:
- 启动 → 首页渲染 → 版本号显示
- 切换周期 → K 线更新 → 副图联动
- 策略中心 → 添加/删除策略
- 配置页 → 修改风控参数 → 保存
- 持仓 → 手工平仓 → 列表更新

---

#### P3-3: OpenAPI → 前端客户端生成

**目标**: FastAPI OpenAPI → TypeScript 客户端自动生成

**实施**:
```bash
# 后端导出 schema
python -c "from dashboard.backend.main import app; import json; print(json.dumps(app.openapi()))" > openapi.json

# 前端生成客户端
npx openapi-typescript-codegen --input openapi.json --output src/api/generated
```

**收益**: 前端 API 调用类型安全，后端接口变更自动发现。

---

#### P3-4: backtest 目录清理

**目标**: 50+ 杂乱脚本移到独立目录或仓库

**实施**:
- 按策略名归档: `backtest/sanqing/`, `backtest/m30_rsi/` ...
- 删除重复/过期脚本
- 更新 `.gitignore`

---

## 三、实施路线图

| 阶段 | 时间 | 内容 | 验证 | 版本号 |
|------|------|------|------|--------|
| **P0-1a** | Day 1 | chartSync.ts 抽离 | vite build | +0.01 |
| **P0-1b** | Day 1-2 | MainChart.vue 抽离 | build + 截图 | +0.01 |
| **P0-1c** | Day 2-3 | IndicatorPanes.vue 抽离 | build + Playwright | +0.01 |
| **P0-2** | Day 3-4 | 指标增量计算 | build + 性能测试 | +0.1 |
| **P0-3** | Day 4 | WebSocket 背压 | 并发压测 | +0.01 |
| **P1-1a** | Day 5-6 | engine events.py + risk_mgr.py | 语法 + 启动 | +0.01 |
| **P1-1b** | Day 6-7 | engine position_mgr + entry_exit | 语法 + 启动 | +0.01 |
| **P1-2** | Day 7-8 | 后端依赖注入 | API 全端点测试 | +0.1 |
| **P1-3** | Day 8 | 数据库连接池 | 并发测试 | +0.01 |
| **P2-1** | Day 9 | 结构化日志 | 日志格式验证 | +0.01 |
| **P2-2** | Day 9 | 配置 Schema 校验 | 配置变更测试 | +0.01 |
| **P2-3** | Day 10 | 前端构建分包 | chunk 大小对比 | +0.01 |
| **P2-4** | Day 10-11 | 前端类型收紧 | tsc 零 error | +0.01 |
| **P3** | 持续 | 测试 + 清理 | — | — |

**里程碑版本号**:
- P0 完成 → **v3.0.0** (大版本升级)
- P1 完成 → **v3.1.0**
- P2 完成 → **v3.2.0**

---

## 四、快速胜利清单（≤ 2 小时，可立即执行）

| # | 项目 | 预估 | 收益 |
|---|------|------|------|
| 1 | Vite manualChunks 分包 | 10 min | JS -40% |
| 2 | data_factory.py 加 LRU 缓存 | 15 min | 查询 -50% |
| 3 | 删除 .bak 备份文件 | 5 min | 仓库瘦身 |
| 4 | 删除根目录截图/临时测试文件 | 5 min | 仓库瘦身 |
| 5 | requirements.txt 拆分 base/dev/prod | 15 min | 依赖清晰 |
| 6 | TradingTerminal.vue 抽离 chartSync.ts | 30 min | 为 P0-1 铺路 |

---

## 五、风险与约束

| 风险 | 缓解措施 |
|------|----------|
| 引擎核心拆分可能引入运行时 bug | 每步迁移后语法检查 + 引擎启动 + 持仓验证 |
| 前端拆分可能破坏图表联动 | Playwright 十字光标联动测试 + 副图开关测试 |
| 数据库连接池锁竞争 | 用 `contextmanager` + 锁超时 + 压测验证 |
| 配置变更引入 schema 不兼容 | pydantic 校验 + 向后兼容默认值 |
| 后端依赖注入重构影响所有路由 | 逐路由迁移，非一次性替换 |

---

## 六、验证标准（每阶段通用）

```
1. python -m py_compile <changed_files>     # 后端语法
2. cd dashboard/frontend && npx vite build  # 前端构建
3. node playwright_test.mjs                  # 页面功能验证
4. curl -s http://127.0.0.1:1783/api/engine/status  # 引擎状态
5. git add -A && git commit && git push      # 提交推送
```

---

## 七、附录：文件清单（优化涉及范围）

### 后端
```
engine_standalone/main.py          → 拆分为 5 个文件
dashboard/backend/main.py          → 依赖注入重构
dashboard/backend/engine_runner.py → 适配 DI
dashboard/backend/routes/*.py      → 适配 Depends
dashboard/backend/broadcast_hub.py → 新建 (P0-3)
dashboard/backend/deps.py          → 新建 (P1-2)
data/database.py                   → 连接池
core/paper_bridge.py               → 保持，加测试
services/log_messages.py           → 适配 loguru
```

### 前端
```
dashboard/frontend/src/components/dashboard/
  TradingTerminal.vue              → 瘦身为调度层
  MainChart.vue                    → 新建 (P0-1)
  IndicatorPanes.vue               → 新建 (P0-1)
dashboard/frontend/src/utils/
  indicators.ts                    → 增量计算接口
  chartSync.ts                     → 新建 (P0-1)
dashboard/frontend/src/types/
  chart.ts                         → 新建核心类型
dashboard/frontend/vite.config.ts  → manualChunks
dashboard/frontend/tsconfig.json   → strict mode
```

### 文档
```
docs/optimization_plan_v3.md       → 本文档
CHANGELOG.md                       → 每阶段更新
CLAUDE.md                           → 版本号同步
VERSION                             → 版本号同步
```

---

> **注意**: 本方案不涉及策略文件（strategies/ 子模块），策略优化另行规划。  
> 所有改动遵循「先确认再说话」原则，涉及配置数据时必须读取实际数据验证。
