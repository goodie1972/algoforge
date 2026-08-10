# XAUUSD 量化交易系统 — 变更日志

> 此文件为**人工整理的里程碑日志**，Dashboard 顶部的版本徽章会自动从 `git log` 拉取最新 commit。
> 格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [2.7.7] - 2026-08-10 — 日志双语化 + 策略全英文化 + 黄金快讯修复

### 新增
- **中英双语日志模板库**：`services/log_messages.py` 80+ 模板，运行时按 `runtime_config.language` 自动选择
- **日志语言跟随前端 locale**：切换语言时自动通知后端，日志即时切换
- **策略文件全覆盖**：31 个策略文件 logger 消息中文→英文

### 修复
- **黄金快讯标签方向**：3 处硬编码标签改为根据 direction 动态显示（利多/利空/中性）
- **语言切换键文字**：英文环境显示"中文"而非"Chinese"
- **黄金快讯英文翻译回填**：20 条历史快讯用 LLM 补全 content_en

### 文档
- **CLAUDE.md** 新增纪律规则：先确认再说话，不凭猜测作答

## [2.7.6] - 2026-08-09 — 新闻快讯 LLM 自动翻译 + 英文显示

### 新增
- **LLM 自动翻译**：`judge_with_llm` prompt 同时输出方向 + 英文翻译，gold_news 表加 `content_en` 字段
- **前端语言切换**：英文模式下黄金快讯显示 LLM 翻译后的英文，中文模式显示原文

### 修复
- **i18n 硬编码中文**：跑马灯、黄金快讯、快捷键等由中文改为 i18n key，支持中英文切换

## [2.7.4] - 版本号进位（24 个 patch 进 1 位）

### 说明
- 由于 2.5.x 连续 24 个小版本，将版本号进位为 2.7.4，包含 2.5.1~2.5.24 的全部改动

## [2.5.24] - 黄金快讯 Modal 字体放大

### 修改
- 黄金快讯完整 Modal 字体放大 50%（正文 12px→18px，来源/时间 11px→16px）

## [2.5.23] - 黄金快讯字体放大 + 放大按钮

### 修改
- 黄金快讯卡片字体放大，放大按钮点击后弹窗内字体 22px

## [2.5.22] - 跑马灯宽度扩大 + 速度降低

### 修改
- 经济日历跑马灯宽度扩大 50%，滚动速度降低 30%

## [2.5.21] - 跑马灯速度减半

### 修改
- 经济日历跑马灯滚动周期 20s → 40s

## [2.5.20] - 跑马灯拉长 + 信息增强

### 修改
- 跑马灯拉长一倍，显示信息增强（日期时间、名称（含中文翻译）、前值、预测）

## [2.5.19] - 跑马灯移到顶部栏

### 修改
- 经济日历跑马灯移到 app-header 顶部栏，和版本号同一水平位置

## [2.5.18] - 跑马灯独立显示

### 修改
- 跑马灯移到最顶部，在仪表板旁边

## [2.5.17] - 跑马灯独立显示在仪表板旁边

### 修改
- 经济日历跑马灯独立显示在实盘信号仪表板旁边

## [2.5.16] - 经济日历跑马灯 + 黄金快讯 5 条 + Modal 75%

### 新增
- 经济日历跑马灯放在顶部
- 黄金快讯卡片显示 5 条
- 放大窗口 Modal 75%×75%

## [2.5.15] - 黄金快讯窗口改为 Modal

### 修改
- 黄金快讯窗口改为居中 Modal（60%×60%）

## [2.5.14] - 黄金快讯卡片加放大按钮

### 新增
- 黄金快讯卡片加放大按钮，向左弹出完整列表窗口

## [2.5.13] - 新增黄金快讯评估卡片

### 新增
- Dashboard 右侧面板新增黄金快讯评估卡片

## [2.5.12] - 彻底删除旧新闻系统

### 删除
- `services/news_bias.py`、`services/news_fetcher.py`、`services/news_bias_reviewer.py`
- 旧 `routes/news_bias.py`、`routes/news_review.py`
- 前端 `NewsBiasPopup.vue`、`ReportView.vue` 的 news_bias tab
- `main.py` 的 `news_bias_loop` WebSocket 推送

### 改造
- `core/bias_state.py` 改为从 `news_filter.get_current_bias` 读取 gold_news 方向

## [2.5.11] - 模型栏改为下拉选择器

### 修改
- AI Agent 卡片模型栏改为下拉选择器，测试连接后列出可选模型

## [2.5.10] - 卡片边框加粗 + 点击放大

### 修改
- AI Agent 卡片边框加粗，点击弹出 Modal 放大编辑

## [2.5.9] - AI Agent 卡片优化

### 修改
- 网格卡片 + 无头像 + API Key 眼睛切换显示

## [2.5.8] - AI Agent 卡片优化

### 修改
- 透明背景 + 边框，点击放大编辑

## [2.5.7] - LLM 配置改为卡片形式

### 新增
- LLM 配置改为卡片形式，预置 4 个卡片（DeepSeek/Agnes/GLM5.2/Mimo）

## [2.5.6] - LLM 配置支持环境变量

### 新增
- LLM 配置支持环境变量 + `.env` 文件

## [2.5.5] - 新增黄金快讯评估 + 准确性统计

### 新增
- 黄金快讯评估 API + 准确性统计 API

## [2.5.4] - 删除旧新闻数据 + 黄金快讯 API

### 修改
- 删除旧新闻数据，新增黄金快讯 API 端点

## [2.5.3] - 新闻系统全面改造

### 修改
- **弃用 ForexFactory**，改用汇通 + 金十 + LLM 方向判断

## [2.5.2] - 新闻分析逻辑全面优化

### 修复
- 预期差逻辑 + 修复 NFP 冲突

## [2.5.1] - 全局总持仓上限 + 策略优化

### 新增
- 全局总持仓上限检查（真实模式生效）

### 修改
- M30_rsi_bb 优化：score_threshold=5, hard_atr=1.2, trailing_atr=1.5
- stoch_trend_h1_optimized 优化：adx_threshold=25, sl_atr=1.2

## [2.5.0] - 2026-08-08 — 全量 i18n 国际化 + 配置布局优化

### 新增
- **全量 i18n 国际化**：所有 14 个 Vue 组件完成国际化，中文/英文 833 键同步，覆盖全部按钮、标签、说明、反馈
- **RiskConfig 三列布局**：保持两栏结构，每栏内部每行 3 个字段排列，减少垂直滚动

### 修改
- **配置输入框宽度**：风控参数 30px，报告时间 60px，关注货币 60px
- **NewsFilterConfig 布局**：成对字段同行 flex 排列，输入框窄化
- **PaperConfig/StrategyConfig 标签同行**：label-placement="left" 确保标签与输入框同行

### 修复
- **多处 hardcoded 中文 → t() 调用**：策略雷达、信号面板、回测报告、AI 配置、协调器配置等
- **i18n 键名修复**：`save_config→save`、`exit_method→exit_mode`、`widen→wide_mode` 等
- **vue-i18n 占位符修复**：`{{n}}` → `{n}` 禁止嵌套占位符

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
