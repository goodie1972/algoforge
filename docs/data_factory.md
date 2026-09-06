# DataFactory 数据工厂

> 三轨架构第 1 轨 — 所有策略指标的**唯一数据来源**
>
> 📌 指标逐键的权威来源表（EA / TA‑Lib 逐字段对照、勘误与协议细节）见仓库根目录 [`INDICATOR_SOURCES.md`](../INDICATOR_SOURCES.md)。本文档侧重"怎么用"，那份侧重"从哪来"。

## 架构位置

```
MT4 终端 ←→ FreeMT4 桥接(F043) ←→ DataFactory（独立线程） ←→ 全局缓存 ←→ 策略/运动员
                                        ↑
                                   TA-Lib 本地计算（回退）
```

## 运行机制

### 启动流程

1. `DataFactory.connect()` → 连接桥接
2. `DataFactory.start()` → 启动独立线程 `data-factory`
3. **加载暖缓存**（v4）→ 从 `data/cache/candles_cache.pkl` 恢复上次 K 线（如可用，避免冷启动重拉 4×2000 根）
4. `_init_indicators_from_db()` → 从 SQLite 恢复最近指标（保证 EA 未连上时策略即可运行）
5. 首次加载按"上次末根 − 当前时间"测算缺口，增量补齐（上限 2000 根）；如无暖缓存/缓存过旧则全量加载
6. 进入增量循环（每 0.3 秒一轮）

### 增量循环

每轮执行：

| 步骤 | 方法 | 说明 |
|:----|:----|:----|
| ① K 线同步 | `_sync_tf("M15"/"M30"/"H1"/"H4")` | 增量拉取 2 根，合并去重；必要时 TA‑Lib 重算 |
| ② Tick 同步 | `_sync_tick()` | bid/ask 报价，**自动 prune tick_data ≤ 200K 行**（v5 起） |
| ③ 指标覆盖 | `_sync_indicators()` | F043 从 MT4 EA 取指标，覆盖 TA‑Lib 值 |
| ④ 数据校验 | `_validate_data()` | 每 5 分钟一次，对比数据库 |
| ⑤ 暖缓存落盘 | `_save_candle_cache()` | 每 5 分钟一次（v4 起，重启可复用） |

### 全量计算 vs 增量更新

`_sync_tf` 并非每轮都跑 TA‑Lib（较耗 CPU）。触发**全量计算**的条件：出现新 K 线，或距上次计算超过 `_ta_calc_interval`（5 秒）；否则走**增量更新**，只刷新 `candles`，顶层指标值保持不变。

> 顶层缓存存的是 **bar1（上一根已闭合 K 线）** 的指标值。bar1 在新 K 线出现前恒定不变，因此增量轮次保持原值是**正确语义**。
>
> ⚠️ v3 修复过此处一个严重缺陷：旧实现在增量轮次用 `{"candles": merged}` 整体替换缓存，导致全量算出的 45+ 个指标键在下一个 0.3s 轮次被**清零**（实测 `rsi` 也为 `None`），TA‑Lib 独有键约 94% 的时间读不到。现改为先继承旧值再覆盖。

### 数据来源优先级

```
1. MT4 F043 命令（get_indicators）  ← 优先，与 MT4 图表完全一致
2. TA-Lib 本地计算（_ta_only_indicators） ← 回退
3. SQLite 数据库 ← 启动恢复 + 桥接数据不足时补充历史 K 线
```

**回退何时生效（v3 起）**：`_sync_tf` 用 `_EA_CACHE_KEYS` 保护 EA 字段不被 TA‑Lib 覆盖，但保护是**有条件**的——只有 EA 在 `_EA_PROVIDED_TTL`（**30 秒**）内确实提供过该键才保护。

| 场景 | 行为 |
|:----|:----|
| EA 正常 | EA 值受保护，策略读到与 MT4 图表一致的值 |
| EA 掉线 ≤ 30s | 暂沿用最后一次 EA 值（避免 EA/TA 两套值来回跳变产生假信号） |
| EA 掉线 > 30s | 保护失效，**自动回退 TA‑Lib 实时值** |
| 缓存中尚无该键 | 直接用 TA‑Lib 值 |

