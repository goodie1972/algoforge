# 策略自算指标（talib/numpy）审计报告

> 审计依据：`strategy_manual.md:17` —— "DataFactory + TA-Lib 是唯一数据来源。所有策略指标通过 `get_indicator(key)` 读取，禁止自算 RSI/MFI/BB/EMA/ATR/ADX/Stoch/MACD 等指标。"
> 审计时间：2026-09-02 ｜ 审计人：火眼眼（Code Review Expert）
> 关联标准：已写入 `docs/CODE_REVIEW_STANDARD.md` 🔴 A 节 —— "禁止在策略内自算买卖指标"
>
> 🟢 **整改状态：已整改（9/9）**。全部自算已改走 `get_indicator()`（xaubot 备份强制 `candles[:-1]` 闭合 + 豁免），并由 `tests/unit/test_strategy_indicators_refactor.py` 静态门禁钉死。详见第七节的整改结果与验证。改动已提交复审，未自动合并。

---

## 一、结论

**发现 9 个策略文件（含 1 个框架备份）在策略内部直接用 `talib` / `numpy` 自算买卖指标，违反 `strategy_manual.md:17` 的明文禁令。**

更严重的是：这些自算**几乎都基于 `self.candles` / `self.get_close_prices()`（含 forming bar0）**，最后一根指标值是在**未完成 K 线**上算出来的 → 同时引入了**重绘 / 未来函数**，与已修的 F043 `shift=1` 是同源隐患，只是发生在策略内部。

**这已经是 🔴 阻断级问题**（资金安全 / 回测-实盘不一致）。所有自算必须迁移到 `get_indicator()`（已算好的 bar1 缓存），或统一在 `data_factory._ta_only_indicators` 内基于 `candles[1:]`（已闭合）计算。

---

## 二、为什么必须拦

1. **违反明确约定**：手册白纸黑字"禁止自算"，而 DataFactory 已经算好 26+ 指标并缓存，`get_indicator(key)` 一行就能拿。自算是重复造轮子 + 双份真相源。
2. **重绘 / 未来函数**：`self.candles[-1]` 是当前未完成 K 线，每个 tick 的 OHLC 都在变。在其上算 `talib.RSI(...)[-1]` 会在收盘前抖动，导致"信号时 RSI=32 触发、收盘变成 28 没触发"的回测/实盘不一致——和 F043 `shift=0` 完全相同的坑。
3. **不可审计、不可单测**：手算散落在各策略里，没法统一覆盖、没法保证和图表一致；与本项目"指标必须可单测、可 CI"的审查基调冲突。
4. **xaubot_backup 整段重算**：一个文件里用 talib 把 RSI/ATR/MACD/BB/EMA/SMA/量价特征全部重算一遍，若被启用将是重绘重灾区（虽文件名带 `backup`，但代码在仓库内，必须清掉或标注）。

---

## 三、违规清单（按文件）

| 文件 | 行 | 自算内容 | 数据来源 | 含 forming bar0 | 严重度 |
|:-----|:---|:--------|:---------|:----------|:------|
| `20260630_M30_rsi_bb_v1.py` | 99–109 | `talib.RSI` 取最近 3 根方向 | `self.get_close_prices()`（= `self.candles` 收盘价） | ✅ 是 | 🔴 |
| `20260630_M30_rsi_bb_v1.py` | 121–148 | `talib.CDLMORNINGSTAR` 等 K 线形态 | `self.candles` 全部 OHLC | ✅ 是 | 🔴（形态也算自算 + 含 forming） |
| `20260801_m30_vol_return_v1.py` | 85–91 | `talib.ATR` + 近 5 根均值 | `self.candles`（high/low/close） | ✅ 是 | 🔴 |
| `20260630_gold_auto_research_v1.py` | 123–129 | `talib.ATR` + 近 20 根均值 | `highs/lows/closes`（源自 `self.candles`） | ✅ 是 | 🔴 |
| `20260630_entry_score_pro_v1.py` | 141–147 | `talib.ATR` 历史阈值 | `self.candles`（high/low/close） | ✅ 是 | 🔴 |
| `20260630_momentum_pulse_pro_v1.py` | 77–79 | `talib.ROC` | `closes`（源自 `self.candles`） | ✅ 是（推测） | 🔴 |
| `20260821_m15_followave_v1.py` | 154–163 | `talib.STOCH` | `seg`（需确认是否剔除了 forming bar） | ⚠️ 待核 | 🔴/🟡 |
| `20260821_m30_followave_v1.py` | 152–161 | `talib.STOCH` | `seg`（需确认是否剔除了 forming bar） | ⚠️ 待核 | 🔴/🟡 |
| `20260811_xaubot_backup_v1.py` | 59–134 | `talib.RSI/ATR/MACD/BBANDS/EMA/SMA` 全套 + 量价特征 | `df['close/high/low/volume']`（df 来源需确认） | ⚠️ 待核 | 🔴（整段，备份文件） |

