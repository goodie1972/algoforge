# XAUUSD 量化交易系统 — 变更日志

> 此文件为**人工整理的里程碑日志**，Dashboard 顶部的版本徽章会自动从 `git log` 拉取最新 commit。
> 格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [3.5.5] - 2026-09-05 — 进程内热重启（A）

### 进程内引擎热重启（A）
- **目标**：不退出进程、不拆除 MT4 桥接 socket、不重拉 K 线，秒级完成"重新加载策略代码 + 重置运行态"，彻底消除冷重启的 36s 重连 + 4×2000 根重拉开销
- **触发方式（两种）**：
  1. 触发文件：`touch config/engine_restart.trigger`，引擎在 `_tick` 中节流 2s 检测后自动热重启（与配置热重载一致的 watch 模式）
  2. Dashboard API：`POST /api/engine/restart`，由 `engine_runner` 转调 `engine.request_restart()`
- **关键修复**：`strategies.scanner.scan_strategies()` 有模块级 `_strategy_cache`，首次扫描后永远返回旧类；热重启必须先 `clear_cache()` 再 `create_strategies`（其内部会重新 `import_module`+`reload` 各策略模块），同时 reload `strategies.base`，否则 .py 改动不生效
- **复用清单**：活 MT4 socket（`bridge._connected` 保持，仅做存活校验）、DataFactory 线程与暖缓存、价格轮询/偏置刷新线程（engine_runner 路径）、风控阻断状态（DB 恢复）
- **不热重载边界**：策略 `.py` 代码、F043 字段集、桥接参数可热重载；若改动涉及 `settings.py`/RuntimeConfig 中"不热重载"项仍需进程重启（与既有配置热重载边界一致）

### 操作注意
- 热重启后日志会出现 `[HotRestart] ===== in-process reboot ... =====` 与 `strategies rebuilt: [...]`；socket 不断、K线不闪
- 触发文件为一次性消费（检测即删除），误触不会重复重启

---

## [3.5.6] - 2026-09-05 — 数据库/日志/WS 三层性能优化 + 指标全量回填

### 数据完整性修复（核心，关系回测）
调研发现 `indicator_snapshots` 表历史残缺：覆盖率仅 30%，且键数多数残缺（2-35 键不等），**新写入已正常（全 45-46 键），但历史 K 线无对应指标**。MT4 历史保留期短，自存是回测硬需求。

提供 **`tools/backfill_indicators.py`** 一次性回填工具：
- 从 `ohlcv` 读全部 K 线 → 调用 `_ta_only_indicators` 计算全套 46 键 → UPSERT 到 `indicator_snapshots`
- 支持 `--only-incomplete`（仅回填 < 40 键的行）、`--keep-gc`（保留 GC_* 残留）、`--clean-gc-only`（仅清理）
- 使用单连接 + `executemany` 批量写入（每 1000 行 commit），实测 42K 行仅需 23 秒
- **回填结果**：5,643 → 48,569 行（**97% 完整 45+ 键**），各周期 100% 覆盖 M5/M15/M30/H1/H4/D1/W1
- 同时清理 17,085 个 GC_*（历史黄金合约）残留

### D1 tick_data 表持久化清理
- `data/database.py` 加 `prune_tick_data(max_rows=200000)`（默认 1-2 周全交易时段 tick 量）
- `tick_data` 加 `idx_tick_data_ts` 索引（清理路径查询提速）
- DataFactory 在每 5 分钟 `_validate_data()` 之后调用 prune，避免无限增长

### D3 SQLite cache_size 调优
- `PRAGMA cache_size=-64000`（默认 2MB → 64MB）
- 表行数上 10 万后旧值频繁淘汰，每次查询重新读页；64MB 让热表常驻缓存

### D5 价格 WS 推送去重
- `broadcast_prices()` 0.3s 轮询，但仅在 bid/ask/spread 任一变化时才推
- MT4 tick 频率 1-3Hz，0.3s 轮询大量重复；去重后前端不会收到无变化 JSON 触发无效 re-render

### 已有未改动（D2/D4 经核实已就位）
- **D2 trading.log 轮转**：10MB × 7 备份（`engine_standalone/main.py:55`，无需改）
- **D4 synchronous=NORMAL**：已是 WAL 模式默认（`data/database.py:311`，无需改）

### 版本号
- `data/database.py` `DATABASE_VERSION` 升 v2 并补 changelog

---

## [3.5.7] - 2026-09-05 — 主循环性能优化（E1 + E3）

