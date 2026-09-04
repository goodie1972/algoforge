# 指标来源说明（DataFactory）

本文档说明在 `services/data_factory.py` 中，哪些指标是直接从 MT4 EA（通过 F043 自定义命令）获取，哪些是由本地 TA‑Lib 计算得出。  
目的是帮助策略开发者了解数据的真实来源，避免在策略内部重复计算同一指标。

## 1. 从 MT4 EA 获取（F043）的指标

以下指标在 `_sync_indicators()` 中会直接使用 `bridge.get_indicators()` 返回的 EA 值进行更新（**以 EA 为真实来源**，覆盖内存缓存和数据库）：

| 指标键 | 说明 | 备注 |
|--------|------|------|
| `rsi` | RSI(14) | EA 提供的 RSI 值 |
| `rsi_5` | RSI(5) |  |
| `rsi_10` | RSI(10) |  |
| `mfi` | MFI(14) |  |
| `bb` | 布林带 `{upper, mid, lower}` | EA 提供的三轨值，随后在本地计算 `bb_width`、`bb_width_direction`、`bb_mid_direction` 等派生字段 |
| `ema_9` | EMA(9) |  |
| `ema_21` | EMA(21) |  |
| `ema_34` | EMA(34) | EA(MQL4 `iMA` EMA) 真值（v2 起由 F043 提供，原冻结 bug 已解决） |
| `ema_50` | EMA(50) | EA(MQL4 `iMA` EMA) 真值（v2 起新增） |
| `ema_200` | EMA(200) | EA(MQL4 `iMA` EMA) 真值（v2 起由 F043 提供，原冻结 bug 已解决） |
| `sma_14` | SMA(14) |  |
| `sma_20` | SMA(20) |  |
| `sma_50` | SMA(50) |  |
| `atr` | ATR(14) |  |
| `atr_20` | ATR(20) |  |
| `adx` | ADX(14) |  |
| `pdi` | +DI(14) |  |
| `ndi` | -DI(14) |  |
| `macd` | MACD `{macd, signal}` |  |
| `stoch_5_3_3` | 随机指数 K,D (5,3,3) |  |
| `volume_sma_20` | 成交量 SMA(20) |  |
| `linear_reg_slope` | 线性回归斜率 (20) | EA(MQL4 无内置 `iLR`，改用手算最小二乘回归斜率，窗口 20、结束于 shift) 真值（v2 起由 F043 提供，原冻结 bug 已解决） |
| `cci` | CCI(14) | EA(MQL4 `iCCI`, 典型价) 真值（v2 新增）；方向见 `cci_direction` |
| `cci_direction` | CCI 方向（up/down/flat） | 由 EA 提供的当前/前一根 `cci` 比较得出（与 `bb_width` 同模式：EA 值本地派算，已列入 `_EA_CACHE_KEYS` 防 TA‑Lib 覆盖） |
| `close` | 收盘价 |  |

> **注**：EA 若未能提供上述任意字段，DataFactory 会回退到 TA‑Lib 本地计算（见下表）。  
> ✅ 该回退在 v3 已真正生效：EA 断连超过 `_EA_PROVIDED_TTL`（30s）后，这些键自动回退到 TA‑Lib 实时值，不再冻结（详见第 5.2 节）。

## 2. 由 TA‑Lib 本地计算（EA 不覆盖）的指标

以下指标仅在 `_ta_only_indicators()`（以及后续的派生字段计算）中由 TA‑Lib 算出，**不会被 EA 值覆盖**。它们的值来源于 DataFactory 自身的 K 线序列（从 MT4 拉取的 OHLCV 或从数据库恢复的历史数据）。

