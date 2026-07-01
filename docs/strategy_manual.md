# XAUUSD 量化交易系统 — 策略手册（MD 备份）

> 版本: 20260701 | 系统: V6 多策略引擎 | 周期: M30/H1 混合
>
> **最新 HTML 主文档**: `strategies/strategy_manual_20260630.html`
>
> **更新规则**: 每次策略修改后，同步更新此 MD + HTML 文档。

---

## 一、全局系统规则

### 1.1 基类 BaseStrategy (`strategies/base.py`)

- **桥接**: MT4BridgeBase 封装
- **门禁**: 位置门禁 + 急跌急涨惩罚 + News-Bias 阻塞（calc_gate_state）
- **信号格式**: `(signal, score_long, score_short, factors_long[], factors_short[], indicator_values{})`
- **指标工具**:
  - `calc_adx_wilder(candles, period)` — 标准 Wilder ADX/DI，与 TA-Lib 一致
  - `calc_atr_wilder(candles, period)` — 标准 Wilder ATR
- **冷却**: 盈利出场后同方向 30 分钟冷却
- **保本出场**: `_check_breakeven_exit()` — MFE≥0.3ATR 后回成本±0.05ATR 平仓

### 1.2 门禁系统

| 关卡 | 参数 | 效果 |
|---|---|---|
| 位置门禁 | lookback=40, bottom=0.10, top=0.90 | 底部禁空、顶部禁多；DI差>20跳过 |
| 急跌急涨 | lookback=30, threshold=1.5%, ADX跳过=25 | 急跌处禁空、急涨处禁多；ADX>25 跳过 |
| News-Bias | 读取 bias_state | 偏空禁BUY、偏多禁SELL |

### 1.3 出场层级

| 层 | 类型 | 说明 |
|---|---|---|
| 1 | Broker SL/TP | 开仓时写入 MT4 订单，断线兜底 |
| 2 | 保本出场 | MFE≥0.3ATR→成本回收 |
| 3 | 利润回撤 | peak回撤25%(ADX>25调至50%) |
| 4 | ATR 追踪 | 峰值回撤 > trail_mult×ATR |
| 5 | DI 跳过 | 盈利+强趋势(DI差>10)跳过追踪 |
| 6 | 硬止损 | 亏损 > hard_mult×ATR |

### 1.4 指标标准

| 指标 | 标准 |
|---|---|
| RSI | Wilder RMA（SMA种子+RMA递推） |
| ADX/DI | 分别RMA(DM)再归一化÷RMA(TR), DX→RMA(DX)=ADX |
| ATR | Wilder RMA |
| BB | SMA(20)±2σ 总体方差（÷N） |
| EMA | closes[0]种子 + α=2/(N+1) 递推 |
| Stoch | %K(14根)+%D=SMA(%K,3) |
| MACD | EMA12-26, Signal=EMA9 |

---

## 二、策略列表

### 2.1 M30 RSI+BB — `m30_rsi_20260630.py`

**状态**: ✅ 活跃 | v11 | Magic 660707 | 周期 M30

**入场**: 7 因子评分 — ≥4直接开，=3需diff≥2
| # | 因子 | 加分 |
|---|---|---|
| ① | M30 趋势 (close vs MA14) | 同侧+1 |
| ② | BB 位置 (进入上下轨10%) | 同侧+1 |
| ③ | RSI 分层 | **+2**(<25)/+1(<35)多；**+2**(>75)/+1(>65)空 |
| ④ | RSI 方向 (3根递升/递降) | 同侧+1 |
| ⑤ | DI 强度 (\|DI差\|>10) | 同侧+1 |
| ⑥ | 成交量 (>SMA20×1.3+同向) | 同侧+1 |
| ⑦ | K线形态 (TA-Lib强反转:晨星/暮星/锤子/刺透/射击/乌云/吞没/吊人) | 同侧+1 |

ADX>28 门禁已移除（2026-06-30）→ **H1 MA20 趋势门禁**（2026-07-01 新增：H1=DOWN 时清零 LONG 分，H1=UP 时清零 SHORT 分）