### E1｜策略并行执行
- `_tick()` 改用 `ThreadPoolExecutor(max_workers=4)` 并发跑 `_run_strategy`，替代原 for 循环串行
- 实测：25 策略 × 5ms，**串行 142ms → 并行 41ms，加速 3.4x**
- 收益：tick 处理从 100ms 预算超标 42ms 降到 41ms（充足余量），K 线不再掉帧
- 异常隔离：每个 `_run_strategy` 仍自带 try/except，单策略异常不影响整体
- 超时防御：每个任务设 80ms deadline（tick 周期 100ms 留 20ms 给协调出场/状态报告）
- 线程生命周期：惰性 init + 进程退出时 `_shutdown_strategy_executor(wait=True)`

### E3｜bridge.get_positions 加超时
- `_status_report` 中 `bridge.get_positions()` 加 1s 超时（`ThreadPoolExecutor.submit + future.result(timeout)`）
- 超时/异常回退 `_cached_positions` 缓存值，避免 MT4 卡顿阻塞 tick 周期
- 首次无缓存返回空列表（语义安全）

### 版本号
- `engine_standalone/core_loop.py` `CORE_LOOP_VERSION` 升 v2 并补 changelog
- `docs/NEXT_IMPROVEMENTS.md` 新建：记录 F1 前端拆分 + F2 热重启覆盖 DataFactory 的下次改进计划

### E1 + E3 真入口修正 (commit 944c6cd — Mixin 陷阱)
- **陷阱**：原 E1 / E3 改动落在 `engine_standalone/core_loop.py`（Mixin），但 `engine_standalone/main.py::TradingEngine` 主类 **override 了所有 tick 相关方法**（`_run_strategy` / `_check_status_report` / `_status_report` / ...），Mixin 代码上线后被全部 bypass
- **修复**：把 E1（ThreadPoolExecutor(max_workers=4)）和 E3（1s 超时回退缓存）真正移到 `main.py` 真入口，core_loop 的辅助方法通过继承访问
- **验证**：单测 E1 25 任务 4 worker = 38ms（vs 串行 142ms，3.7x），E3 超时回退缓存生效

## [3.5.4] - 2026-09-05 — 启动加速 + Dashboard 假死修复

### 启动优化（B + C）
- **C｜砍 sleep / 收缩重连**：引擎 `start()` 中硬编码 `time.sleep(5)` 死等改为有界等待 `_wait_data_factory_ready(≤5s)`，数据就绪即提前继续；MT4 桥接重连由 `30×10s=300s` 收缩为 `12×3s≈36s`（引擎与 engine_runner 两处同步）
- **B｜DataFactory 暖启动门控（v4）**：新增本地 K 线缓存 `data/cache/candles_cache.pkl`，重启时先加载上次缓存，首轮按「当前时间 − 缓存末根时间」估算缺口增量补齐（上限 2000），不再无脑重拉 4×2000 根。冷启动/缓存过旧时自动回退全量。缓存每 5 分钟及首轮成功后落盘

### Dashboard 假死修复（导航卡顿 + K线冻结/漂移）
- **根因**：`web_manager.broadcast()` 在持锁状态下 `await ws.send_text()` 且无超时——任一被浏览器节流/弱网的 WebSocket 客户端发送缓冲占满即阻塞整个 asyncio 事件循环，导致 REST（切导航拉数据）与 WS 推送全部卡死（K线不动），客户端恢复后积压消息一次性涌来（图表漂移/跳动）
- **修复**：`broadcast()` 改为快照连接后释放全局锁，按连接并发发送，单客户端 1s 超时即放弃并断开，绝不拖累事件循环与其他客户端（原设计的 `broadcast_hub` 背压机制保留备用）
- **前端减负**：K线自动刷新不再每 2s 全量重算所有指标，仅在新 K 线出现时重算；历史滚动加载加 8000 根软上限，避免主线程被拖垮

### 操作注意
- 重启后首轮数据加载明显加快（暖缓存命中时近乎即时）；若缓存过旧（如隔周重启）会自动全量补齐，行为不变
- 假死修复后，弱网/后台标签页不再拖垮整个面板

### K 线拖拽后缓慢漂移修复 (commit 3f71af7)
- **症状**：用户拖拽过 K 线后，图表会"缓慢漂移"自动回滚实时
- **根因**：`TradingTerminal.vue::scheduleAutoScroll()` 在 `subscribeVisibleLogicalRangeChange` + `subscribeCrosshairMove` 两个订阅里被无条件调用，10s 后强制 `scrollAllToRealTime()`。`isViewingLatest()` 防护对"轻微拖动"场景无效（拖动后视窗右边缘仍落在最新 5 根内 → 防护绕过）
- **修复**：彻底移除 scheduleAutoScroll 函数 + 4 处调用（onMounted / 主题切换 rebuild 各 2 处）+ 2 个 let 变量。dist 重新构建，已无残留
- **行为变化**：拖拽后视图完全静止跟随意图；需主动滚到右边缘才吸附实时

