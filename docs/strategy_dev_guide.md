# XAUUSD 量化交易系统 — 策略开发规范

> 版本: v2.7.8 | 最后更新: 2026-08-11

---

## 目录

1. [架构总览](#1-架构总览)
2. [快速开始：创建第一个策略](#2-快速开始创建第一个策略)
3. [策略注册与部署](#3-策略注册与部署)
4. [BaseStrategy 基类参考](#4-basestrategy-基类参考)
5. [数据源与指标](#5-数据源与指标)
6. [出场逻辑体系](#6-出场逻辑体系)
7. [信号生成规范](#7-信号生成规范)
8. [风控与门禁系统](#8-风控与门禁系统)
9. [策略模板](#9-策略模板)
10. [MQL4/MQL5 移植指南](#10-mql4mql5-移植指南)
11. [测试与调试](#11-测试与调试)
12. [常见问题](#12-常见问题)

---

## 1. 架构总览

### 三轨架构

```
轨1: DataFactory（独立线程）
  → 增量拉取 K 线 → TA-Lib 统一计算 26 个指标
  → 指标写入缓存，供所有策略读取

轨2: 策略员（主循环）
  → 每 tick 遍历所有策略 → on_tick()
  → generate_signal() 评分 → 评分达标出门票
  → 风控门禁检查 → 提交给运动员

轨3: 运动员（tick 验证层）
  → 收到候选门票后持续验证 _verify_entry
  → 10 个 tick 内验证通过则开仓，否则作废
```

### 策略生命周期

```
文件放入 strategies/ → 注册到 registry → 配置策略池 → 引擎加载 → 信号生成 → 开仓 → 出场
```

### 技术栈

| 组件 | 技术 |
|:----|:-----|
| 策略语言 | Python 3.10+ |
| 基类 | `strategies/base.py` → `BaseStrategy` |
| 数据源 | DataFactory（TA-Lib 计算）+ F043 MT4 桥接 |
| 出场 | `check_ema20_exit()` + 通用保本/回撤止盈 |
| 风控 | GateManager + RiskManager + 策略级 max_positions |
| 配置 | `runtime_config.json` + `strategy_pool` |

---

## 2. 快速开始：创建第一个策略

### 步骤 1：创建策略文件

在 `strategies/` 目录下创建 `.py` 文件，文件名格式：`{策略名}_{日期}.py`。

```python
"""
M30 MyStrategy — 示例策略
==========================
- 基于 RSI + EMA 的简单趋势策略
- 出场: ATR 追踪止损 + 硬止损
数据源: 全部指标从 DataFactory TA-Lib 读取
"""

import logging
from typing import Optional
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 889900
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 889900, "date": "2026-08-11",
     "desc": "初始版本：RSI+EMA 趋势策略"},
]

class MyStrategy(BaseStrategy):
    name = "my_strategy"  # 策略唯一标识名（注册用，全小写+下划线）
    legacy_magics = []    # 旧版 magic 列表（版本升级时使用）

    def __init__(self, bridge, magic=0, timeframe=""):
        super().__init__(bridge, magic, timeframe)
        # 策略参数
        self.score_threshold = 3     # 评分阈值（≥阈值触发信号）
        self.p_hard_atr = 2.0        # 硬止损倍数
        self.p_trailing_atr = 1.0    # 追踪止损倍数

    def generate_signal(self) -> Optional[tuple]:
        """生成交易信号（评分系统）"""
        # ... 实现信号逻辑

    def check_ema20_exit(self, position, bid, ask) -> bool:
        """出场逻辑"""
        # ... 实现出场逻辑
```

### 步骤 2：注册策略

在 `dashboard/backend/strategy_registry.py` 中添加策略名。

### 步骤 3：配置策略池

在 `dashboard/runtime_config.json` 的 `strategy_pool` 中添加策略配置，设置 `enabled: false`（默认禁用）。

### 步骤 4：启用策略

在策略中心 UI 手动启用，重启引擎生效。

---

## 3. 策略注册与部署

### 3.1 注册流程

```
1. 创建策略 .py 文件 → strategies/{name}_{date}.py
2. 注册到 strategy_registry.py → 策略中心可见
3. 注册到 engine_standalone/main.py 的 STRATEGY_MAP → 引擎可加载
4. 添加 runtime_config.json strategy_pool → 可配置
5. 用户在策略中心 UI 启用 → 重启引擎生效
```

### 3.2 strategy_registry.py 注册

```python
# dashboard/backend/strategy_registry.py
METADATA = {
    "my_strategy": {
        "name": "my_strategy",
        "display": "MyStrategy — 示例策略",
        "file": "my_strategy_20260811.py",
        "class_name": "MyStrategy",
        "default_magic": 889900,
        "default_timeframe": "M30",
    },
}
```

### 3.3 runtime_config.json 配置

```json
{
  "strategy_pool": {
    "my_strategy": {
      "enabled": false,
      "magic": 889900,
      "timeframe": "M30",
      "max_positions": 1,
      "double_first": false
    }
  }
}
```

### 3.4 引擎 STRATEGY_MAP

```python
# engine_standalone/main.py
STRATEGY_MAP = {
    "my_strategy": MyStrategy,
}
```

---

## 4. BaseStrategy 基类参考

### 4.1 类属性（策略定义）

| 属性 | 类型 | 说明 |
|:----|:----|:------|
| `name` | str | 策略唯一标识名（全小写+下划线） |
| `legacy_magics` | list[int] | 旧版 Magic 列表，用于版本升级时接管旧单 |
| `magic` | int | 策略 Magic Number（唯一） |
| `timeframe` | str | 策略运行的 K 线周期（M5/M15/M30/H1/H4） |
| `symbol` | str | 交易品种（默认 XAUUSD） |

### 4.2 核心方法（必须实现）

#### `generate_signal() -> Optional[tuple]`

**作用：** 生成交易信号，每 tick 被引擎调用。

**返回值格式：**
```python
# 无信号时返回 None
return None

# 有信号时返回 (signal_type, score_long, score_short, factors, scores, indicators)
return (
    signal_type,      # OrderType.BUY 或 OrderType.SELL
    score_long,       # 多头评分（整数）
    score_short,      # 空头评分（整数）
    factors,          # 因子列表，如 ["RSI-UP", "EMA-UP"]
    scores,           # 各因子得分
    indicator_values, # 指标字典，用于日志和报表
)
```

**信号触发条件：** 引擎比较 `score_long >= threshold` 或 `score_short >= threshold`，达标则出门票。

#### `check_ema20_exit(position, bid, ask) -> bool`

**作用：** 出场检查，每 tick 被引擎调用。

**参数：**
- `position`: Position 对象（含 ticket, open_price, order_type, magic 等）
- `bid`: 当前买价
- `ask`: 当前卖价

**返回值：** `True` 表示触发出场，引擎执行平仓。

**标准出场逻辑模板：**
```python
def check_ema20_exit(self, position, bid, ask) -> bool:
    ticket = position.ticket
    is_buy = position.order_type in ("OP_BUY", "BUY")

    # 获取指标
    bb = self.get_indicator("bb")
    mfi = self.get_indicator("mfi")
    atr = self.get_indicator("atr")
    if bb is None or mfi is None or atr is None:
        return False

    current_price = bid if is_buy else ask

    # 初始化追踪数据
    if ticket not in self._trail_data:
        self._trail_data[ticket] = {...}

    td = self._trail_data[ticket]

    # 条件①: 趋势出场（穿轨后回抽）
    # 条件②: 中线出场（价格回到中线）
    # 条件③: 半宽出场（逆势走了半宽）

    return False  # 不出场
```

### 4.3 辅助方法（可直接调用）

#### 指标读取

```python
self.get_indicator("rsi")           # → float
self.get_indicator("ema_21")        # → float
self.get_indicator("bb")            # → {"upper": f, "mid": f, "lower": f}
self.get_indicator("mfi")           # → float
self.get_indicator("atr")           # → float
self.get_indicator("adx")           # → float
self.get_indicator("pdi")           # → float（+DI）
self.get_indicator("ndi")           # → float（-DI）
self.get_indicator("macd")          # → {"macd": f, "signal": f}
self.get_indicator("stoch_5_3_3")   # → {"k": f, "d": f}
self.get_indicator("price_position") # → float（0~1，价格在20周期高低区间位置）
self.get_indicator("volume_sma_20") # → float
self.get_indicator("bb_width")      # → float（带宽）
self.get_indicator("bb_width_ratio") # → float（带宽比）
```

#### 跨周期数据

```python
from services.data_factory import get_cache
h4 = get_cache("H4")        # → dict，含 candles + 26 个指标
m30 = get_cache("M30")
h4_ema = h4.get("ema_21")   # → float
h4_candles = h4.get("candles", [])  # → list[Candle]
```

#### 门禁检查

```python
adx_data = strategy.get_adx_data()
gate_buy = strategy.calc_gate_state("BUY", price, adx_data)
gate_sell = strategy.calc_gate_state("SELL", price, adx_data)
```

#### 保本出场

```python
self._check_breakeven_exit(td, current_profit, atr_val, entry, is_buy)
```

#### 利润回撤止盈（基类内置）

通过 `runtime_config` 的 `coordinator` 配置：
```python
self.profit_drawdown_enabled = True   # 是否启用
self.profit_drawdown_pct = 0.25       # 回撤百分比（默认25%）
self.profit_drawdown_min_peak_atr = 0.5  # 最小峰值 ATR
```

### 4.4 可用属性

| 属性 | 类型 | 说明 |
|:----|:----|:------|
| `self.candles` | list[Candle] | 当前周期 K 线数据 |
| `self.bridge` | MT4BridgeBase | 桥接对象（open_order/close_order/modify_order） |
| `self.magic` | int | 策略 Magic Number |
| `self.timeframe` | str | 策略周期 |
| `self._trail_data` | dict | 追踪数据（出场用） |
| `self._last_signal` | dict | 最近一次信号数据 |
| `self._last_exit_detail` | dict | 最近一次出场详情 |

---

## 5. 数据源与指标

### 5.1 数据来源

**DataFactory 是唯一数据来源。** 所有指标通过 `get_indicator(key)` 读取。

**数据来源优先级：**
1. F043 命令（MT4 直接计算）→ 优先
2. TA-Lib 本地计算 → 回退

### 5.2 完整指标表（26 个）

| key | 类型 | 参数 | 说明 |
|:----|:----|:----:|:----|
| `close` | float | — | 最新收盘价 |
| `trend` | str | SMA14 | `"UP"` / `"DOWN"` |
| `rsi` | float | 14 | RSI |
| `rsi_5` | float | 5 | 快速 RSI |
| `rsi_10` | float | 10 | 中速 RSI |
| `mfi` | float | 14 | 资金流量指数 |
| `mfi_direction` | str | — | `"up"` / `"down"` / `"flat"` |
| `bb` | dict | 20,2,2 | `{"upper": f, "mid": f, "lower": f}` |
| `bb_width` | float | — | BB 带宽 |
| `bb_width_direction` | str | — | 带宽方向 |
| `bb_width_ratio` | float | SMA3 | 当前带宽 / 近 3 根均值 |
| `ema_9` | float | 9 | EMA |
| `ema_21` | float | 21 | EMA |
| `sma_14` | float | 14 | SMA |
| `sma_20` | float | 20 | SMA |
| `sma_50` | float | 50 | SMA |
| `atr` | float | 14 | ATR |
| `atr_20` | float | 20 | ATR |
| `atr_list` | list[float] | 14 | ATR 历史序列 |
| `adx` | float | 14 | ADX |
| `pdi` | float | 14 | +DI |
| `ndi` | float | 14 | -DI |
| `macd` | dict | 12,26,9 | `{"macd": f, "signal": f}` |
| `stoch_5_3_3` | dict | 5,3,3 | `{"k": f, "d": f}` |
| `volume_sma_20` | float | 20 | 成交量 SMA |
| `price_position` | float | 20 周期 | 价格在 20 周期高低区间的位置 0~1 |

### 5.3 自定义指标

如果 TA-Lib 指标不够，可以在策略中自算。但**只能用 TA-Lib 函数计算**，不能手动 for 循环。

```python
import numpy as np
import talib

closes = self.get_close_prices()
# 用 TA-Lib 计算
sma = talib.SMA(np.array(closes), timeperiod=10)
```

---

## 6. 出场逻辑体系

### 6.1 三层出场体系

```
check_ema20_exit()
├── ① 趋势出场（穿轨后回抽）
│   BUY: 价格先穿上轨 → 回抽到上轨附近 + MFI>50
│   SELL: 价格先穿下轨 → 回抽到下轨附近 + MFI<50
├── ② 中线出场（价格回到中线）
│   BUY: 价格先跌破中线 → 回到中线以上
│   SELL: 价格先涨过中线 → 回落到中线以下
└── ③ 半宽出场（逆势走了半宽）
    BUY: 价格 >= 入场价 + 半宽
    SELL: 价格 <= 入场价 - 半宽
```

### 6.2 通用出场（基类内置）

| 功能 | 方法 | 触发条件 |
|:----|:----|:---------|
| 保本出场 | `_check_breakeven_exit()` | 盈利走过 ≥0.3×ATR 后回到成本附近 |
| 利润回撤止盈 | `profit_drawdown_pct` | 盈利从最高点回撤超过阈值 |
| ATR 移动止盈 | TrailStop | 价格从最高点回落超过 trail_mult×ATR |
| 硬止损 | HardStop | 亏损超过 hard_mult×ATR |

### 6.3 出场配置

出场参数通过 `runtime_config.json` 的 `coordinator` 配置，支持热重载：

```python
{
  "coordinator": {
    "profit_drawdown_enabled": true,
    "profit_drawdown_pct": 0.25,
    "trail_mult": 1.0,
    "hard_mult": 2.0
  }
}
```

---

## 7. 信号生成规范

### 7.1 评分系统

策略采用**评分制**，而非传统的条件与/或。每个因子独立打分，累加后与阈值比较。

```
score_long = factor1 + factor2 + factor3 + ...
score_short = factor1 + factor2 + factor3 + ...
threshold = 3（可配置）

signal = score_long >= threshold ? BUY : score_short >= threshold ? SELL : None
```

### 7.2 评分标准示例

```
# 因子得分规则
RSI 超卖(<30)  → +1
RSI 极端超卖(<20)  → +2
EMA 金叉 → +1
ADX > 25  → +1（趋势确认）
BB 触及下轨  → +1（超卖反弹）
```

### 7.3 高位拦截（推荐）

价格极端高位时禁止追高做多（但允许做空）：

```python
price_pos = self.get_indicator("price_position")
ema21 = self.get_indicator("ema_21")
atr = self.get_indicator("atr")
if price_pos and ema21 and atr and atr > 0:
    dev = (close - ema21) / atr
    if price_pos > 0.88 and dev > 4.0:
        safe_up = False  # 禁 BUY 追高
    if price_pos < 0.12 and dev < -4.0:
        safe_dn = False  # 禁 SELL 抄底
```

---

## 8. 风控与门禁系统

### 8.1 策略级控制

| 参数 | 说明 | 配置位置 |
|:----|:------|:---------|
| `max_positions` | 策略最大持仓数 | `strategy_pool.{name}.max_positions` |
| `double_first` | 是否双倍首单 | `strategy_pool.{name}.double_first` |
| `enabled` | 是否启用 | `strategy_pool.{name}.enabled` |

### 8.2 全局控制

| 参数 | 说明 |
|:----|:------|
| `max_positions` | 全局总持仓上限（真实模式生效） |
| `safety_lock_timeout_minutes` | 安全锁超时分钟数 |
| `per_strategy_loss_block_hours` | 单策略亏损阻断小时数 |
| `consecutive_loss_cooldown_hours` | 连续亏损冷却小时数 |
| `profit_exit_cooldown_hours` | 盈利平仓冷却小时数 |

### 8.3 门禁（Gate）系统

引擎内置多重门禁，每 tick 自动检查：

- **时间门**：非交易时段禁止开仓
- **波动门**：ATR 低于阈值禁止开仓
- **趋势门**：ADX 低于阈值禁止开仓
- **连续亏损门**：连续亏损 N 次后暂停开仓
- **新闻门**：重大新闻事件前后禁开仓
- **方向门**：MTF 协调器方向限制

---

## 9. 策略模板

### 9.1 完整策略模板

```python
"""
StrategyDisplayName — 简短描述
================================
- 入场逻辑简述
- 出场逻辑简述
数据源: 全部指标从 DataFactory TA-Lib 读取
"""

import logging
from typing import Optional
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "v1"
STRATEGY_MAGIC = 889900
STRATEGY_CHANGELOG = [
    {"version": "v1", "magic": 889900, "date": "2026-08-11",
     "desc": "初始版本"},
]

class MyStrategy(BaseStrategy):
    name = "my_strategy"
    legacy_magics = []

    def __init__(self, bridge, magic=0, timeframe=""):
        super().__init__(bridge, magic, timeframe)
        self.score_threshold = 3
        self.p_hard_atr = 2.0
        self.p_trailing_atr = 1.0
        self.profit_drawdown_pct = 0.25

    # ─── 信号生成 ───────────────────────────────
    def generate_signal(self) -> Optional[tuple]:
        candles = self.candles
        if len(candles) < 50:
            return None

        closes = self.get_close_prices()
        close = closes[-1]

        # 读取指标
        rsi = self.get_indicator("rsi")
        ema21 = self.get_indicator("ema_21")
        bb = self.get_indicator("bb")
        if rsi is None or ema21 is None or bb is None:
            return None

        # 因子打分
        long_score = 0
        short_score = 0
        long_factors = []
        short_factors = []

        # 例：RSI 因子
        if rsi < 30:
            long_score += 1
            long_factors.append("RSI-OS")
        elif rsi > 70:
            short_score += 1
            short_factors.append("RSI-OB")

        # 例：EMA 因子
        if close > ema21:
            long_score += 1
            long_factors.append("EMA-UP")
        else:
            short_score += 1
            short_factors.append("EMA-DN")

        # 判定信号
        signal = None
        if long_score >= self.score_threshold:
            signal = OrderType.BUY
        elif short_score >= self.score_threshold:
            signal = OrderType.SELL

        if signal is None:
            return None

        indicator_values = {
            "close": round(close, 2),
            "rsi": round(rsi, 1),
            "ema21": round(ema21, 2),
        }

        return (signal, long_score, short_score,
                long_factors + short_factors,
                [long_score, short_score],
                indicator_values)

    # ─── 出场逻辑 ───────────────────────────────
    def check_ema20_exit(self, position, bid, ask) -> bool:
        ticket = position.ticket
        is_buy = position.order_type in ("OP_BUY", "BUY")
        bb = self.get_indicator("bb")
        mfi = self.get_indicator("mfi")
        if bb is None or mfi is None:
            return False
        current_price = bid if is_buy else ask

        if ticket not in self._trail_data:
            self._trail_data[ticket] = {
                "entry_price": position.open_price,
                "entry_bb_width": bb["upper"] - bb["lower"],
                "entry_bb_mid": bb["mid"],
                "is_buy": is_buy,
                "has_crossed_band": False,
                "has_crossed_mid": False,
            }
        td = self._trail_data[ticket]

        # ① 趋势出场：穿轨后回抽
        if is_buy:
            if not td["has_crossed_band"] and bid > bb["upper"]:
                td["has_crossed_band"] = True
            if td["has_crossed_band"] and bid <= bb["upper"] + 0.01 and mfi > 50:
                self._trail_data.pop(ticket, None)
                return True
        else:
            if not td["has_crossed_band"] and ask < bb["lower"]:
                td["has_crossed_band"] = True
            if td["has_crossed_band"] and ask >= bb["lower"] - 0.01 and mfi < 50:
                self._trail_data.pop(ticket, None)
                return True

        # ② 中线出场：先越过中线再返回
        _mid = td["entry_bb_mid"]
        if is_buy:
            if not td.get("has_crossed_mid"):
                if current_price <= _mid:
                    td["has_crossed_mid"] = True
            elif current_price >= _mid:
                self._trail_data.pop(ticket, None)
                return True
        else:
            if not td.get("has_crossed_mid"):
                if current_price >= _mid:
                    td["has_crossed_mid"] = True
            elif current_price <= _mid:
                self._trail_data.pop(ticket, None)
                return True

        # ③ 半宽出场
        half_width = td["entry_bb_width"] / 2
        if is_buy:
            if current_price >= td["entry_price"] + half_width:
                self._trail_data.pop(ticket, None)
                return True
        else:
            if current_price <= td["entry_price"] - half_width:
                self._trail_data.pop(ticket, None)
                return True

        return False

    # ─── 入场验证（可选）───────────────────────
    @staticmethod
    def _verify_entry(signal: dict, tick_price: float, latest: dict, item: dict = None) -> bool:
        """tick 验证入场条件（可选，默认通过）"""
        return True
```

### 9.2 策略文档模板

每个策略必须有对应的策略说明文档 `docs/strategies/{name}.md`：

```markdown
---
name: my_strategy
magic: 889900
type: 趋势/反转/评分/ML
display: MyStrategy — 示例策略
desc: 策略简述（中文）
desc_en: Strategy brief description (English)
---

## 评分因子

### BUY（做多）
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | RSI 超卖 | +1 | RSI < 30 |
| ② | EMA 向上 | +1 | 收盘价 > EMA21 |

### SELL（做空）
| # | 因子 | 得分 | 说明 |
|:-:|:----|:----:|:----|
| ① | RSI 超买 | +1 | RSI > 70 |
| ② | EMA 向下 | +1 | 收盘价 < EMA21 |

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:------|
| ① | 趋势出场 | 穿轨后回抽 + MFI 确认 |
| ② | 中线出场 | 价格先越过中线再返回 |
| ③ | 半宽出场 | 逆势走了入场时 BB 宽度的一半 |

数据源: 全部指标从 DataFactory TA-Lib 读取
```

---

## 10. MQL4/MQL5 移植指南

### 10.1 核心概念对照

| MQL4 概念 | 本系统对应 | 说明 |
|:----------|:----------|:------|
| `OnTick()` | `on_tick()` → `generate_signal()` | 事件驱动 → 评分制 |
| `iRSI()` | `self.get_indicator("rsi")` | 指标读取 |
| `iMA()` | `self.get_indicator("ema_21")` | 均线指标 |
| `iBands()` | `self.get_indicator("bb")` | 布林带 |
| `iADX()` | `self.get_indicator("adx")` | ADX |
| `iStochastic()` | `self.get_indicator("stoch_5_3_3")` | 随机指标 |
| `iMACD()` | `self.get_indicator("macd")` | MACD |
| `iCustom()` | 需手动计算 | 自定义指标需要移植到 Python |
| `OrderSend()` | `self.bridge.open_order()` | 开仓 |
| `OrderClose()` | 引擎自动调用 | 平仓通过出场逻辑触发 |
| `OrderModify()` | `self.bridge.modify_order()` | 修改止损止盈 |
| `OrderSelect()` | 遍历 `self.candles` | 选择订单 |
| `OrdersTotal()` | `filter_positions()` | 获取持仓总数 |
| `OrderStopLoss()` | `position.stop_loss` | 止损价 |
| `OrderTakeProfit()` | `position.take_profit` | 止盈价 |
| `Close[0]` | `self.candles[-1].close` | 当前收盘价 |
| `High[0]` | `self.candles[-1].high` | 当前最高价 |
| `Low[0]` | `self.candles[-1].low` | 当前最低价 |
| `Volume[0]` | `self.candles[-1].volume` | 当前成交量 |
| `Time[0]` | `self.candles[-1].time` | 当前时间戳 |

### 10.2 移植步骤

```
1. 分析 MQL4 策略逻辑，拆分为：入场条件 × 出场条件 × 风控
2. 入场条件 → generate_signal() 评分系统
3. 出场条件 → check_ema20_exit() 出场逻辑
4. 风控 → 利用系统内置的门禁/风控
5. 指标替换：MQL4 的 iXXX → 系统的 get_indicator()
6. 订单管理：去掉 OrderSend/OrderClose，由系统自动处理
```

### 10.3 移植注意事项

1. **MQL4 的 OnTick 是每 tick 调用**，本系统的 `on_tick` 也是每 tick 调用，但信号生成只在 K 线收盘时触发（内部处理）
2. **MQL4 的 iCustom 指标**需要手动移植到 Python（用 TA-Lib 或 numpy 实现）
3. **MQL4 的硬止损**通过 `modify_order()` 设置，本系统通过 `check_ema20_exit` 的硬止损逻辑触发
4. **MQL4 的挂单**（Pending Order）本系统暂不支持
5. **MQL4 的多个品种**本系统当前只支持 XAUUSD

### 10.4 移植示例：MQL4 → Python

**MQL4 代码：**
```mql4
void OnTick() {
    double rsi = iRSI(NULL, 0, 14, PRICE_CLOSE, 0);
    double ema = iMA(NULL, 0, 21, 0, MODE_EMA, PRICE_CLOSE, 0);
    
    if (rsi < 30 && Close[0] > ema && OrdersTotal() == 0) {
        OrderSend(Symbol(), OP_BUY, 0.01, Ask, 3, 
                  Ask - 200 * Point, Ask + 400 * Point, "", Magic, 0, clrBlue);
    }
}
```

**移植后的 Python 代码：**
```python
def generate_signal(self) -> Optional[tuple]:
    rsi = self.get_indicator("rsi")
    ema21 = self.get_indicator("ema_21")
    close = self.candles[-1].close
    if rsi is None or ema21 is None:
        return None
    
    if rsi < 30 and close > ema21:
        return (OrderType.BUY, 1, 0, ["RSI-OS", "EMA-UP"], [1], {})
    return None

def check_ema20_exit(self, position, bid, ask) -> bool:
    # 出场逻辑（硬止损 + 追踪止盈）
    ...
```

---

## 11. 测试与调试

### 11.1 纸面测试

系统内置纸面测试模式，新策略先在纸面模式下运行：

```bash
# 纸面模式运行
python tools/paper_trader.py

# 查看纸面记录
cat papertest/papertest_bridge.csv
```

### 11.2 回测

```bash
python scripts/backtest_6months.py --months=3
python -c "import json; r=json.load(open('data/evaluation/backtest_report.json')); ..."
```

### 11.3 日志调试

策略日志通过 `logger.info()` 输出，可在 `logs/backend.log` 中查看：

```python
logger.info(f"[{self.name}] RSI={rsi:.1f} EMA={ema21:.2f} Score={long_score}/{self.score_threshold}")
```

### 11.4 策略中心

在 Dashboard → 策略中心，可查看：
- 策略的实时评分和因子
- 门禁状态
- 持仓和成交记录

---

## 12. 常见问题

### Q: 策略文件命名规则是什么？
A: `{策略名}_{日期}.py`，如 `my_strategy_20260811.py`。策略名全小写+下划线。

### Q: Magic Number 怎么分配？
A: 每个策略唯一 Magic。已分配范围：660000-880999。新策略从 889000 开始分配。

### Q: 策略参数怎么热更新？
A: 策略参数在 `__init__` 中设置，修改后重启引擎生效。风控参数通过 `runtime_config.json` 配置，支持热重载。

### Q: 怎么添加自定义指标？
A: 在策略中直接用 TA-Lib 计算，或用 `self.get_close_prices()` 获取收盘价数组后自行计算。

### Q: 策略可以同时运行在多个周期吗？
A: 可以，注册多个策略实例，每个实例指定不同的 `timeframe`。

### Q: 策略出现异常怎么办？
A: 引擎会捕获异常并记录日志，不会影响其他策略。建议在 `generate_signal()` 中使用 try-except 兜底。

---

数据源: 全部指标从 DataFactory TA-Lib 读取