**出场**:
| 类型 | 参数 |
|---|---|
| Broker SL/TP | 顺 2.5/4.0, 逆 1.0/2.0, 震荡 1.5/3.0 (SL/TP ×ATR) |
| 保本 | base 基类 |
| 利润回撤 | 25%(ADX>25→50%) |
| ATR 追踪 | trail_mult 锁定于开仓（顺1.5/逆1.0/震荡1.2） |
| DI 跳过 | 盈利+DI差>10 跳过追踪 |
| 硬止损 | 顺3.0/逆2.0/震荡2.5 ×ATR |

---

### 2.2 Gold Auto Research H1 — `gold_autoresearch_h1_20260630.py`

**状态**: ✅ 活跃 | v6 | Magic 880306 | 周期 H1

**入场**: 四因子共识（4/4 必须全过）+ **H4 SMA50 趋势门禁**（H4=DOWN 禁BUY，H4=UP 禁SELL，防反弹诱多/诱空）
| 因子 | 条件 | 方向 |
|---|---|---|
| ① 趋势 | EMA10 vs EMA20 | UP/DOWN |
| ② 动量 | MACD+Stoch **一致**（2026-06-30 修复OR→consensus） | UP/DOWN |
| ③ 波动 | ADX>20 或 ATR上升 | ACTIVE |
| ④ 安全 | RSI10+BB20: RSI≥70+上轨→禁BUY; RSI≤35→禁SELL | - |

决策: `trend and mom and vol and safe` → 信号

**出场**: 保本(base) → 利润回撤25%(ADX>25→50%) → ATR追踪(顺1.5/逆1.0) → 硬止损(顺3.0/逆2.0/震荡2.5)

---

### 2.3 Stoch Trend H1 — `stoch_trend_h1_20260630.py`

**状态**: ✅ 活跃 | v6 | Magic 661201 | 周期 H1

**入场**: ADX 分权（≤25 震荡双向/ >25 趋势单侧）+ Stoch(21,5,3)

**出场**: 保本 → 利润回撤25%(ADX>25→50%) → ATR追踪1.5×ATR → DI反转出场 → 硬止损2.0×ATR

---

### 2.4 M30 MFI+BB — `m30_mfi_bb_20260630.py`

**状态**: ✅ 活跃 | v1 | Magic 661001 | 周期 M30

**入场**: 双模评分（ADX≥25 趋势/ <25 震荡），最高4分，阈值≥3
- 趋势模式：仅顺DI方向单侧
- 震荡模式：多空双侧，含MFI极值方向（MFI超买<strike>80</strike> **70**，超卖30，2026-07-01不对称化）


**出场**: 保本 → 利润回撤25% → ATR追踪1.0×ATR → DI跳过(盈利+DI差>10) → 硬止损2.0×ATR

---

### 2.5 M30 BB DeepReturn — `m30_bb_deepreturn_20260630.py`

**状态**: ✅ 活跃 | v1 | Magic 661101 | 周期 M30

**入场**: BB极值+MFI极值超跌反弹（MFI超买<strike>80</strike> **70**，超卖30，2026-07-01不对称化）

**出场**: 分支出场（BB反向/同向）+ 硬止损2.0×ATR + 保本

---

### 2.6 RSI Grading M30 — `rsi_grading_m30_20260630.py`

**状态**: ❌ 禁用 | v5 | Magic 660902 | 周期 M30

**入场**: RSI分层(≤20=+2, 20-30=+1, ≥80=+2, 70-80=+1) + MA14 + BB触轨 + ADX>28门禁，阈值≥2

**出场**: 利润回撤 → ATR追踪(趋势感知) → 硬止损(趋势感知) + 保本

---

### 2.7 SanQing H1 — `sanqing_h1_20260630.py`

**状态**: ❌ 禁用 | v7 | Magic 880106 | 周期 H1

**入场**: 6因子评分（趋势、EMA9触及、K线实体、成交量、趋势线、吞噬），最高8分
- ADX>20 阈值=4，否则=3（2026-06-30 文档修正）

