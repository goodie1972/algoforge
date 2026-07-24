# DataFactory 数据工厂

> 三轨架构第 1 轨 — 所有策略指标的**唯一数据来源**

## 架构位置

```
MT4 终端 ←→ FreeMT4 桥接 ←→ DataFactory（独立线程） ←→ 全局缓存 ←→ 策略/运动员
```

## 运行机制

### 启动流程

1. `DataFactory.connect()` → 连接桥接
2. `DataFactory.start()` → 启动独立线程 `data-factory`
3. 首次全量加载（最多重试 10 次）
4. 进入增量循环（每 0.3 秒一轮）

### 增量循环

每轮执行：

| 步骤 | 方法 | 说明 |
|:----|:----|:----|
| ① K 线同步 | `_sync_tf("M15"/"M30"/"H1"/"H4")` | 增量拉取 2 根，合并去重 |
| ② Tick 同步 | `_sync_tick()` | bid/ask 报价 |
| ③ 指标覆盖 | `_sync_indicators()` | F043 从 MT4 获取指标值，覆盖 TA-Lib |
| ④ 数据校验 | `_validate_data()` | 每 5 分钟一次，对比数据库 |

### 数据来源优先级

```
1. MT4 F043 命令（get_indicators） ← 优先，与 MT4 图表完全一致
2. TA-Lib 本地计算（_talib_indicators） ← 回退，首次加载 / F043 失败时
3. SQLite 数据库 ← 兜底，桥接数据不足时补充历史 K 线
```

## 指标表（26 个）

### 读取方式

策略通过 `BaseStrategy` 提供的方法读取：

```python
# 本周期指标（H1 策略读 H1 指标）
rsi = self.get_indicator("rsi")       # → float
ema = self.get_indicator("ema_21")    # → float
stoch = self.get_indicator("stoch_5_3_3")  # → {"k": float, "d": float}
bb = self.get_indicator("bb")         # → {"upper": float, "mid": float, "lower": float}

# 跨周期数据（读其他周期的缓存）
from services.data_factory import get_cache
h4 = get_cache("H4")                  # → 完整缓存 dict
h4_ema = h4.get("ema_21")            # → float
h4_candles = h4.get("candles", [])   # → [Candle, ...]
```

### 完整指标列表

| key | 类型 | 参数 | 说明 |
|:----|:----|:----|:----|
| `close` | float | — | 最新收盘价 |
| `trend` | str | SMA14 | `"UP"` / `"DOWN"`，close vs SMA14 |
| `rsi` | float | 14 | RSI |
| `rsi_5` | float | 5 | 快速 RSI |
| `rsi_10` | float | 10 | 中速 RSI |
| `mfi` | float | 14 | 资金流量指数 |
| `mfi_direction` | str | — | MFI 方向 `"up"` / `"down"` / `"flat"` |
| `bb` | dict | 20,2,2 | `{"upper": f, "mid": f, "lower": f}` |
| `bb_width` | float | — | BB 带宽 = upper − lower |
| `bb_width_direction` | str | — | 带宽方向 `"up"` / `"down"` / `"flat"` |
| `bb_width_ratio` | float | SMA3 | 当前带宽 / 近 3 根均值 |
| `ema_9` | float | 9 | 指数移动平均 |
| `ema_21` | float | 21 | 指数移动平均 |
| `sma_14` | float | 14 | 简单移动平均 |
| `sma_20` | float | 20 | 简单移动平均 |
| `sma_50` | float | 50 | 简单移动平均 |
| `atr` | float | 14 | 平均真实波幅 |
| `atr_20` | float | 20 | 平均真实波幅（用于 SL/TP） |
| `atr_list` | list[float] | 14 | ATR 历史序列（长度 = K 线数） |
| `adx` | float | 14 | 趋势强度 |
| `pdi` | float | 14 | +DI 多头方向 |
| `ndi` | float | 14 | −DI 空头方向 |
| `macd` | dict | 12,26,9 | `{"macd": f, "signal": f}` |
| `stoch_5_3_3` | dict | 5,3,3 | `{"k": f, "d": f}` |
| `volume_sma_20` | float | 20 | 成交量 SMA |
| `price_position` | float | 20 周期 | 价格在 20 周期高低区间的位置 0~1 |

### 跨周期数据

通过 `get_cache(tf)` 可读取其他周期的**完整缓存**（含 candles + 所有指标）：

```python
from services.data_factory import get_cache

h4 = get_cache("H4")    # H4 周期
m30 = get_cache("M30")  # M30 周期
m15 = get_cache("M15")  # M15 周期
```

返回的 dict 结构与本周期相同，包含 `candles` 和所有 26 个指标。

## 在策略中使用

### 标准模式

```python
class MyStrategy(BaseStrategy):
    def generate_signal(self):
        # 1. 本周期指标
        rsi = self.get_indicator("rsi")
        ema = self.get_indicator("ema_21")
        stoch = self.get_indicator("stoch_5_3_3")
        adx = self.get_indicator("adx")
        atr = self.get_indicator("atr_20")

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
| DataFactory 运行中 | F043 MT4 优先，TA-Lib 回退 | ✅ 全量 |
| DataFactory 启动中 / 断连 | 策略 `refresh_data()` 自行调 `_talib_indicators` | ✅ 全量（TA-Lib） |
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
# }
```

## 注意事项

- **不要直接调 bridge 获取 K 线**：用 `self.candles` 或 `get_cache(tf)`
- **不要自算标准指标**：RSI/EMA/Stoch/ADX/MACD 等全部由 DataFactory 提供
- **指标可能为 None**：策略必须做空值检查
- **F043 覆盖是异步的**：首次加载用 TA-Lib，F043 连上后覆盖为 MT4 值