| 指标键 | 说明 | 备注 |
|--------|------|------|
| `stoch_14_3_3` | Stoch(14,3,3) K,D | 由 `_ta_only_indicators()` 计算（黄金自动研究 v8 使用） |
| `stoch_rsi` | StochRSI (14,14,3,3) | 仅 TA‑Lib（MQL4 无 `iStochRSI`，未迁 EA；不在 `_EA_CACHE_KEYS`，运行期实时） |
| `atr_list_val` | ATR(14) 单值 | 由 `_ta_only_indicators()` 计算（DB 存单值用） |
| `bb_width` | 布林带宽度 = upper − lower （由 `bb` 计算） | 虽然依赖 EA 的 `bb`，但宽度本身在本地计算 |
| `bb_width_direction` | 布林带宽度方向（up/down/flat） | 本地根据前值比较得出 |
| `bb_width_ratio` | 当前宽度 / 近 3 均值 | 本地计算 |
| `bb_mid_direction` | 布林带中轨方向（up/down/flat） | 本地根据前值比较得出 |
| `bbi` | BBI = (SMA3+SMA6+SMA12+SMA24)/4 | 本地计算 |
| `mfi_direction` | MFI 方向（up/down/flat） | 本地根据前值比较得出 |
| `mfi_dir_50` | MFI 相对于 50 的方向（1/‑1） | 本地计算 |
| `rsi_dir_3bar` | RSI 连续 3 根方向（up/down/flat） | 本地根据已闭合 K 线计算 |
| `atr_ma_5` | ATR 的 5 均值 | 本地计算 |
| `atr_sma20` | ATR 的 SMA(20) | 本地计算 |
| `atr_ratio_30` | 当前 ATR / 30 根前 ATR | 本地计算 |
| `roc_10` | ROC(10) | 本地计算 |
| `trend` | 趋势方向（UP/DOWN）基于 14 根前收盘价比较 | 本地计算 |
| `price_position` | 价格在最近 20 根高低区间的相对位置 (0~1) | 本地计算 |
| `candle_pattern_dir` / `candle_pattern_name` | 蜡烛图形态方向与名称（long/short/none + 名称如 ENGULF/HAMMER） | 由 `talib.CDL*`（MORNING/EVENING/HAMMER/PIERCE/SHOOT/CLOUD/ENGULF/HANG）在 `_ta_only_indicators()` 中算出。**⚠️ 策略层没有 `cdl_*` 这类逐形态键**，请勿调用 `get_indicator("cdl_hammer")`（返回 None），应读 `candle_pattern_dir` / `candle_pattern_name` |
| `stoch_k_prev`, `stoch_d_prev` | 前一根已闭合 K 线的 Stoch K,D 值（用于穿越检测） | 本地计算 |

> 注：`volume_sma_20` 与 `close` 已在第 1 表列出（EA 直供），此处不再重复；若 EA 未提供则回退 TA‑Lib。

## 3. 数据流概览

1. **EA 端**（FreeMT4Bridge EA）在每根 K 线更新时，通过自定义 F043 消息将上述 **第 1 表** 中的指标值发送给 Python 桥接。  
2. **桥接端**（`freemt4_bridge.py` / `paper_bridge.py`）解析 F043 消息，得到一个包含这些指标的字典。  
3. **DataFactory** 在 `_sync_indicators()` 中用 EA 字典直接更新内存缓存（`_DATA_CACHE[timeframe]`）并持久化到数据库（`upsert_indicators`）。  
4. 对于 **第 2 表** 中的指标，DataFactory 不依赖 EA，而是在 `_ta_only_indicators()` 中基于已缓存的 OHLCV 使用 TA‑Lib 直接计算，结果同样写入缓存和数据库。  
5. 策略通过 `self.get_indicator("<key>")` 读取缓存顶层（已完成 K 线，即 bar1），保证所有策略使用同一套指标来源。

## 4. 使用建议

- 若你的策略需要确保与 MT4 图表完全一致的指标（如 RSI、ADX、布林带等），请直接使用上表第 1 列的指标键；它们在 EA 可用时将以 EA 值为准。  
- 对于仅由 TA‑Lib 计算的指标（第 2 表），可以放心在策略内使用，但 **请不要在策略内部重新调用 TA‑Lib 计算同一指标**（这会造成重绘和双份真相源）。直接调用 `self.get_indicator()` 即可。  
- 若需要自行计算某些派生字段（如 `bb_width_direction`），建议直接读取已经计算好的键，而不是在策略内部再次调用 TA‑Lib，以避免不一致。

## 5. 勘误与已知问题（2026-09-04 核对）

### 5.1 第 1 表（EA/F043）经核对——正确
逐字段比对 `tools/FreeMT4Bridge.mq4` 的 F043 响应（34 个字段，idx 0–33；含 6 个 K 线字段 + 28 个指标字段，其中 25 个作为指标键写入缓存）与 `core/freemt4_bridge.py::get_indicators` 解析端、`services/data_factory.py::_sync_indicators` 的 `ea_keys`，三者完全对齐。第 1 表列出的 25 个指标键即为 EA 真实发送、Python 真实解析的字段，**分类正确**。

### 5.2 `_EA_CACHE_KEYS` 与 EA 实际发送不一致 → 5 个键被冻结（**已修复** ✅）
`services/data_factory.py` 顶部的 frozenset `_EA_CACHE_KEYS` 用于 `_sync_tf` 重建缓存时"保护 EA 字段不被 TA‑Lib 覆盖"：
```python
new_cache[k] = old_cache[k] if (k in _EA_CACHE_KEYS and k in old_cache) else v
```
**原问题**：该集合曾包含 **EA 从未发送** 的 5 个键 `ema_34`、`ema_50`、`ema_200`、`stoch_rsi`、`linear_reg_slope`。EA 不写入它们，`old_cache` 的值就停在启动期 DB 恢复（或首轮计算）的结果，之后每轮都被"保护"而**永远保留旧值**，`_ta_only_indicators()` 的实时值被丢弃 → `get_indicator()` 返回冻结陈旧值。