## [3.5.3] - 2026-09-04 — 指标来源重构（F043 扩展 + DataFactory v3）

### 变更
- **F043 协议扩展（28 → 34 字段）**：新增 `ema_34`/`ema_50`/`ema_200`/`linear_reg_slope`（EA 直供）与 `cci`/`cci_prev`（CCI(14)，含方向用前一根值）；`stoch_rsi` 与蜡烛形态仍由 TA‑Lib 计算
- **DataFactory v2**：删除 `_EA_CACHE_KEYS` 中 EA 从未发送的 5 个冻结键；`ema_34/50/200`、`linear_reg_slope` 改由 EA 真值；新增 `cci` 与 `cci_direction`
- **DataFactory v3**：①修复增量轮次清空顶层缓存（指标被清零为 None）的严重缺陷；②保护逻辑改为"EA 本轮确实提供过该键才保护"（`_EA_PROVIDED_TTL`=30s），EA 掉线超 30s 自动回退 TA‑Lib 实时值
- **文档同步**：`docs/data_factory.md`（46 键权威表）、`CLAUDE.md`、`AGENTS.md`、`docs/strategy_dev_guide.md`、`docs/mt4_guide.md`（F043 协议版本须知）、`INDICATOR_SOURCES.md`

### 操作注意
- EA 需重新编译 `FreeMT4Bridge.mq4` 并挂机到 XAUUSD 图表，否则旧 `.ex4`（28 字段）会被拒绝、EA 指标全部失效

## [3.5.2] - 2026-08-28 — FollowAve v1.2 出场逻辑重构

### 变更
- **bbi_dir 修正**：改用 `get_indicator("bb_mid_direction")`，趋势反转出场真正生效（v1.1 恒 flat 导致永不触发）
- **新增超买死叉止盈**：曾触 BB 上轨（high≥bb_top−3）+ Stoch K>80 死叉 → 主动止盈（最高优先级），空头对称
- **m15 新增 Trailing Stop**：2.0×ATR（v1.1 无 TS），与 m30 对齐
- **出场优先级调整**：① 超买死叉止盈 → ② 趋势反转 → ③ BB 硬止损 → ④ Trailing Stop（止盈在前，止损在后）
- **Stoch 参数分离**：入场 70/30，止盈 80/20
- **文档同步**：m15/m30 策略说明（cn/en）

## [3.5.1] - 2026-08-28 — Magic Number 规则升级（策略类型 PP 划分）

### 变更
- **Magic Number 编号规则**：新增策略类型 PP 表（11 多因子 / 22 事件驱动 / 33 机器学习 / 66 趋势追踪 / 77 价值回归 / 88 价格回归 / 99 不能定位），仅用于 2026-08-28 后**新增**策略
- **存量策略 magic 不变**：唯一例外 `viprasol_sniper` 661401 → 661400（原号已由 m15_followave 占用，避免撞号）
- **文档同步**：STRATEGY_VERSIONING.md、strategy_manual.md/html、viprasol 策略说明（cn/en）

### 说明
- 历史 `66`/`88` 前缀（自研/借鉴）仅对存量策略有效

## [3.4.0] - 2026-08-24 — 策略文档双语 + 新闻多源分离

### 新增
- **策略说明文档双语**：25 个策略文档 frontmatter 新增 `display_en`，解析器返回，前端按 locale 选择（文档驱动，不再依赖运行时映射）
- **新闻多源按语言分离**：中文源（汇通+金十）+ 英文源（FXStreet+Kitco），按界面语言展示，无需翻译
- **查看原文链接**：每条新闻支持点击跳转原文页面（url 字段）
- **来源标签动态显示**：huicong/jin10/fxstreet/kitco 按 source 区分显示

### 修复
- gold_news 表新增 url/lang 列，汇通/金十抓取提取链接
- _rule_based_judge 增加英文关键词判断 + 黄金自身涨跌优先
- locale 切换时新闻自动按语言重新拉取
- 英文界面新闻不再显示中文翻译

## [3.3.9] - 2026-08-24 — 策略说明文档全面修复 + Git 版本号升级