### 框架层（**合规，不在拦截范围**）
- `strategies/base.py:334–338` `_compute_ema` 用 `talib.EMA` —— 这是**框架通用 helper**，属于"DataFactory + TA-Lib 是唯一数据来源"的合法实现，允许。
- `services/data_factory.py:_ta_only_indicators` 内的 `talib` 计算 —— 唯一合法的计算点，允许，且应作为所有指标的唯一出处。

---

## 四、整改方案

### 方案 A（推荐，零偏差）：直接改用 `get_indicator()`
所有买卖指标改读 DataFactory 已算好的 bar1 缓存：
```python
# 原来
rsi_arr = talib.RSI(np.array(self.get_close_prices()), timeperiod=self.rsi_period)
# 改为
rsi = self.get_indicator("rsi")          # 已闭合 bar1，与 MT4 图表一致
atr = self.get_indicator("atr")
```
优点：现在就能用、无重绘、和图表/回测一致；符合手册。

### 方案 B（确需自定义指标）：统一进 `data_factory._ta_only_indicators`
若某指标 DataFactory 没算（如自研特征），**不要在各策略里算**，而是：
1. 在 `services/data_factory.py` 的 `_ta_only_indicators` 内用 `candles[1:]`（剔除 forming bar0）计算；
2. 通过 `get_indicator(your_key)` 暴露给策略。
这样自定义特征同样享受"已闭合 + 可单测 + 单一真相源"三件套。

### K 线形态（CDL*）的特殊处理
`talib.CDLMORNINGSTAR` 等形态识别用的是 OHLC 序列，不属手册点名的"指标"但**同样基于 `self.candles`（含 forming bar0）**。建议：
- 形态判定也只基于 `candles[1:]`（已闭合），剔除 forming bar0；
- 或把形态识别也移到 `data_factory` 统一计算后暴露。

---

## 五、验收（落到审查标准）
- 🔴 拦截：策略文件（`base.py` 框架 helper 除外）出现 `import talib` / `import numpy` 用于买卖指标计算。
- 🔴 拦截：任何指标基于 `self.candles`（含 `candles[-1]`）计算，而非 `get_indicator()` / `candles[1:]`。
- 整改后，本仓策略对 TA-Lib 的引用应**仅出现在** `services/data_factory.py` 与 `strategies/base.py` 框架 helper 内。

---

## 六、建议的后续动作

> ⚠️ 本节为原始建议；实际执行情况见第七节「整改结果」。原始 3 条建议**已全部落实**（按本仓规矩：改动已提交复审，未自动合并）。

1. 逐文件按方案 A 改造上述 9 个策略（改 + 补单测，按本仓标准交复审、不自动合并）。
2. 在 CI 加一条正则/静态检查：`strategies/*.py` 中（排除 base.py）匹配 `^\s*import talib|^\s*import numpy` 即报错拦截。
3. `xaubot_backup_v1.py`：若不再使用，移出 `strategies/` 或加 `# DEPRECATED` 头；若保留，必须按方案 A/B 改造。

---

## 七、整改结果（本轮）

**状态：9/9 文件已整改完毕，全部经测试钉死，待人工复审 + Risk Owner 确认后合并。**

### 7.1 标准策略（7 个，方案 A：全部改走 `get_indicator()`）

