# 策略层「forming bar 上读指标」合规审计

- **审计日期**：2026-09-02
- **审计对象**：`strategies/` 下 25 个策略文件
- **审计目标**：落实 `CODE_REVIEW_STANDARD.md` 的 🔴 阻断项——「确认性指标只源自已闭合 K 线（bar1 / F043 shift=1），禁止用 forming bar（`candles[-1]`）做买卖判定」
- **结论**：**硬违规 0 处**。全仓蜡烛对象只含 OHLCV，指标统一经 `self.get_indicator(key)`（顶层缓存=已闭合 bar1）读取。

---

## 一、扫描方法

| 检查项 | 命中 | 说明 |
|---|---|---|
| `candles[-1].<指标名>`（rsi/atr/ema/bb/macd…） | **0** | 蜡烛对象无指标属性，此类写法物理上不存在 |
| `candles[-1]["<指标名>"]` 字典取值 | **0** | 同上 |
| 全部 `candles[-1]` 用法总数 | 52 | 逐条核对，全部为 `.close/.high/.low/.open/.volume` |
| `_verify_entry` 复核函数总数 | 21 | 全部从传入 `latest`（=bar1 缓存）读指标 |
| `_verify_entry` 内回读 `self.candles[-1]` | 2（followave m15/m30） | 仅用于 `curr.close > curr.open`（多空形态），合规 |

---

## 二、52 处 `candles[-1]` 用法分类（全部合法）

全部为 **OHLCV 价格/量/形态触发**，符合「bar0 可做价格触发」原则：

- **取价触发**（占绝大多数）：`candles[-1].close / .high / .low / .open` —— 突破、挂单、止损价判断
- **取量触发**：`candles[-1].volume` —— 放量/缩量判定（viprasol、momentum_pulse、multi_confluence_quant、M30_rsi_bb）
- **阴阳/实体触发**：`candles[-1].close > candles[-1].open` —— 当前 forming 蜡烛多空形态（entry_score_pro、multi_confluence_quant、M30_rsi_bb、viprasol、followave）
- **振幅/实体派生**：`candle_range = high-low`、`body = abs(close-open)`（entry_score_pro）—— 纯 OHLV 派生，非指标

---

## 三、唯一需复核点：followave `_verify_entry`

`20260821_m15_followave_v1.py:91` 与 `20260821_m30_followave_v1.py:90` 在 `_verify_entry` 内：

```python
candles = latest.get("candles", [])
curr = candles[-1]          # forming bar0
prev = candles[-2]          # closed bar1
candle_trending_up = curr.close > curr.open   # 仅读 forming 蜡烛自身 OHL
bbi  = latest.get("bbi", 0)   # 指标来自 latest = 已闭合 bar1 ✅
bb_mid = bb.get("mid", 0)     # 指标来自 latest = 已闭合 bar1 ✅
```

**判定**：合规。指标（`bbi`/`bb_mid`）取自 `latest`（bar1 缓存），forming bar 仅用于「当前蜡烛多空形态」价格触发，无指标计算。

---

## 四、边界项（合法，但建议在标准中明示允许清单）

以下均为 forming bar 的**价格/量/形态**触发，不重绘，当前合法。为防后续 PR 误用，建议在 `CODE_REVIEW_STANDARD.md` 🔴 项补一段允许/禁止清单：

> **允许（forming bar）**：`.close/.high/.low/.open/.volume` 及其派生（振幅 `high-low`、实体 `abs(close-open)`、阴阳 `close>open`、量比 `vol/avg_vol`）。
> **禁止（forming bar）**：任何指标值（含 RSI/BB/EMA/ATR/ADX/MACD…），以及在 forming bar 上自算的指标。

涉及策略：entry_score_pro、multi_confluence_quant、M30_rsi_bb、viprasol_sniper、momentum_pulse_pro、followave(m15/m30)。

---

## 五、结论与建议

1. **代码无需修改**：本批 25 个策略已完全符合新 🔴 规则；`base.py:91` 兜底修复 + 文档 🔴 项已覆盖该风险。
2. **CI 加固（可选）**：可在 pre-commit 加一条 AST 规则——`_verify_entry` / `generate_signal` 函数体内若出现 `candles[-1].<指标>` 或 `self.candles[-1].<指标>` 即报错；因本仓蜡烛无指标属性，当前 52 处均不会误报。
3. **相邻风险（未纳入本次范围）**：`strategy_manual.md` 规定「禁止自算指标，统一 `get_indicator`」，可另行扫描有无策略手动 `talib`/`numpy` 计算指标——与本次 forming-bar 主题弱相关，列为后续项。