### 修复
- **策略说明文档不完整**：25 个策略的说明文档全部修复，解析器支持中文标题（`### 做多/做空`）+ exitNote 从 frontmatter 读取
- **get_dynamic_sl_tp 签名不兼容**：followave/fish_eaten 的 4 参签名加 `atr_val=None` 默认值，兼容引擎 2 参调用，止损恢复正常
- **AI 代理自动检测代理端口**：去掉端口 10808 自动检测，改用纯环境变量配置，修复 SSL 连接错误
- **K线图漂移**：`isViewingLatest()` 防止查看历史时自动回滚

### 新增
- AI Agent 人设系统 + ToolRegistry + SkillLoader（3 内置技能）

## [3.3.8] - 2026-08-21 — K线图修复 + 三新策略上线

### 新增
- **fish_eaten v2**（magic 661301）：M30 价格回归策略，修改为 M30 + TS=48 吃鱼出场 + 时间止损
- **m15_followave v1**（magic 661401）：M15 Stoch+BBI+BB 趋势跟踪，±DI 门禁，回测 +$403
- **m30_followave v1**（magic 661402）：M30 Stoch+BBI+BB 趋势跟踪，2.0×ATR trailing stop，回测 +$658
- **K线图历史数据滚动加载**：后端 `before` 参数 + 前端滚动左边缘自动加载更多历史，不设上限

### 修复
- **K线图漂移**：`isViewingLatest()` 判断用户是否查看最新，查看历史时不再自动回滚（阈值 5 根）
- **K线图历史被裁**：`fetchLatestCandles` 不再 `splice` 裁头部（原会把已加载历史删掉）
- **AI Agent 调用失败**：修复 `list index out of range`（models 空列表访问）

## [3.3.7] - 2026-08-19 — 四仓库研究吸收 + 策略升级

### 新增
- **timeprofit_ea v2**：入场增强（M5 EMA10 回踩确认 + 真突破前一根关内判断），替换 v1 在线基础版
- **gold_auto_research v8**：Stoch 5,3,3→14,3,3、RSI 超买 70→79、超卖 35→29（BeanBagData 最新版移植）
- **GoodMA v1**：新策略 60MA 方向 + 回踩入场（Yumerain/EA-MQL4 移植）
- **KISS v1**：新策略 H4 MACD + H1 均线组 + 枢轴支阻（Yumerain/EA-MQL4 移植）
- **LLM 参数搜索工具** `tools/llm_param_search.py`：遗传式搜索 + Ollama 引导（BeanBagData 未吸收部分）
- **DataFactory**：新增 `stoch_14_3_3` 指标缓存

### 修复
- 策略描述路径修复（上一个版本遗留的路径修正）
- 平仓记录写入异常捕获加固

## [3.3.6] - 2026-08-17 — 平仓记录写入修复 + 策略描述路径修复

### 修复
- **平仓记录不写入 trades 表**：`_run_exits` 中调用未定义的 `_trim_closed_trades` 方法导致 `AttributeError`，异常跳出循环后 `db.insert_trade` 被跳过。已在 `PositionMgrMixin` 中补上该方法定义，并加固异常捕获（`json.dumps` 异常类型从 `OSError` 扩展为 `(OSError, TypeError, ValueError, OverflowError)`，`db.insert_trade` 异常改为打 `error` 日志不再 `pass`）
- **策略描述不显示**：`strategy_logics.py` 的 `DOCS_DIR` 指向已不存在的 `docs/strategies/`，实际文件在 `strategies/docs/strategies/`。已修正路径
- 补录 003/004/005 平仓记录到 trades 表（分别盈利 +3.59 / +2.73 / +4.40）

## [3.3.5] - 2026-08-16 — 平仓超时误报修复

### 修复
- **平仓"超时错误"误报**：平仓走 MT4 桥接命令（`_send_cmd` 默认 socket timeout 10s × 2 次重试，最坏 ~20s），而前端 axios 全局 timeout 仅 10s —— 平仓实际成功但前端先报"请求超时"，刷新后才消失。现已：
  - 前端 `closePosition` 单独放宽 timeout 至 30s
  - 持仓 store 超时兜底：请求超时后自动刷新持仓确认，若单子已平掉则按"已提交成功"提示（`TIMEOUT_BUT_CLOSED`），不再误报失败
  - `PositionsTable` 区分提示：`请求超时，但平仓已提交成功（持仓已刷新）`
  - 后端 `close_position` 路由改用 `run_bridge`（专用线程执行器），不再同步阻塞 uvicorn event loop（与 `modify_position` 一致）
- 新增中英文案 `positions.close_timeout_submitted`

## [3.3.4] - 2026-08-16 — 双实例引擎状态脱节修复

