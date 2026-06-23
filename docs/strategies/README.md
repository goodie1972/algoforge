# 实盘策略文档

该目录包含各活跃交易策略的详细技术文档。

## 策略一览

| 策略 | 文件 | 周期 | Magic | 状态 | 入场方式 |
|------|------|------|-------|------|---------|
| [M30 RSI + 布林带](m30_rsi_bb.md) | `strategies/m30_rsi.py` | M30 | 660706 | ✅ 启用 | 评分≥3 + H1 趋势门控 |
| [Stoch Trend M30](stoch_trend_m30.md) | `strategies/stoch_trend_m30.py` | M30 | 660903 | ✅ 启用 | 三模自适应（窄幅/宽幅/趋势） |
| [RSI 分级评分 M30](rsi_grading_m30.md) | `strategies/rsi_grading_m30.py` | M30 | 660902 | ✅ 启用 | 因子评分 + ADX 阈值提升 |
| [SanQing H1](sanqing_h1.md) | `strategies/sanqing_h1.py` | H1 | 880107 | ✅ 启用 | 6 因子评分 ≥5（ADX>25降为4） |
| [Gold Auto Research](gold_auto_research.md) | `strategies/gold_autoresearch_h1.py` | H1 | 880306 | ✅ 启用 | 四维度全票通过 |
| [MTF 共振 H1](mtf_resonance_h1.md) | `strategies/mtf_resonance_h1.py` | H1 | 660801 | ✅ 启用 | 多周期信号共振 |

## 停用策略

| 策略 | Magic | 说明 |
|------|-------|------|
| H1 V6 混合 | 660607 | 已下架，602 笔回测亏损 $166 |
| Stoch M30 | 660901 | 被 stoch_trend_m30 取代 |
| Bakome 备用 | 777004 | 备用，未启用 |
| XAUBot 备用 | 777005 | 备用，未启用 |

## 共同架构

所有策略共享以下核心特性：

- **三层退出体系** — 利润回撤止盈 + ATR 移动止盈 + ATR 硬止损
- **趋势感知出场乘数** — 顺势宽松（trail=2.5, hard=4.0）、逆势收紧（trail=1.0, hard=2.0）
- **盈利/亏损分离** — 盈利时全退出策略、亏损时仅硬止损
- **新闻收紧模式** — 高影响新闻事件前自动收紧出场参数
- **持仓位门控** — 60 根 K 线区间上下 10% 限制逆势开仓
- **策略池热同步** — 引擎自动识别配置变更，无需重启