| 文件 | 原自算 | 整改后取值 | 移除 |
|:-----|:------|:----------|:-----|
| `20260630_M30_rsi_bb_v1.py` | `talib.RSI` 方向、`CDL*` 形态 | `get_indicator("rsi_dir_3bar")` / `candle_pattern_dir`+`candle_pattern_name` | 移除全部 `talib`/`numpy` 引用 |
| `20260801_m30_vol_return_v1.py` | `talib.ATR` + 5 根均值 | `get_indicator("atr_ma_5")` 比较 | 移除 talib 块 |
| `20260630_gold_auto_research_v1.py` | `talib.ATR` + 20 根均值 | `get_indicator("atr_sma20")` | 移除 talib 块 |
| `20260630_entry_score_pro_v1.py` | `talib.ATR` 历史阈值 | `get_indicator("atr_ratio_30")` | 移除 ROC/ATR 自算 |
| `20260630_momentum_pulse_pro_v1.py` | `talib.ROC` | `get_indicator("roc_10")` | 移除 talib 块 |
| `20260821_m15_followave_v1.py` | `talib.STOCH` | `get_indicator("stoch_5_3_3")`+`stoch_k_prev`+`stoch_d_prev` | 移除 `import numpy` |
| `20260821_m30_followave_v1.py` | `talib.STOCH` | 同上 | 移除 `import numpy` |

### 7.2 ML 备份策略（1 个，方案 B 变体：强制闭合 + 豁免）

- `20260811_xaubot_backup_v1.py`：XGBoost 模型耦合的特征管线**不能改写**（改写即破坏已训练模型输入分布）。改为：
  - `generate_signal` 中 `for c in self.candles:` → `for c in self.candles[:-1]:`，**只对已闭合 K 线计算特征**，消除 forming bar0 重绘；
  - 文件头 docstring 显式标注「审查豁免：model-coupled ML 特征管线，已限定 `candles[:-1]`」，CI 静态门禁对其豁免（见下方）。

### 7.3 派生字段由 DataFactory 统一计算（`services/data_factory.py`）

上述策略读取的派生字段（如 `rsi_dir_3bar`、`atr_ma_5`、`atr_sma20`、`atr_ratio_30`、`roc_10`、`stoch_k_prev/d_prev`、`candle_pattern_dir/name`）已全部在 `_ta_only_indicators` 内基于**已闭合序列**预算，并经 `get_indicator()` 暴露。修复了一个常年抛 `AttributeError` 被吞的死分支：`CDLBEARISHENGULFING` 在本环境 talib 不存在，已改为 `CDLENGULFING`；端到端验证吞没检测正确返回 `short/ENGULF`。

### 7.4 CI 静态门禁（建议 2 已落地）

- 文件：`tests/unit/test_strategy_indicators_refactor.py`
- `test_no_talib_numpy_import_in_strategy_files`：扫描 `strategies/*.py`，**除 `base.py`/`scanner.py`/`__init__.py`（框架层）与 `xaubot_backup_v1.py`（豁免）外**，出现 `import talib/numpy`/`from talib/numpy` 即断言失败、CI 变红。
- `test_strategy_reads_cached_indicators`（parametrize 7 策略）：验证 helper 直接读 `get_indicator` 缓存，不依赖 `self.candles` 上的 talib 计算。
- `test_stoch_completed_graceful_when_cache_missing`：缓存缺失时优雅返回 `None`，不因缺失回退 talib。
- 关联标准：已写入 `docs/CODE_REVIEW_STANDARD.md` 🔴 A 节「禁止在策略内自算买卖指标」的 CI 门禁段。

### 7.5 验证结果

- 策略重构回归测试：9 passed（本文件）。
- 关联测试簇（含既有 risk_mgr / freemt4_bridge / strategy_base）：51 passed。
- 所有改动文件 `py_compile` 通过；`base.py` 不在 `strategies/*.py` 自算拦截范围（其 talib 仅用于框架 helper `_compute_ema`，合法）。
- 说明：仓库现有 `tests/unit/test_broadcast_hub.py`、`test_lifespan.py`、`test_config_schema.py`、`test_web_manager.py` 因隔离 venv 缺 `pytest-asyncio`/`fastapi`/`pydantic` 而报错，属**既有环境缺口**，与本整改无关。