### 修复
- **引擎状态脱节（平仓失败根因）**：`python main.py` 以 `__main__` 加载时，运行中任何 `from dashboard.backend.main import XX` 会二次执行顶层代码，创建第二份 `EngineRunner` 并覆盖路由引用，导致 API/UI 显示 stopped、持仓为空、手动平仓失败。现已：
  - `start.py` 改用 `python -m dashboard.backend.main` 模块方式启动（统一模块名）
  - `main.py` 增加模块名守卫：脚本方式运行时提前注册 `sys.modules["dashboard.backend.main"]`，防止二次加载
- **非交易时间误入场的根因**：`_is_market_open()` 错误地把「周日 07:00 北京时间」当开盘（正确应为周一 06:00 = 周日 22:00 UTC），且信号/Athlete 候选票阶段无市场开放过滤。现已：
  - 修正 `engine_standalone/main.py` 与 `engine_standalone/core_loop.py` 的 `_is_market_open()`：闭市窗口为周六 05:00（北京）→ 周一 06:00（北京）
  - 策略信号处理处（`Signal received` 后）增加市场开放检查，休市期间不再产生 Athlete 候选票/尝试开仓
- **AI 聊天面板关闭按钮**：`AiChatPanel` 头部新增关闭按钮（上一版本 ChatLauncher 隐藏按钮的遗留问题），点击可收起面板

## [3.3.3] - 2026-08-16 — AI 交易助理「金探」上线

### 新增
- **AI 交易助理「金探」** — 右下角浮动聊天面板，支持自然语言对话
  - 人设：黄金量化交易分析师，熟悉系统三轨架构和 18 个策略
  - 交易上下文自动注入：账户/持仓/价格/指标/新闻/策略状态/经济日历
  - SSE 流式响应，逐字输出（打字机效果）
  - 6 个快捷指令：行情研判/持仓诊断/新闻解读/策略表现/风险检查/今日总结
  - 多会话管理：新建/切换/删除，会话持久化到 SQLite
  - 空状态引导 + Markdown 渲染（加粗/列表/表格/代码块）
  - 暗色主题，金色品牌色，响应式布局
- 新增 `chat_sessions` + `chat_messages` 数据库表
- 新增后端 `ai_service.py`（上下文收集 + System Prompt + 会话管理）
- 新增后端 `routes/ai.py`（会话 CRUD + `/api/ai/chat` SSE 流式端点）
- 新增前端 `stores/chat.ts`（Pinia 状态管理 + SSE 接收）
- 新增前端组件：`ChatLauncher.vue` / `AiChatPanel.vue` / `ChatMessage.vue`

## [3.3.2] - 2026-08-16 — 删除策略 bug 修复 + 策略说明文档补全

### 修正
- **修复删除策略 API 500 错误**：`dashboard/backend/routes/strategies.py` 第 123 行调用了 `logger.info()` 但文件中从未定义 logger，导致 `NameError`。已添加 `import logging` 和 `logger = logging.getLogger(...)` 定义

### 文档
- **补全 5 个活跃策略缺失的说明文档**：m30_bb_deepreturn_optimized、mfi_bb_m30_optimized、stoch_trend_h1_optimized、mfi_bb_m30_upgraded、rsi_grading_m30_upgraded
- **新建 backup 策略说明文档目录** `strategies/docs/strategies/backup/`，为所有后备策略创建说明文档（27 个），含同名历史版本
- **xaubot_backup.md 从活跃目录移至 backup 目录**（对应策略已在 backup 中）
- 活跃策略 18 个 = 活跃文档 18 个（完全一一对应）

## [3.3.1] - 2026-08-15 — 回滚历史序列改动，策略改用 talib 直接计算

### 修正
- **回滚 DataFactory 中的 `*_list` 历史序列改动**：删除 `_build_indicator_lists`、`_LIST_INDICATOR_KEYS`，`_sync_tf` 和 `_init_indicators_from_db` 恢复原版只存最新一根扁平指标——保持 DataFactory 原有设计不变
- **回滚 base.py**：`_steep_ma_direction` 恢复用 `talib.EMA` 从 `self.candles` 计算的原版逻辑；fallback 路径恢复原版 `_ta_only_indicators` 调用
- **策略中需要历史序列的场景改为用 talib 在 `self.candles` 上直接计算**（而非依赖 DataFactory 缓存提供序列）：
  - `mfi_bb_m30_v1` / `mfi_bb_m30_optimized_v1` — 3 根容差检测改为只用当前 K 线 BB/MFI 扁平值判断（参照 `mfi_bb_m30_upgraded_v16` 的方式）
  - `M30_rsi_bb_v1` — `_get_m30_rsi_direction` 改用 `talib.RSI` 在 candles 上算 3 根方向
  - `entry_score_pro_v1` — 波动因子改用 `talib.ATR` 在 candles 上算 30 根前 ATR 比较
  - `gold_auto_research_v1` — ATR SMA(20) 改用 `talib.ATR` 在 candles 上算
  - `m30_vol_return_v1` — ATR 扩张检测改用 `talib.ATR` 在 candles 上算 5 根均值
