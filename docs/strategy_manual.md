# XAUUSD 量化交易系统 — 策略手册（MD 备份）

> 版本: 20260809 | 系统: v2.7.8 三轨架构 | 周期: M30/H1 混合 | 双桥接(exec+data)
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

### 1.3 数据工厂统一指标 (v2.0.0)

DataFactory 独立线程从 TA-Lib 预计算所有公共指标，写入全局缓存。策略通过 `get_indicator(key)` 读取，无需自行桥接。

| 指标 | 缓存 key | 周期 | TA-Lib 函数 |
|:----|:----|:---:|:-----|
| RSI | `rsi` / `rsi_5` / `rsi_10` | M15/M30/H1/H4 | RSI(14/5/10) |
| MFI | `mfi` | 同上 | MFI(14) |
| BB | `bb{upper,mid,lower}` | 同上 | BBANDS(20,2,2) |
| EMA | `ema_9` / `ema_21` | 同上 | EMA(9/21) |
| SMA | `sma_14` / `sma_20` / `sma_50` | 同上 | SMA(14/20/50) |
| ATR | `atr` / `atr_20` | 同上 | ATR(14/20) |
| ADX | `adx` / `pdi` / `ndi` | 同上 | ADX/PLUS_DI/MINUS_DI(14) |
| MACD | `macd{macd,signal}` | 同上 | MACD(12,26,9) |
| Stoch | `stoch_14_3_3` / `stoch_21_5_3` | 同上 | STOCH(14,3,3)/(21,5,3) |
| Trend | `trend` | 同上 | close vs SMA(14) |
| VolSMA | `volume_sma_20` | 同上 | SMA(vol,20) |

策略独有指标（TA-Lib K线形态、MACD序列等）由各策略自行计算。

### 三轨架构说明

v2.0.0 引入三轨架构：

- **轨1: DataFactory** — 独立线程，双桥接(exec+data)，增量拉取K线，TA-Lib统一计算指标
- **轨2: 策略员** — 主引擎循环，读缓存指标，评分达标出门票（候选信号）
- **轨3: 运动员** — tick验证层，实时重算入场条件，10秒过期作废

### 1.4 出场层级

| 层 | 类型 | 说明 |
|---|---|---|
| 1 | Broker SL/TP | 开仓时写入 MT4 订单，断线兜底 |
| 2 | 保本出场 | MFE≥0.3ATR→成本回收 |
| 3 | 利润回撤 | peak回撤25%(ADX>25调至50%) |
| 4 | ATR 追踪 | 峰值回撤 > trail_mult×ATR |
| 5 | DI 跳过 | 盈利+强趋势(DI差>10)跳过追踪 |
| 6 | 硬止损 | 亏损 > hard_mult×ATR |

### 1.5 指标标准

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

### 2.3 Stoch Trend H1 — 双版本

#### v6 (原版) — `stoch_trend_h1_20260630.py`
**状态**: ❌ 已停止 | v6 | Magic 661201 | 周期 H1 | 被 _optimized 取代

**入场**: ADX>25 趋势确认 + Stoch(21,5,3) 超买超卖回调 + 多周期(H4+M15)过滤

#### v7_optimized — `stoch_trend_h1_optimized_20260711.py`
**状态**: ✅ 活跃 | Magic 661202 | 周期 H1

**改动**:
- ADX 阈值 25→20（弱趋势也出信号）
- Stoch 参数 (21,5,3)→(14,3,3)（更快）
- AND逻辑→**评分制**：Stoch极端+2, 金叉+2, EMA方向+1, DI方向+1, H4趋势+1, M15+1（阈值4/8）
- 出场逻辑保持原版

**出场**: 保本 → 利润回撤 → ATR追踪1.5×ATR → DI反转出场 → 硬止损2.0×ATR

---

### 2.4 M30 MFI+BB — 双版本

#### v5 (原版) — `m30_mfi_bb_20260630.py`
**状态**: ❌ 已停止 | v5 | Magic 661001 | 周期 M30 | 被 _optimized 取代

**入场**: 纯均值回归：MFI≥80+BB上轨→SELL，MFI≤20+BB下轨→BUY，3根容差

#### v6_optimized — `m30_mfi_bb_optimized_20260711.py`
**状态**: ✅ 活跃 | Magic 661002 | 周期 M30

