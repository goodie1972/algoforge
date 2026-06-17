# XAUUSD 量化交易系统 — 变更日志

> 此文件为**人工整理的里程碑日志**，Dashboard 顶部的版本徽章会自动从 `git log` 拉取最新 commit。
> 格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.5.0] - 2026-06-17

### 新增
- **News-Bias 预判报告系统**：5 大影响变量（通胀/利率政策/地缘政治/美元/央行购金）逻辑链分析，8:00 + 20:00 自动生成
- **版本追踪系统**：`VERSION` 文件 + `core/version.py` + Dashboard 徽章 + 自动 changelog 弹窗
- Dashboard 顶部版本徽章，点击查看最近 20 条 commit
- `start.py` 启动横幅显示 `v0.5.0 (commit) branch=main build=...`

### 改进
- sanqing_h1 v7：逆势 RSI-OB/OS + PRICE-HIGH/LOW 评分
- 修复 K线主图与指标窗格同步跳变
- M5 reverse TP 配置移除（保留 M15 + 灵敏度）
- 实时盈亏改用价格轮询器重算（不再依赖 MT4 滞后值）
- voided 信号标签："升级前记录" / "历史记录" 区分
- voided 列表布局：列宽收紧、字号加大、关键值加粗
- 优雅退出：非 daemon 线程 + taskkill 先 graceful

### 修复
- MT4 硬止损平仓后下一 tick 立即触发 recover
- 自动滚动循环：避免程序化 range 变更事件
- K线实时更新：使用 BID 而非 midPrice
- 价格采样放到独立 daemon 线程（0.1s 间隔）
- 安全锁文件路径错误

## [0.4.0] - 2026-06-08

### 新增
- **信号生命周期管理系统**：today / voided / opened 三态分类
- **交易同步监管**：轻量 1 小时自检 + 5 分钟自动 recover
- **K线实时缓存 + 价格延伸最后一根 K 线**
- 仓位展开行（Dashboard 终端）

### 改进
- 价格采样提升至 0.1s，WebSocket 广播 0.3s
- K线使用 BID 更新 H/L/C
- K线 10s 无操作后自动滚到实时

---

## 早期版本
- v0.3.x — M30_rsi_bb v5 + H1_v6_hybrid v6 仓位门控
- v0.2.x — 多策略 H1 共振信号框架
- v0.1.x — 单策略 MVP + MT4 桥接
