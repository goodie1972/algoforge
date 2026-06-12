# XAUUSD 量化交易系统

基于 Python + MetaTrader 4 的黄金自动化交易系统，支持多策略并行、多层风控、实时 Web 监控。

## 架构概览

```
MT4 + FreeMT4Bridge EA (Socket :23232)
        │
    core/bridge.py (桥接抽象层)
        │
    TradingEngine (引擎主循环)
        ├── M30_rsi_bb       (M30 均值回归)
        ├── H1_v6_hybrid     (H1 多因子混合)
        ├── sanqing_h1       (H1 EMA9/21 趋势)
        └── gold_auto_research (H1 共识投票)
        │
    Dashboard (FastAPI + Vue 3)
        │
    monitor/patrol_daemon.py (独立巡检)
```

## 核心特性

- **多策略并行** — 4 个独立策略同时运行，独立 Magic Number 和风控状态
- **三层退出体系** — 利润回撤止盈 + ATR 移动止盈 + ATR 硬止损，趋势感知乘数
- **信号生命周期** — 从信号生成→开仓→平仓的全链路追踪，含废票管理
- **持仓位门控** — 60 根 K 线高低 10% 范围内限制逆势开仓
- **多策略协调器** — 跨策略联动出场 + M15 EMA20 斜率归一化反向止盈
- **新闻保护** — 集成 ForexFactory 财经日历，三级新闻防护（收紧→强平→黑名单）
- **十层风控** — 全局硬止损、浮动/已实现亏损阻断、快速出场检测、连续亏损冷却、安全锁
- **实时 Web 仪表盘** — 价格图表、持仓管理、信号日志、策略统计、运行时配置
- **策略版本管理** — Magic Number 标准化（PP+NN+VV），结构化 Changelog 写入数据库
- **独立巡检守护** — 独立进程 30 秒轮询，异常自动告警

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