- **保留的新增基础指标**：`ema_34`/`ema_50`/`ema_200`/`stoch_rsi`/`linear_reg_slope`（TA-Lib 计算，策略之前手算的，改为从 DF 缓存读取）

## [3.3.0] - 2026-08-15 — 指标计算统一收归 DataFactory + TA-Lib

### 重构
- **所有基础指标计算统一收归 DataFactory，全部基于 TA-Lib**，策略和基类中不再有任何手算指标
- **DataFactory 缓存新增历史指标序列**（`*_list`）：`rsi_list`、`mfi_list`、`bb_list`、`atr_list`、`adx_list`、`macd_list`、`stoch_5_3_3_list`、`ema_9_list`、`ema_21_list`、`ema_50_list`、`ema_200_list`、`sma_14_list`、`sma_20_list`、`sma_50_list`、`close_list`、`volume_sma_20_list` 等 28 个序列字段，供策略读取多根 K 线历史指标值
- **DataFactory 新增基础指标**：`ema_34`、`ema_50`、`ema_200`（TA-Lib EMA）、`stoch_rsi`（TA-Lib STOCHRSI）、`linear_reg_slope`（TA-Lib LINEARREG_SLOPE）
- **base.py 删除手算方法**：`calc_atr_wilder`、`calc_adx_wilder`、`_calc_m30_adx` 三个手算 Wilder 指标方法；`_steep_ma_direction` 改用缓存 `ema_{period}_list` 序列；`calc_gate_state` 中 DI diff 和 ADX 回退改用 `get_indicator`
- **8 个策略清除手算指标**：
  - `20260630_mfi_bb_m30_v1.py` — 删除 `_calc_stddev`/`_calc_bb_at`/`_calc_mfi_at`，改用缓存 `bb_list`/`mfi_list`
  - `20260711_mfi_bb_m30_optimized_v1.py` — 同上
  - `20260811_xaubot_backup_v1.py` — `_FeatureEngineer` 类从 Polars `ewm_mean` 手算改为 TA-Lib 计算 RSI/ATR/MACD/BB/EMA/Volume；删除 `_calc_atr_values`/`_calc_atr`
  - `20260630_M30_rsi_bb_v1.py` — 删除 `_calc_rsi`，`_get_m30_rsi_direction` 改用缓存 `rsi_list`
  - `20260630_entry_score_pro_v1.py` — 删除 `_calc_ema`/`_calc_atr`，改用缓存 `ema_50`/`ema_200`/`atr_list`/`sma_14`
  - `20260630_gold_auto_research_v1.py` — 删除 `_calc_ema`/`_calc_stddev`/`_calc_rsi`/`_calc_atr_values`/`_calc_atr`/`_calc_adx`/`_get_adx_at`/`_get_macd`/`_get_stoch` 全套手算，改用缓存
  - `20260630_multi_confluence_quant_v1.py` — 删除 `_calc_ema`/`_calc_rsi`/`_calc_macd`/`_calc_stoch_rsi`/`_calc_linear_reg_slope`，改用缓存 `ema_21`/`ema_50`/`ema_200`/`macd`/`stoch_rsi`/`linear_reg_slope`；H1 EMA 也改为从 DataFactory H1 缓存读取
  - `20260630_momentum_pulse_pro_v1.py` — 删除 `_calc_roc`，改用 `talib.ROC`

### 修复
- 修复 `atr_list`/`close_list` 等历史序列在 DataFactory 缓存中不存在的隐性 bug（多个策略已引用但缓存未提供）

## [2.9.5] - 2026-08-14 — 十字光标联动显示真实指标值

### 修复
- 十字光标联动时副图同步的 `setCrosshairPosition` 传入 price=0，导致 RSI 等副图鼠标经过时显示值为 0 而非真实指标值
- 新增 `indexSeriesValues`：为每个 series 构建 time→值 索引（支持 close/value/macd/histogram/k/d 等字段），同步竖线时取该指标在光标时点的真实值；查不到时回退最近可用值

