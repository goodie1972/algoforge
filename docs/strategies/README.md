# 实盘策略文档

该目录包含各活跃交易策略的详细技术文档。

## 当前运行策略 (2026-07-11)

| 策略 | 文件 | 周期 | Magic | 状态 | 说明 |
|------|------|:----:|:-----:|:----:|------|
| [SanQing H1](sanqing_h1.md) | `sanqing_h1_20260630.py` | H1 | 880107 | ✅ 活跃 | 6因子评分 ≥5，ATR动态追踪 |
| SanQing H1 original | `sanqing_h1_original_20260711.py` | H1 | 880101 | ✅ 活跃 | 原始v1还原(阈值5, trail=4.0) |
| Stoch Trend H1 opt | `stoch_trend_h1_optimized_20260711.py` | H1 | 661202 | ✅ 活跃 | Stoch(14,3,3)+评分制 |
| MFI+BB opt | `m30_mfi_bb_optimized_20260711.py` | M30 | 661002 | ✅ 活跃 | 容差2根, MFI 85/15 |
| BB DeepReturn opt | `m30_bb_deepreturn_optimized_20260711.py` | M30 | 661102 | ✅ 活跃 | 阈值2+ADX动态 |
| RSI Grading opt | `rsi_grading_m30_optimized_20260711.py` | M30 | 660903 | ✅ 活跃 | ADX≤28阈值=2 |
| Bakome Backup opt | `bakome_backup_optimized_20260711.py` | H1 | 777006 | ✅ 活跃 | 时段10h+FVG放宽 |

## 已停止策略

| 策略 | 被取代 | 原因 |
|------|--------|------|
| stoch_trend_h1 (v6, 661201) | stoch_trend_h1_optimized | AND逻辑太严，一周仅8信号 |
| mfi_bb_m30 (v5, 661001) | mfi_bb_m30_optimized | 容差3根偏宽 |
| m30_bb_deepreturn (v2, 661101) | m30_bb_deepreturn_optimized | 阈值3导致出单太少 |
| rsi_grading_m30 (v5, 660902) | rsi_grading_m30_optimized | 一周0信号(ADX≤28阈值升到3) |
| bakome_backup (v1, 777004) | bakome_backup_optimized | 时段仅6h+FVG太严 |
| gold_auto_research (880306) | ❌ 关闭 | 一周亏-$8,554 |
| viprasol_sniper (661401) | ❌ 关闭 | 一周亏-$6,825 |
| v6_hybrid (660607) | 已下架 | 602笔回测亏损$166 |
| entry_score_pro (661501) | 已关闭 | UI中禁用 |
| momentum_pulse_pro (661301) | 已关闭 | UI中禁用 |
| multi_confluence_quant (661601) | 已关闭 | UI中禁用 |
| xaubot_backup (777005) | 已关闭 | UI中禁用 |

## 共同架构

所有策略共享以下核心特性：

- **三层退出体系** — 利润回撤止盈 + ATR 移动止盈 + ATR 硬止损
- **趋势感知出场乘数** — 顺势宽松（trail=2.5, hard=4.0）、逆势收紧（trail=1.0, hard=2.0）
- **盈利/亏损分离** — 盈利时全退出策略、亏损时仅硬止损
- **新闻收紧模式** — 高影响新闻事件前自动收紧出场参数
- **策略池热同步** — 引擎自动识别配置变更，无需重启
- **纸面测试** — `tools/paper_trader.py` 记录全量信号+模拟出场