TTL 取 30s 是刻意的：远大于正常 F043 轮询周期（约 1–3 秒），既避免值跳变，又能在掉线后半分钟内恢复。

## 指标表（46 个键）

顶层缓存共 **47 个指标键**（v6 新增 `bbi_direction`）；其中 `candle_pattern_name` 仅在识别到形态时出现，常态可见 **46 个**。

图例：**EA** = MT4 F043 直供 · **EA派生** = 由 EA 值在 Python 侧派算 · **TA** = 仅 TA‑Lib 计算

### 读取方式

策略通过 `BaseStrategy` 提供的方法读取：

```python
# 本周期指标（H1 策略读 H1 指标）
rsi  = self.get_indicator("rsi")            # → float
ema  = self.get_indicator("ema_200")        # → float（v2 起由 EA 提供）
stoch = self.get_indicator("stoch_5_3_3")   # → {"k": float, "d": float}
bb   = self.get_indicator("bb")             # → {"upper": f, "mid": f, "lower": f}
cci  = self.get_indicator("cci")            # → float（v2 新增）
cci_dir = self.get_indicator("cci_direction")  # → "up"/"down"/"flat"（v2 新增）

# 跨周期数据（读其他周期的缓存）
from services.data_factory import get_cache
h4 = get_cache("H4")                # → 完整缓存 dict
h4_ema = h4.get("ema_21")           # → float
h4_candles = h4.get("candles", [])  # → [Candle, ...]
```

### 一、EA 直供（24 个）

| key | 类型 | 参数 | 说明 |
|:----|:----|:----|:----|
| `rsi` | float | 14 | RSI |
| `rsi_5` | float | 5 | 快速 RSI |
| `rsi_10` | float | 10 | 中速 RSI |
| `mfi` | float | 14 | 资金流量指数 |
| `bb` | dict | 20,2 | `{"upper": f, "mid": f, "lower": f}` |
| `ema_9` | float | 9 | 指数移动平均 |
| `ema_21` | float | 21 | 指数移动平均 |
| `ema_34` | float | 34 | 指数移动平均（v2 起由 EA 提供） |
| `ema_50` | float | 50 | 指数移动平均（v2 新增） |
| `ema_200` | float | 200 | 指数移动平均（v2 起由 EA 提供） |
| `sma_14` | float | 14 | 简单移动平均 |
| `sma_20` | float | 20 | 简单移动平均 |
| `sma_50` | float | 50 | 简单移动平均 |
| `atr` | float | 14 | 平均真实波幅 |
| `atr_20` | float | 20 | 平均真实波幅（常用于 SL/TP） |
| `adx` | float | 14 | 趋势强度 |
| `pdi` | float | 14 | +DI 多头方向 |
| `ndi` | float | 14 | −DI 空头方向 |
| `macd` | dict | 12,26,9 | `{"macd": f, "signal": f}` |
| `stoch_5_3_3` | dict | 5,3,3 | `{"k": f, "d": f}` |
| `linear_reg_slope` | float | 20 | 线性回归斜率（v2 起由 EA 提供） |
| `volume_sma_20` | float | 20 | 成交量 SMA |
| `cci` | float | 14 | CCI 商品通道指数（v2 新增，典型价） |
| `close` | float | — | 最新收盘价 |

> EA 掉线超 30s 时，上表中除 `cci` 外的键均有 TA‑Lib 兜底值（`cci` 亦有兜底，见 `_ta_only_indicators`）。

### 二、EA 值本地派算（2 个）

| key | 类型 | 说明 |
|:----|:----|:----|
| `bb_width` | float | BB 带宽 = upper − lower（由 EA 的 `bb` 计算） |
| `cci_direction` | str | CCI 方向 `"up"` / `"down"` / `"flat"`（当前 vs 前一根，两根均来自 EA） |

### 三、仅 TA‑Lib 计算（20 个）