**改动**:
- 容差 3→2根（信号更精准）
- MFI超买 80→85，超卖 20→15（更极端才触发）
- 出场逻辑保持原版

**出场**:
| 类型 | 条件 |
|:-----|:------|
| 顺势平 | MFI另一极端+另一轨(2根容差) |
| 逆势平1 | 价格回到BB中轴 |
| 逆势平2 | 价格走了开仓时BB宽度的一半 |

---

### 2.5 M30 BB DeepReturn — 双版本

#### v2 (原版) — `m30_bb_deepreturn_20260630.py`
**状态**: ❌ 已停止 | v2 | Magic 661101 | 周期 M30

#### v3_optimized — `m30_bb_deepreturn_optimized_20260711.py`
**状态**: ✅ 活跃 | Magic 661102 | 周期 M30

**改动**:
- 阈值 3→2（BB触轨+MFI极端即可出单）
- ADX动态阈值：ADX>25(趋势)用3，ADX≤25(震荡)用2
- 新增ATR波动因子(ATR/close>0.25%→+1)
- 盈利冷却 1800s→900s

**出场**: 分支出场（BB反向/同向）+ 硬止损2.0×ATR + 保本

---

### 2.6 RSI Grading M30 — 双版本

#### v5 (原版) — `rsi_grading_m30_20260630.py`
**状态**: ❌ 已停止 | v5 | Magic 660902 | 周期 M30 | 一周0信号

#### v3_optimized — `rsi_grading_m30_optimized_20260711.py`
**状态**: ✅ 活跃 | Magic 660903 | 周期 M30

**改动**:
- ⭐ ADX≤28时阈值保持2（原升到3，导致无法出单）
- RSI超卖阈值 20/30→25/35，超买 65/70→60/75
- 新增RSI方向反转因子（3根K线检测）
- 出场逻辑保持原版

**出场**: 利润回撤 → ATR追踪(趋势感知) → 硬止损(趋势感知) + 保本

---

### 2.7 SanQing H1 — 双版本

#### v7 (原版) — `sanqing_h1_20260630.py`
**状态**: ✅ 活跃 | v7 | Magic 880107 | 周期 H1

#### v1_original — `sanqing_h1_original_20260711.py`
**状态**: ✅ 活跃 | Magic 880101 | 周期 H1

**说明**: 从git历史还原的原始v1代码，作为对比基准
- 6因子评分，阈值=5
- ATR追踪 trail=4.0, hard=2.5
- **无**保本出场、**无**利润回撤止盈、**无**门禁、**无**新闻过滤

---

### 2.8 Bakome Backup — 双版本

#### v1 (原版) — `bakome_backup.py`
**状态**: ❌ 已停止 | v1 | Magic 777004 | 周期 H1

#### v2_optimized — `bakome_backup_optimized_20260711.py`
**状态**: ✅ 活跃 | Magic 777006 | 周期 H1

**改动**:
- 交易时段 6h→10h（伦敦6-10时，纽约12-16时）
- 放松FVG检测：去掉实体方向要求，仅保留缺口条件
- 出场逻辑保持原版

---

---

## 三、全局变更日志

### 2026年7月1日

| 变更 | 影响 |
|---|---|
| H1 MA20 趋势门禁（H1=DOWN禁BUY，H1=UP禁SELL） | m30_rsi |
| H4 SMA50 趋势门禁（H4=DOWN禁BUY，H4=UP禁SELL） | gold_autoresearch_h1 |
| MFI 超买 80→70 不对称化 | m30_mfi_bb, m30_bb_deepreturn |
| 新增策略文档 | m30_mfi_bb.md, m30_bb_deepreturn.md |
| ADX>25趋势模式利润回撤放宽至40% | m30_mfi_bb |

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

### 保本出场实盘观察

基类保本出场（MFE≥0.3ATR→回成本±0.05ATR）在极端位置开仓时过于主动：
- 价格已到 BB 极值/RSI 深度区，开仓后先走一段有利行情
- 但极端位置反弹动力强，价格快速弹回成本
- 导致持仓 10-20 分钟即被保本微亏出场，趋势方向判断正确但没时间奔跑
- 影响策略：m30_rsi（RSI<30时开仓），gold_autoresearch_h1（RSI≤35边缘开仓）
- 可能方案：在 RSI 深度超卖/超买区或价格突破 BB 后禁用保本，改用硬止损兜底

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
