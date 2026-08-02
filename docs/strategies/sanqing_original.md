---name: sanqing_original
magic: 880201

type: 组合
display: Sanqing Original — 三清 M5 4策略调度器
desc: 原始 sanqing-ea 移植，M5 4策略优先级调度（ExpansionFollow > Pullback > TrendContinuation > PinbarReversal）---

## 原始出处

- **GitHub:** [caoruihua/sanqing-ea](https://github.com/caoruihua/sanqing-ea)
- **语言:** MQL4 (MT4) → Python 移植
- **作者:** caoruihua
- **说明:** 一个完整的 M5 4 策略调度器，核心文件为 `StrategySelector.mq4`，包含 4 个策略模块按优先级逐级判断，同一根 K 线只出一个信号。

## 策略架构

### 4 策略优先级调度

| 优先级 | 策略 | 方法 | 说明 |
|:-----:|:----|:----|:----|
| 1 (最高) | ExpansionFollow | `_strategy_expansion_follow()` | 极端放量跟随：实体/ATR≥4.0 + 实体/中位数≥2.20 + 成交量/中位数≥1.9 + 实体/范围≥0.65 |
| 2 | Pullback | `_strategy_pullback()` | EMA回踩拒绝：EMA9>21 时价格回踩EMA9附近出现的下影线拒绝信号 |
| 3 | TrendContinuation | `_strategy_trend_continuation()` | 趋势延续突破：EMA9>21 时收盘突破前高+0.2×ATR |
| 4 (最低) | PinbarReversal | `_strategy_pinbar_reversal()` | PinBar反转：前置波动≥PinBar的3倍+影线≥2×实体+对侧影线≤0.5×实体 |

### 调度规则

- 从 ExpansionFollow → PinbarReversal 逐级检查
- 任一策略产生有效信号立即返回，不再检查后续策略
- 同一根 M5 K 线只处理一次（`_last_processed_bar_time` 去重）
- 日风控锁定后禁止所有交易

## 入场逻辑

### 所有策略通用

- 时间框架: **M5**
- 基出指标: EMA9/21, ATR14
- 低波动过滤: ATR<300points 或 ATR/Spread<3 时不出手
- 日风控: 日盈利≥$50 或 日亏损≥$40 或 日交易≥30 次锁定

## 出场逻辑

| # | 条件 | 说明 |
|:-:|:----|:----|
| ① | 固定止损 | 1.2×ATR |
| ② | 固定止盈 | 2.0×ATR |
| ③ | 日风控 | 日盈利$50/日亏损$40锁定，次日重置 |

## 特别规则

- 冷却期: 盈利平仓后 300 秒内同方向不再开仓
- 日风控锁定后所有交易暂停，到次日重置
- 数据源: 全部指标从 DataFactory TA-Lib 读取