**已采取的修复（v2，2026-09-04）**：
1. **先删除这 5 个键**解除冻结（用户要求的第一步）。
2. **除 `stoch_rsi` 与蜡烛形态外，其余改用 EA 真值**：`ema_34`、`ema_50`、`ema_200`、`linear_reg_slope` 重新回归 `_EA_CACHE_KEYS`，并由 EA F043 真正发送（`tools/FreeMT4Bridge.mq4` 扩展）+ Python 解析端同步（`core/freemt4_bridge.py`）+ `_sync_indicators.ea_keys` 协同。
3. **`stoch_rsi` 不再回归** `_EA_CACHE_KEYS` → 走纯 TA‑Lib，运行期实时更新（MQL4 无 `iStochRSI`，未迁 EA）。
4. 蜡烛图形态 `candle_pattern_dir/name` 同样不在 `_EA_CACHE_KEYS`，保持 TA‑Lib 实时。

`bb_width` 也在 `_EA_CACHE_KEYS` 中，但它由 `_sync_indicators` 基于 EA 的 `bb` 每轮重算写入，属 EA 派生值，保护行为正确，不受影响。

> ✅ **原"残留注意"已在 v3 修复**：旧保护逻辑是**无条件的**——EA 长时间离线时 `_sync_indicators` 提前返回，缓存仍保留上一次 EA 值，TA‑Lib 新值被丢弃，即**所有 EA 键（含 `rsi`）在断连期间冻结在最后有效值**。v3 改为"**仅当本轮 EA 确实提供了该键时才保护**"：新增 `_EA_PROVIDED_TS[tf][key] = 时间戳`（由 `_sync_indicators` 在 EA 真实写入时打戳）与 `_EA_PROVIDED_TTL = 30s`，保护条件变为
> ```python
> ea_provided = (k in _EA_CACHE_KEYS and (now - prov.get(k, 0.0)) <= _EA_PROVIDED_TTL)
> new_cache[k] = old_cache[k] if (ea_provided and k in old_cache) else v
> ```
> 于是 EA 掉线超过 30s 后自动回退到 TA‑Lib 实时值；TTL 取 30s 是刻意远大于正常 F043 轮询周期（约 1–3s），避免 EA/TA 两套值来回跳变造成假信号。

### 5.3 `_sync_tf` 增量模式清空整个顶层缓存（**已修复** ✅）
**原问题（v3 修复前，实测确认）**：`_sync_tf` 在增量模式（`need_full_calc=False`）下 `latest_ind` 为空，但代码仍执行 `_DATA_CACHE[tf] = {"candles": merged}`，把顶层**全部指标键清零**——实测全量计算后的 **45 个键在下一次 0.3s 增量轮次后变成 0 个**，连 `rsi` 都返回 `None`。由于顶层存的是 bar1（已闭合 K 线）的值，而 bar1 在新 K 线出现前恒定不变，正确做法是增量轮次保持原值，而非清空。

后果：TA‑Lib 独有的键（`stoch_rsi`、`candle_pattern_dir/name`、`bbi`、`roc_10`、`trend`、`price_position` 等）在全量计算后的下一个增量轮次即消失，直到下一次全量计算（≤5s）才回来——**即约 94% 的时间读到 `None`**。

**修复**：`new_cache` 先继承旧值（`for k,v in old_cache.items() if k != "candles"`），再用本轮 `latest_ind` 按保护规则覆盖。

### 5.4 文档此前的事实性错误（已校正）
- 蜡烛图形态：原文档写"如 `cdl_engulfing`、`cdl_hammer` 等逐形态键"。代码实际产出的是 `candle_pattern_dir` 与 `candle_pattern_name` 两个键，**不存在 `cdl_*` 键**。已更正（仍保持 TA‑Lib 来源）。
- 原文档遗漏了键 `ema_50`、`stoch_14_3_3`、`atr_list_val`。其中 `ema_50` 已在 v2 改为 **EA 提供**（归入第 1 表），`stoch_14_3_3` 与 `atr_list_val` 补入第 2 表（TA‑Lib）。

## 6. 由 TA‑Lib 计算的指标能否改由 EA 提供（可行性与边界）

**结论：基本都可以**，因为 MQL4 内置指标覆盖了绝大多数，派生字段只是简单算术。逐类说明（✅已实施 = v2 已迁到 EA）：

