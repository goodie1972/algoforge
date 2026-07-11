# XAUUSD 量化交易系统

基于 Python + MetaTrader 4 的黄金自动化交易系统，支持多策略并行、多层风控、实时 Web 监控、纸面测试。

## 架构概览

```
MT4 + FreeMT4Bridge EA (Socket :23232)
        │
    core/bridge.py (桥接抽象层)
        │
    TradingEngine (引擎主循环 — 三轨架构)
        ├── 轨1: DataFactory (独立线程拉K线+TA-Lib计算指标)
        ├── 轨2: 策略员 (主循环评分出门票)
        └── 轨3: Athlete (tick验证+开仓)
        │
    Dashboard (FastAPI + Vue 3)
        │
    tools/ (监控+纸面测试+分析)
        ├── status_monitor.py (每5分钟检查+自动修复)
        ├── signal_analysis_recorder.py (信号全指标记录)
        ├── paper_trader.py (纸面交易模拟)
        └── weekly_analysis.py (周分析报告)
```

## 当前运行策略 (7个)

| 策略 | Magic | 周期 | 说明 |
|:-----|:-----:|:----:|:-----|
| sanqing_h1 | 880107 | H1 | 6因子评分 ≥5, ATR动态追踪 |
| sanqing_h1_original | 880101 | H1 | 原始v1还原(阈值5, trail=4.0 hard=2.5) |
| stoch_trend_h1_optimized | 661202 | H1 | 优化版: Stoch(14,3,3)+评分制 |
| mfi_bb_m30_optimized | 661002 | M30 | 优化版: 容差2根, MFI 85/15 |
| m30_bb_deepreturn_optimized | 661102 | M30 | 优化版: 阈值2+ADX动态 |
| rsi_grading_m30_optimized | 660903 | M30 | 优化版: ADX≤28阈值=2 |
| bakome_backup_optimized | 777006 | H1 | 优化版: 时段10h+FVG放宽 |

## 核心特性

- **多策略并行** — 7个独立策略同时运行，独立 Magic Number 和风控状态
- **三轨架构** — DataFactory(数据)+ 策略员(信号)+ Athlete(开仓)
- **三层退出体系** — 利润回撤止盈 + ATR 移动止盈 + ATR 硬止损
- **信号全生命周期** — 从信号生成→开仓→平仓的全链路追踪
- **纸面测试系统** — 信号全量模拟入场+出场，按策略规则模拟平仓
- **状态监控+自修复** — 每5分钟检查，引擎崩溃/桥接断连自动重启
- **更多特性**见下方

## 快速开始

```bash
# 一键启动（端口清理 + 后端 + 引擎）
python start.py

# 或直接启动（引擎在 lifespan 中自动启动）
python dashboard/backend/main.py
```

前置条件：MT4 已安装并登录，FreeMT4Bridge EA 已加载到 XAUUSD 图表。

## 技术栈

| 层 | 技术 |
|----|------|
| 桥接 | FreeMT4Bridge EA (MQL4) + TCP Socket |
| 引擎 | Python 3.10+ |
| 后端 | FastAPI + WebSocket |
| 前端 | Vue 3 + TypeScript + Vite + Naive UI |
| 数据库 | SQLite (market_data.db) |
| 图表 | lightweight-charts |