| key | 类型 | 参数 | 说明 |
|:----|:----|:----|:----|
| `stoch_14_3_3` | dict | 14,3,3 | `{"k": f, "d": f}` |
| `stoch_rsi` | dict | 14,14,3,3 | `{"k": f, "d": f}` StochRSI |
| `stoch_k_prev` | float | — | 前一根已闭合 K 线 Stoch K（穿越检测用） |
| `stoch_d_prev` | float | — | 前一根已闭合 K 线 Stoch D |
| `bbi` | float | 3,6,12,24 | BBI = (SMA3+SMA6+SMA12+SMA24)/4 |
| `roc_10` | float | 10 | ROC 变动率 |
| `trend` | str | close vs 14 根前 | `"UP"` / `"DOWN"` |
| `price_position` | float | 20 周期 | 价格在 20 周期高低区间的位置 0~1 |
| `rsi_dir_3bar` | str | — | RSI 连续 3 根方向 `"up"`/`"down"`/`"flat"` |
| `mfi_direction` | str | — | MFI 方向 |
| `mfi_dir_50` | int | — | MFI 相对 50：`1` / `-1` |
| `bb_width_direction` | str | — | 带宽方向 |
| `bb_width_ratio` | float | SMA3 | 当前带宽 / 近 3 根均值 |
| `bb_mid_direction` | str | — | BB 中轨方向（= SMA20 斜率）。⚠️ **不是** BBI 方向，两者不一致率约 25%，需要 BBI 方向请用 `bbi_direction` |
| `bbi_direction` | str | — | **BBI 方向**（v6 新增）。BBI=(SMA3+SMA6+SMA12+SMA24)/4 的当前根 vs 前一根 |
| `atr_list_val` | float | 14 | ATR(14) 单值（DB 存单值用） |
| `atr_ma_5` | float | 5 | ATR 近 5 根均值 |
| `atr_sma20` | float | 20 | ATR 的 SMA(20) |
| `atr_ratio_30` | float | 30 | 当前 ATR / 30 根前 ATR |
| `candle_pattern_dir` | str | — | 蜡烛形态方向 `"long"`/`"short"`/`"none"` |
| `candle_pattern_name` | str | — | 形态名（如 `ENGULF`/`HAMMER`），**仅识别到形态时出现** |

> ⚠️ **蜡烛形态没有 `cdl_*` 这类逐形态键**。请勿调用 `get_indicator("cdl_hammer")` —— 恒返回 `None`。应读 `candle_pattern_dir` + `candle_pattern_name`。

## 跨周期数据

通过 `get_cache(tf)` 可读取其他周期的**完整缓存**（含 candles + 所有指标）：

```python
from services.data_factory import get_cache

h4  = get_cache("H4")    # H4 周期
m30 = get_cache("M30")   # M30 周期
m15 = get_cache("M15")   # M15 周期
```

返回结构与本周期相同，包含 `candles` 与全部指标键。

## 在策略中使用

### 标准模式

```python
class MyStrategy(BaseStrategy):
    def generate_signal(self):
        # 1. 本周期指标
        rsi  = self.get_indicator("rsi")
        ema  = self.get_indicator("ema_21")
        stoch = self.get_indicator("stoch_5_3_3")
        adx  = self.get_indicator("adx")
        atr  = self.get_indicator("atr_20")
        cci  = self.get_indicator("cci")            # v2 新增
        cci_dir = self.get_indicator("cci_direction")

        # 空值检查
        if rsi is None or ema is None:
            return None

        # 2. 跨周期数据
        h4 = get_cache("H4")
        if h4:
            h4_ema = h4.get("ema_21")
            h4_close = h4.get("close")

        # 3. K 线数据
        candles = self.candles
        closes = self.get_close_prices()
```

### 数据可用性

| 场景 | 指标来源 | 可用性 |
|:----|:----|:----|
| DataFactory 运行中 + EA 在线 | F043（MT4 图表一致）优先 | ✅ 全量 |
| EA 掉线 > 30s | 自动回退 TA‑Lib 实时值 | ✅ 全量 |
| DataFactory 启动中 / K 线不足 | TA‑Lib（或启动期 DB 恢复值） | ✅ 全量 |
| K 线 < 30 根 | 返回空 dict | ❌ 无数据 |

