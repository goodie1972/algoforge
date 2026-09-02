# 策略自算指标（talib/numpy）审计报告

> 审计依据：`strategy_manual.md:17` —— "DataFactory + TA-Lib 是唯一数据来源。所有策略指标通过 `get_indicator(key)` 读取，禁止自算 RSI/MFI/BB/EMA/ATR/ADX/Stoch/MACD 等指标。"
> 审计时间：2026-09-02 ｜ 审计人：火眼眼（Code Review Expert）
> 关联标准：已写入 `docs/CODE_REVIEW_STANDARD.md` 🔴 A 节 —— "禁止在策略内自算买卖指标"

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
1. 逐文件按方案 A 改造上述 9 个策略（改 + 补单测，按本仓标准交复审、不自动合并）。
2. 在 CI 加一条正则/静态检查：`strategies/*.py` 中（排除 base.py）匹配 `^\s*import talib|^\s*import numpy` 即报错拦截。
3. `xaubot_backup_v1.py`：若不再使用，移出 `strategies/` 或加 `# DEPRECATED` 头；若保留，必须按方案 A/B 改造。