**出场**: 利润回撤25% → ATR追踪 → 硬止损2.0×ATR + 保本

---

### 2.8 Entry Score Pro — `entry_score_pro_20260630.py`

**状态**: 🔴 未注册 | v1 | Magic 661501 | 周期 M30

**入场**: 5因子加权评分（结构30%+临近25%+动量15%+波动10%+趋势20%），≥75=ENTRY，≥80=PRIME

**出场**: ATR追踪1.5×ATR + 硬止损0.55×ATR（2026-06-30 统一）+ 保本

---

### 2.9 Momentum Pulse Pro — `momentum_pulse_pro_20260630.py`

**状态**: 🔴 未注册 | v1 | Magic 661301 | 周期 M30

**入场**: 7维度评分 ≥6（AMC+MACD+RSI+H1+成交量+ADX+安全过滤）

**出场**: 三层TP(1.5/3.0/5.0 ATR) + ATR追踪1.5×ATR + 硬止损1.5×ATR

---

### 2.10 Multi Confluence Quant — `multi_confluence_quant_20260630.py`

**状态**: 🔴 未注册 | v1 | Magic 661601 | 周期 M30

**入场**: 14因子共振 ≥10/14（EMA排列、RSI、ADX、斜率、成交量、H1、StochRSI、MACD、DI、新高/低等）

**出场**: ATR追踪1.5×ATR + 硬止损2.0×ATR

---

### 2.11 Viprasol Sniper — `viprasol_sniper_20260630.py`

**状态**: 🔴 未注册 | v1 | Magic 661401 | 周期 M30

**入场**: 7因子评分 ≥4且>对手方（EMA9/21+RSI+MACD+DI+成交量+M15-RSI）

**出场**: 多级RR(1R~5R) + 保本 + ATR追踪1.0×ATR + 硬止损1.5×ATR

---

## 三、全局变更日志

### 2026年7月1日

| 变更 | 影响 |
|---|---|
| H1 MA20 趋势门禁（H1=DOWN禁BUY，H1=UP禁SELL） | m30_rsi |
| H4 SMA50 趋势门禁（H4=DOWN禁BUY，H4=UP禁SELL） | gold_autoresearch_h1 |
| MFI 超买 80→70 不对称化 | m30_mfi_bb, m30_bb_deepreturn |
| 新增策略文档 | m30_mfi_bb.md, m30_bb_deepreturn.md |

### 2026年6月30日

| 变更 | 影响 |
|---|---|
| 阈值 3→4; BB 90% 区间替代精确触轨 | m30_rsi |
| 动量 OR→consensus | gold_autoresearch_h1 |
| 保本出场（MFE≥0.3ATR→成本） | base + 全部 |
| ADX/DI 统一标准 Wilder | 全部 11 策略 + base |
| ATR 统一标准 Wilder | momentum/multi/viprasol/entry |
| DI 跳过止盈盈利限定 | m30_rsi, m30_mfi_bb |
| peak_profit 解冻 | m30_rsi, m30_mfi_bb, m30_bb_deepreturn, rsi_grading |
| RR 锁定入场 ATR | viprasol |
| gold ADX 映射 + Stoch 窗口 | gold_autoresearch_h1 |
| 波动因子真实现 | entry_score_pro |
| 硬止损统一 0.55ATR | entry_score_pro |
| 文件名加日期后缀 _20260630 | 全部 11 策略 |

---

## 四、更新指南

每次策略代码修改后：

1. 修改 `strategies/<name>_YYYYMMDD.py`
2. 在 STRATEGY_CHANGELOG 追加版本记录
3. 更新 HTML 主文档：`strategies/strategy_manual_<DATE>.html`
4. 同步此 MD 备份文件
5. `python -m py_compile strategies/<name>_*.py` 编译验证
6. 提交时 git add 代码 + HTML + MD

注册新策略流程：
```
strategies/<name>_YYYYMMDD.py → main.py (import+MAP) → engine_runner.py (版本同步)
→ runtime_config.json (strategy_pool) → settings.py (回退)
```