## 健康监控

```python
from services.data_factory import get_health
health = get_health()
# {
#   "bridging": True/False,
#   "started_at": 1234567890.0,
#   "tfs": {"H1": {"last_sync": ..., "candles": 350, "has_indicators": True, "ok": True}, ...},
#   "sync_errors": [...],
#   "last_tick_time": ...,
#   "tick_count": 12345,
#   "db_health": {"last_write_time": ..., "writes_total": N, "writes_failed": N, "ok": True},
# }
```

F043 取不到指标时（EA 未挂 / 协议不匹配）会在日志输出
`[DataFactory] F043 tf=XX returned shorts(...)`，可据此判断 EA 侧问题。

## 版本变更

| 版本 | 日期 | 要点 |
|:----|:----|:----|
| v5 | 2026-09-05 | (3.5.6 D1) **`tick_data` 自动清理**：每 5 分钟 prune 调用，max_rows=200000；新增 `idx_tick_data_ts` 索引。修复合法化维护：永久删除与数据库连接池错误等不再阻塞 tick 同步 |
| v4 | 2026-09-05 | (3.5.4 B) **暖启动门控**：新增 `data/cache/candles_cache.pkl` 本地 K 线缓存，重启按时间差增量补齐（≤2000 根），冷启动加速；缓存每 5 分钟及首轮成功后落盘 |
| v3 | 2026-09-04 | ①修复增量轮次清空顶层缓存（指标被清零）；②保护逻辑改为"EA 本轮确实提供过该键才保护"（`_EA_PROVIDED_TS` + TTL 30s），EA 掉线超 30s 自动回退 TA‑Lib |
| v2 | 2026-09-04 | F043 由 28 字段扩至 34 字段：`ema_34/ema_50/ema_200/linear_reg_slope` 改由 EA 提供；新增 `cci` 与 `cci_direction`；修复 `_EA_CACHE_KEYS` 含 EA 未发送键导致 5 个键被冻结 |
| v1 | 2026-09-03 | 建立版本基线；新增派生字段（`rsi_dir_3bar`/`atr_ma_5`/`atr_sma20`/`atr_ratio_30`/`roc_10`/`stoch_k_prev`/`stoch_d_prev`/`candle_pattern_dir`/`candle_pattern_name` 等） |

版本号常量：`DATA_FACTORY_VERSION` / `DATA_FACTORY_CHANGELOG`（见文件头）。

### 指标完整性回填（回测前推荐执行）

MT4 历史保留期短，自存是回测的硬需求。运行：

```bash
python tools/backfill_indicators.py --only-incomplete
```

从 `ohlcv` 表读取全部 K 线，对覆盖率不足的行用 TA-Lib 重新计算全套 47 键并 UPSERT 到 `indicator_snapshots`。详见 [product_manual.md §19.5](product_manual.md#195-指标完整性回填工具-356)。

## 注意事项

- **不要直接调 bridge 获取 K 线**：用 `self.candles` 或 `get_cache(tf)`
- **不要自算标准指标**：RSI/EMA/Stoch/ADX/MACD/CCI 等全部由 DataFactory 提供（策略内自算会造成重绘与"双份真相源"，见 `docs/CODE_REVIEW_STANDARD.md`）
- **确认性指标只能源自 bar1**：`get_indicator()` / `get_cache()` / `candles[-2]`；`candles[-1]`（未闭合 bar0）仅可价格/量触发，禁止在其上算指标做判定
- **指标可能为 None**：启动初期或数据不足时仍可能缺值，策略请保留空值检查
- **改 F043 协议需四处同步**：MQL4 响应端（`tools/FreeMT4Bridge.mq4`）、Python 解析端（`core/freemt4_bridge.py`）、`_sync_indicators.ea_keys`、`_EA_CACHE_KEYS`，字段顺序与数量必须严格一致，否则会静默错位
- **改 DataFactory 代码要冷重启**：进程内热重启（A 改进）**不重载 `services/data_factory.py`**——DataFactory 实例被保留。如改 DataFactory 需冷重启，下次改进计划 F2 计划让其覆盖热重启