| 当前 TA‑Lib 键 | EA(MQL4) 可行性 | 说明 |
|:--|:--|:--|
| `ema_34`/`ema_50`/`ema_200` | ✅✅ 已实施 | 内置 `iMA(...,MODE_EMA)`，v2 已由 F043 提供 |
| `linear_reg_slope` | ✅✅ 已实施 | MQL4 无内置 `iLR`，改用手算最小二乘回归斜率（窗口 20、结束于 shift），与 TA‑Lib `LINEARREG_SLOPE` 语义对齐；v2 已由 F043 提供 |
| `cci` / `cci_direction` | ✅✅ 已实施 | 内置 `iCCI(14)`（典型价），v2 新增；方向由当前/前一根比较 |
| `stoch_14_3_3` | ✅ 内置 `iStochastic(14,3,3)` | 尚未迁移，当前仍 TA‑Lib |
| `roc_10` | ✅ 内置 `iROC(10)` | 直接加字段 |
| `bb_width`/`bb_width_direction`/`bb_width_ratio`/`bb_mid_direction` | ✅ 由 EA 已发的 `bb` 派算 | 算术 |
| `mfi_direction`/`mfi_dir_50`/`rsi_dir_3bar` | ✅ 由 EA 已发的 MFI/RSI 派算 | 比较逻辑 |
| `atr_ma_5`/`atr_sma20`/`atr_ratio_30` | ✅ 由 EA 已发的 ATR 派算 | 算术 |
| `bbi` | ✅ 自定义（SMA3+6+12+24 均值） | 4×`iMA` 求平均 |
| `trend`/`price_position` | ✅ `iClose`/`iHigh`/`iLow` 比较 | 算术 |
| `stoch_k_prev`/`stoch_d_prev` | ✅ 取 shift=2 的 `iStochastic` | 直接加字段 |
| `atr_list_val` | ✅ 等同已发的 ATR(14) | 直接加字段 |
| `stoch_rsi` | ⚠️ 需自定义 | MQL4 无 `iStochRSI`，需用 `iStochastic(iRSI(...))` 组合实现 |
| `candle_pattern_dir`/`candle_pattern_name` | ⚠️ 需自定义 | MQL4 无内置 CDL，需把现有 8 种形态判定移植为 MQL4 代码（或 `iCustom`） |

**落地注意（v2 已实施迁移）：**
1. F043 布局由 **28 字段扩展到 34 字段**（idx 0–33）：在 `volume_sma_20`(idx+27) 之后依次追加 `ema_34`、`ema_50`、`ema_200`、`linear_reg_slope`、`cci`、`cci_prev`。（原 `ema_34/50/200` 冻结 bug 正是这种失配的遗留）
2. 数值一致性：TA‑Lib 与 MT4 内置存在已知细微差异（如 MACD signal 在 MQL4 默认用 SMA、TA‑Lib 用 EMA；ATR 平滑细节）。迁到 EA 可获得"与 MT4 图表完全一致"的真值，但会改变现有 TA‑Lib 值，需确认这是期望的单一真相源。
3. 每次 F043 调用 EA 现需计算 34 个字段（原 28 + 新增 6），`freemt4_bridge` 已对 F043 用 20s 超时；若后续再大幅扩展，需评估 EA 计算耗时。
4. **⚠️ 旧 EA 兼容性**：解析端已把字段数下限从 20 提到 **34**（`core/freemt4_bridge.py`）。**未重新编译的旧版 EA（28 字段）响应会被安全拒绝**，`get_indicators` 返回 `{}` → 新增键走 TA‑Lib 兜底、其余 EA 键冻结在最后有效值。**挂 EA 前务必确认 MT4 加载的是重新编译后的新版 .ex4**。
5. 后续继续扩展必须 **MQL4 响应端 + Python `get_indicators` 解析端 + `_sync_indicators.ea_keys` + `_EA_CACHE_KEYS`** 四处同步改动，顺序与字段数严格对齐，否则会静默错位。

---

*文档生成时间：2026-09-04（v3 实施版）*  
*基于当前仓库 `services/data_factory.py`、`core/freemt4_bridge.py`、`tools/FreeMT4Bridge.mq4` 内容核对。*  
*v2 变更：`ema_34/ema_50/ema_200/linear_reg_slope` 改由 EA(F043) 提供；新增 `cci` 与 `cci_direction`；`stoch_rsi` 与蜡烛形态保留 TA‑Lib；F043 由 28 字段扩至 34 字段。*  
*v3 变更：修复增量模式清空顶层缓存（45 键→0）；保护逻辑改为"EA 本轮确实提供过该键才保护"（`_EA_PROVIDED_TS` + TTL 30s），EA 掉线超 30s 自动回退 TA‑Lib。*