### 验证
- 单元验证：RSI series → 45.3、Candle close → 4315，非 0 值正确
- Playwright：主图/副图移动均正常更新时间标签，0 console 错误

## [2.9.4] - 2026-08-14 — 主副图十字光标联动

### 新增
- **十字光标跨图联动**：鼠标在任一图表（主图/K线 + RSI/Stoch/MACD/ATR/成交量/ADX/DI/MFI/BBI 副图）移动时，所有图表的竖线同步对齐到同一时间点，方便对照同一时刻主图与各副图指标
- **时间标签**：图表右上角显示光标对应时间，`YYYY-MM-DD HH:mm` 精确到分钟；移出图表自动清除
- 技术：基于 lightweight-charts 4.1 `setCrosshairPosition` / `clearCrosshairPosition` 双向同步，`_syncLock` 防循环触发
- Playwright 验证：主图、副图移动均更新时间标签（如 2026-08-12 02:00），0 console 错误

## [2.9.3] - 2026-08-14 — 手工平仓反馈修复

### 修复
- **手工平仓看似无反应**：平仓 API 成功后 `_cached_positions` 未立即更新（WS 每 5s 轮询仍推送旧持仓），用户误以为没平掉再次点击 → 404 被静默吞掉
  - 后端 `engine_runner.close_position`：平仓成功后立即从 `_cached_positions` 移除该票
  - 前端 `positions.ts` store：`close()` 成功后立即本地移除该行（不等 WS/轮询）；404 时抛 `notFound` 标记
  - 前端 `PositionsTableBase.vue` / `PositionsTable.vue`：404 时提示"该单已平仓或不存在"（新增 i18n key `positions.close_not_found`），而非无声失败
- Playwright 验证：模拟 404 时提示正确弹出、持仓行立即移除

## [2.9.2] - 2026-08-14 — 修复重启后持仓入场时间丢失

### 修复
- **"可疑秒平" SafetyLock 误报**：引擎重启后恢复持仓时 `_entry_times` 用 `time.time()` 填充（或纸面模式完全未填充），导致持仓时长计算为 0 → 平仓瞬间被误判为"可疑秒平"并暂停新单
  - `dashboard/backend/engine_runner.py`：接管持仓改用 `_pos_open_time` 真实开仓时间；纸面模式（`takeover_existing_positions` 返回空）用 `get_positions` 遍历兜底填充 `_entry_times`
  - `engine_standalone/main.py`：同逻辑同步（备用路径）
- 实测：重启后 `260814000→1786637573`、`260814007→1786686674` 正确填充，0 次 SafetyLock 误报

## [2.9.1] - 2026-08-14 — 修复纸面止损失效

### 修复
- **纸面交易止损失效（严重）**：持仓中策略 `on_tick` 被 `max_positions` 上限挡住 → 指标缓存不刷新 → `get_indicator("atr")` 返回 None → `check_ema20_exit` 永远 `return False` → 单子永不平仓（13015 跌破 SL 18 点仍挂着）
  - A：`_run_exits` 出场检查前强制 `strategy.refresh_data()`，恢复 ATR 移动止损/盈利回撤/保本/硬止损判定
  - B：`PaperBridge.get_tick_price` 模拟真实 MT4 自动触发 SL/TP（触及价格即平仓，不依赖策略指标），带防重入 guard
  - C：`_restore_open_positions` 恢复 CSV 中 `stop_loss / take_profit`（原硬编码 0，重启后 SL/TP 全丢）
- 实测：13015（BUY 4379.37 / SL 4341.67）重启后自动止损平仓，持仓 3→2

### 其他
- 注意：自动平仓瞬时持仓时长为 0（重启后 `_entry_times` 未恢复）可能触发"可疑秒平" SafetyLock 误报，后续可优化

## [2.9.0] - 2026-08-14 — 时间格式化统一 (A+B)

### 新增
- **后端**：核心 API（`/api/trades/history`、`/api/positions`、`/api/account`）新增 `_ts` 后缀 Unix 时间戳字段（秒级整数），前端可直接用 
- **后端**：`core/time_utils.py` 新增 `fmt_ts()` LRU 缓存格式化工具（10000 条上限 + 命中率统计）
- **前端**：`src/utils/timeFormat.ts` 新增统一时间格式化工具（`smartTs` / `formatDateTime` / `formatTimestamp`，基于 date-fns，UTC+8 时区无关）

### 修复
- `/api/account` 返回 422（`@router.get("")` 装饰器误挂在 `_add_ts_fields` 上）— 已修复
- `/api/positions` 未生成 `open_time_ts`（`open_time` 为 Unix 时间戳字符串，`_add_ts_fields` 只解析日期字符串）— 已兼容纯数字时间戳
- 持仓/成交/历史视图时间列改用 `_ts` 字段，修复旧代码对 ISO 字符串 `parseInt` 导致的 1970 年错误日期

