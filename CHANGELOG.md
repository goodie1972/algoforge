# XAUUSD 量化交易系统 — 变更日志

> 此文件为**人工整理的里程碑日志**，Dashboard 顶部的版本徽章会自动从 `git log` 拉取最新 commit。
> 格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [2.4.9] - 2026-08-08 — 策略优化 + 周末休市检查 + 策略池清理

### 新增
- **周末休市检查**：`_is_market_open()` 引擎级阻断，周六全天 + 周日07:00前 + 周六05:00前自动跳过开仓
- **rsi_grading_m30_upgraded 优化**：恢复ADX>28趋势门禁，新增ADX>25趋势加分（+1）

### 修改
- **sanqing_h1_upgraded 优化**：评分阈值3→5，ADX阈值20→25，硬止损1.5→1.2ATR
- **策略池调整**：禁用 `rsi_grading_m30_optimized`（40%胜率-28），启用 `rsi_grading_m30_upgraded`（76%+231）
- **纸面持仓清零**：清除全部未平仓持仓，余额重置至5000，备份CSV

### 策略池最终状态（7个启用）
- `gold_auto_research`（核心，100%胜率）
- `h1_breakout`（核心，趋势突破）
- `m30_bb_deepreturn_optimized`（核心，93%胜率+380）
- `mfi_bb_m30_upgraded`（重新评估，+300净利PF=2.21）
- `rsi_grading_m30_upgraded`（优化版，76%胜率+231）
- `sanqing_h1`（原版，87.7%胜率+91）
- `sanqing_h1_upgraded`（优化版，评分门槛提高止损收紧）

## [2.4.8] - 2026-08-07 — 交易终端指标显示大修

### 修复
- **ADX 副图修复**：`calcADX` 中 adx 与 pdi/ndi 长度不同导致 offset 越界，分别计算偏移量
- **DI 独立副图**：±DI 从 ADX 副图分离为独立 DI 副图（红绿正负柱状图），`applyDI()` 使用 `addHistogramSeries`
- **BBI 副图 + A 价格线**：BBI 改回独立副图，同花顺风格（BBI 紫色实线 + A 收盘价黄色虚线）
- **MFI/BBI 加入周期预设**：各周期切换时自动应用默认指标
- **数据对齐**：`padLinePoints` 补齐 ADX/DI 数据到与 K 线等长，解决时间轴错位
- **清理残留**：`clearAllPanes` 同时清理 `paneSeries` 对象，防止切换周期后跳过 series 创建
- **i18n 修复**：嵌套双花括号占位符 `{{period}}` → `{period}`

## [2.1.0] - 2026-07-11 — 纸面测试+策略优化

### 新增
- **纸面测试系统** — `tools/paper_trader.py` 持续监控信号，按策略规则模拟入场+出场
- **信号全指标记录器** — `tools/signal_analysis_recorder.py` 记录每次信号的完整因子/评分/指标
- **状态监控+自修复** — `tools/status_monitor.py` 每5分钟检查引擎/桥接/数据工厂，自动重启
- **策略颜色自动分配** — `utils/strategyColors.ts` 策略名哈希定色相，同色系深浅
- **周分析脚本** — `tools/weekly_analysis.py` 自动生成按策略/方向/出场原因的完整分析报告
- **papertest/ 目录** — 纸面测试数据归档，含excel报表、CSV记录、分析报告

### 策略优化
- **mfi_bb_m30 → mfi_bb_m30_optimized**: 容差3→2根，MFI 80/20→85/15，新magic 661002
- **m30_bb_deepreturn → m30_bb_deepreturn_optimized**: 阈值3→2，ADX动态阈值，新magic 661102
- **stoch_trend_h1 → stoch_trend_h1_optimized**: Stoch(21,5,3)→(14,3,3)，ADX阈值25→20，AND→评分制
- **rsi_grading_m30 → rsi_grading_m30_optimized**: ADX≤28阈值保持2(不再升3)，RSI阈值放宽
- **bakome_backup → bakome_backup_optimized**: 交易时段6h→10h，FVG放宽
- **sanqing_h1_original**: 从git还原v1原始版(阈值5, trail=4.0) 作为对比基准

### 修复
- 数据工厂从未启动，导致半数策略无法获取指标
- stoch_trend_h1 缺 _calc_ema 方法导致主循环崩溃
- K线接口超时30秒（先试SQLite回退再走桥接）
- 信号记录器多进程冲突
- scanner缓存导致Athlete使用旧版_verify_entry

## [2.0.1] - 2026-07-06 — K线+引擎修复

### 修复
- K线时间轴偏移3h（engine_runner缓存未扣除MT4偏移）
- K线"暂无数据"（axios问题改为原生fetch）
- Value is null控制台报错（深拷贝+数据有效性校验）
- K线收盘价与价格栏不同步（WebSocket tick驱动update）

## [0.5.0] - 2026-06-17

### 新增
- **News-Bias 预判报告系统**：5 大影响变量（通胀/利率政策/地缘政治/美元/央行购金）逻辑链分析，8:00 + 20:00 自动生成
- **版本追踪系统**：`VERSION` 文件 + `core/version.py` + Dashboard 徽章 + 自动 changelog 弹窗
- Dashboard 顶部版本徽章，点击查看最近 20 条 commit
- `start.py` 启动横幅显示 `v0.5.0 (commit) branch=main build=...`

### 改进
- sanqing_h1 v6r：回退v6纯顺趋势逻辑，去掉逆势因子；顺趋势出场加宽至trail=2.5 hard=4.0
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
