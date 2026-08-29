---
name: market_analysis
description: 行情研判 — 结合当前指标、K线形态、新闻给出综合行情分析。Use when user asks to "行情研判", "市场分析", "行情分析", "market analysis", "偏多还是偏空", "趋势判断", "综合研判", "看看行情", "盘面分析", "方向判断", or when multi-timeframe indicator data is available and the user wants a directional bias assessment for XAUUSD.
---

# 行情研判 Skill

根据当前系统提供的实时指标（RSI、MACD、BB、ADX、趋势方向）和新闻动向，进行综合行情研判。

## 触发条件

当满足以下任一条件时触发本 Skill：

1. 用户明确请求行情研判、市场分析、方向判断
2. 用户询问"偏多/偏空/震荡"等方向性问题
3. 用户要求分析当前盘面或趋势
4. 系统已有可用的多周期指标数据（M30/H1/H4），用户希望获得综合解读

**不触发的场景**：用户仅询问单个指标数值（直接读取即可）、用户请求持仓诊断（应触发 `position_diagnosis`）、用户请求系统风险检查（应触发 `risk_check`）。

## 执行流程

### Step 1: 采集多周期 K 线数据

通过 `core.bridge` 的 `get_candles()` 获取 M30、H1、H4 三个周期的 K 线数据（至少 100 根），提取 OHLCV 数组。

### Step 2: 计算各周期技术指标

对每个周期调用 `indicators` 模块的函数：

| 指标 | 函数 | 用途 |
|------|------|------|
| EMA | `calc_ema(closes, period)` | 趋势方向（EMA20/50/200） |
| RSI | `calc_rsi(closes, period=14)` | 超买超卖 |
| MACD | `calc_macd(closes)` → `(macd_line, signal_line, hist)` | 动量方向 |
| BB | `calc_bb(closes, period=20, std_mul=2.0)` → `{sma, upper, lower, width}` | 价格位置 |
| ADX | `calc_adx(highs, lows, closes, period=14)` → `{adx, pdi, ndi}` | 趋势强度 |
| Stoch | `calc_stoch(highs, lows, closes)` → `{k, d, prev_k, prev_d}` | 金叉/死叉 |
| ATR | `calc_atr(highs, lows, closes, period=14)` | 波动率 |

### Step 3: 多周期对齐分析

1. **趋势方向一致性**：各周期 EMA20 相对 EMA50 的位置（上方=多头排列，下方=空头排列）
2. **ADX 趋势确认**：ADX > 25 表示趋势明确，< 20 表示震荡
3. **动量方向**：MACD histogram 正负 + Stoch 金叉/死叉信号
4. **价格位置**：当前价在 BB 中的相对位置（`(price - lower) / (upper - lower)`）

### Step 4: 风险事件检查

1. 检查即将到来的经济数据发布（非农、CPI、利率决议等）
2. 检查新闻方向是否与指标信号冲突
3. 标注未来 2 小时内的重大事件

### Step 5: 综合研判

基于以上分析，给出明确偏向和关键价位。

## 输出契约

研判报告必须包含以下结构化段落：

```
## 行情研判报告

**时间**: YYYY-MM-DD HH:MM UTC
**品种**: XAUUSD
**当前价格**: $XXXX.XX

### 偏向结论
- **方向**: 偏多 / 偏空 / 震荡
- **信心度**: 强 / 中 / 弱
- **关键假设**: [一句话说明]

### 多周期趋势
| 周期 | EMA排列 | ADX | 趋势方向 |
|------|---------|-----|----------|
| M30  | ...     | ... | ...      |
| H1   | ...     | ... | ...      |
| H4   | ...     | ... | ...      |

### 动量信号
- MACD: [方向 + 柱状图趋势]
- Stoch: [K/D 值 + 交叉信号]
- RSI: [数值 + 超买/超卖状态]

### 关键价位
- **阻力位**: $XXXX / $XXXX
- **支撑位**: $XXXX / $XXXX
- **BB 区间**: $XXXX — $XXXX

### 风险提醒
- [即将发布的经济数据/新闻风险]
```

## 验证步骤

完成研判后，逐项检查：

1. **完整性**：三个周期（M30/H1/H4）的指标数据均已采集并分析
2. **一致性**：偏向结论与多周期趋势分析方向一致（若矛盾需说明原因）
3. **具体性**：关键价位包含至少 2 个阻力位和 2 个支撑位
4. **时效性**：风险提醒段落已检查近期经济日历
5. **格式合规**：输出符合上述输出契约的 Markdown 结构
