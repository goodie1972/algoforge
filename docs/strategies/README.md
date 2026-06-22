# 实盘策略文档

该目录包含各活跃交易策略的详细技术文档。

## 策略一览

| 策略 | 文件 | 周期 | Magic | 类型 | 入场方式 |
|------|------|------|-------|------|---------|
| [M30 RSI + 布林带](m30_rsi_bb.md) | `strategies/m30_rsi.py` | M30 | 660706 | 均值回归 | 5 因子评分 ≥3 + H1 趋势门控 |
| [Stoch Trend M30](stoch_trend_m30.md) | `strategies/stoch_trend_m30.py` | M30 | 660903 | 双模震荡/趋势 | 窄幅K/D交叉、宽幅触轨+DI |
| [SanQing H1](sanqing_h1.md) | `strategies/sanqing_h1.py` | H1 | 880107 | 趋势跟踪 | 6 因子评分 ≥5 |
| [H1 V6 混合](v6_hybrid.md) | `strategies/v6_hybrid.py` | H1 | 660607 | 多因子混合 | 8 因子评分 ≥3 |
| [Gold Auto Research](gold_auto_research.md) | `strategies/gold_autoresearch_h1.py` | H1 | 880306 | 共识投票 | 四维度全票通过 |

## 共同架构

所有策略共享以下核心特性：

- **三层退出体系** — 利润回撤止盈 + ATR 移动止盈 + ATR 硬止损
- **趋势感知出场乘数** — 顺势宽松、逆势收紧
- **盈利/亏损分离** — 盈利时全退出策略、亏损时仅硬止损
- **新闻收紧模式** — 高影响新闻事件前自动收紧出场参数
- **热重载支持** — 运行时通过 `reload_config()` 刷新参数

## 出场逻辑标准实现

详见 [产品手册](../product_manual.md#62-三层退出体系) 的出场逻辑说明。