## [2.8.0] - 2026-08-13 — 策略与系统仓库分离

### 重大变更
- **仓库分离**：策略文件（`strategies/`）+ 策略文档（`docs/strategies/`）从 algoforge 仓库移除，迁移至独立仓库 [algoforge-strategies](https://github.com/goodie1972/algoforge-strategies.git)
- **历史重写**：`git filter-repo` 从全部历史中移除策略文件，algoforge 仅保留系统代码
- 2026-08-13 之前的 commit hash 已全部改变

### 新仓库
- `https://github.com/goodie1972/algoforge-strategies.git`
- 策略文件命名规范：`YYYYMMDD_name_vN.py`
- 策略说明文档：`docs/strategies/{name}.md`

### 修改
- `CLAUDE.md` 移除策略编写规范/注册流程，增加策略仓库引用
- 删除策略相关文档（`docs/strategy_analysis.md`、`docs/strategy_dev_guide.md` 等 7 个文件）
- 策略缓存预热改为后台异步任务，不阻塞服务器启动

## [2.7.9] - 2026-08-11 — 配置页面全面优化（卡片分组+下拉+问号帮助）

### 新增
- **配置页面卡片分组**：风控/新闻过滤/纸面交易 全部改为卡片分组布局，去掉分割线，更清晰
- **下拉+填空双模式**：所有配置项 `n-select` 加 `filterable tag`，既可从预设值下拉选择，也可直接键入任意值
- **问号帮助按钮**：每张卡片右上角加圆形问号，悬停弹出该卡片的设置说明
- **浅色模式适配**：K线图背景色+数字输入框随主题切换

### 修改
- **风控配置布局**：仓位管理/账户级止盈止损/单策略风控 三张卡片，全部改为下拉选择
- **新闻过滤布局**：新闻过滤/新闻偏向/事件过滤 三张卡片，事件筛选的影响级别和关注货币同行
- **纸面交易布局**：纸面交易/交易设置/门禁控制 三张卡片，持仓数和初始余额同行
- **余额改为填空项**：纸面交易初始余额从数字滚动键改为 `n-input-number` 填空输入

### 修复
- 浅色模式下控制开关和输入框背景色适配
- 账户级止盈止损 i18n 键名修复

## [2.7.8] - 2026-08-11 — 策略出场优化 + 高位追高拦截 + 纸面持仓修复

### 新增
- **高位/低位追高拦截**：gold_auto_research 和 sanqing_h1_upgraded 新增 `price_position>0.88 且 偏离EMA21>4×ATR` 条件，禁 BUY 追高（允许 SELL）；对称低位禁 SELL 抄底（允许 BUY）
- **利润回撤止盈动态阈值**：5 个策略统一，盈利>10 时回撤 35% 强制止盈（原 50%），保护大盈利
- **TF 周期栏**：持仓/成交列表增加 TF 栏（方向栏前），从策略名自动解析周期
- **副图优化**：指标标签加大加粗（13px/700/白），Stoch 新增 80/20 参考线，ADX 新增 25 参考线，副图显示当前值

### 修复
- **纸面模式忽略策略级 max_positions**：纸面模式用 `_paper_max=10` 覆盖了 `strategy.max_positions=1`，导致 gold_auto 和 sanqing 连续开 4 张同向单（max_positions 失效）
- **净盈亏计算**：`净盈亏 = pnl - |手续费| - |过夜费|`，纸面 commission 统一 0.5 并写入 Position，修复旧公式对正数 commission 算错
- **黄金快讯标签**：卡片标签硬编码"看多"，与 Modal 动态标签不一致，改为根据 current_bias.overall 显示
- **mfi_bb_m30_upgraded 中线出场改用固定参照+穿越跟踪**：原用动态 `bb["mid"]`，价格涨后中线被拉高，导致过早出场；改为用固定入场中线 + 穿越跟踪

### 策略优化
- **mfi_bb_m30_upgraded v16**：条件②中线出场改用 `entry_bb_mid`（固定入场中线）+ `has_crossed_mid` 穿越跟踪
- **sanqing_h1_upgraded v11**：趋势保护下强制止盈改为动态阈值（盈利>10 时 35%）
- **gold_auto_research / m30_rsi_bb / m30_bb_deepreturn 系列**：ADX>25 趋势强放宽回撤从 50% 降为动态 35%

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
