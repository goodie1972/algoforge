# AlgoForge XAUUSD 代码审查标准与流程（Code Review Standard & Process）

> 维护者：火眼眼（Code Review Expert） ｜ 版本：v1.0 ｜ 适用：本仓库所有 Python / Vue / TS 代码变更
>
> 核心原则：**交易系统的每一行代码都可能与真实资金挂钩。审查的重点不是"风格好不好看"，而是"它会不会亏钱、会不会在关键时刻掉链子、出了问题能不能查得到"。**

---

## 一、为什么需要专门的标准

本项目是一个**实盘黄金自动化交易系统**，技术栈是 Python 3.10+（FastAPI + 三轨交易引擎）+ Vue3/TS（Dashboard）+ SQLite。它和普通 Web 应用有三个本质区别，决定了审查清单必须不一样：

1. **错误有直接的金钱代价**：下单失败、止损被静默关闭、价格解析为 0，都可能变成真实亏损。
2. **7×24 常驻运行 + 多线程**：引擎线程、DataFactory 线程、Dashboard 后台轮询同时存在，竞态和阻塞会吞噬行情窗口。
3. **故障发生在没人盯着的时候**：审查必须假设"凌晨 3 点 EA 掉线"的场景，确保有重连、有日志、有熔断。

所以本标准的分级与清单，会把**资金安全 > 可用性 > 安全 > 可维护性**作为优先级。

---

## 二、评审分级（Severity）

| 标记 | 含义 | 合并门槛 |
|:-----|:-----|:---------|
| 🔴 **Blocker（阻断）** | 可能导致资金损失、下单失败、数据损坏、安全泄露 | **必须修复**，否则禁止合并 |
| 🟡 **Suggestion（建议）** | 明显隐患或设计缺陷，短期不一定爆，但应修 | 作者需回复"已修 / 有意保留（说明理由）" |
| 💭 **Nit（细节）** | 可读性、命名、小优化 | 可选，不阻塞 |

> 原则：🔴 必须修；🟡 要回应；💭 随意。严禁用 💭 来刷存在感，也严禁把 🔴 降级成 🟡 来"放行"。

---

## 三、角色与职责

| 角色 | 职责 |
|:-----|:-----|
| **作者（Author）** | 提交前完成自检清单（见第七节）；写清"改了什么、为什么改、动了哪些资金路径" |
| **评审人（Reviewer）** | 至少 1 人；涉及 `core/`、`engine_standalone/`、`strategies/` 的资金/风控代码须有**第二作者之外**的人评审 |
| **风控代码守护者（Risk Owner）** | 任一 `risk_mgr` / `position_mgr` / `athlete` / `bridge` 下改变更，必须有一名熟悉风控链路的人确认 |
| **AI 预审（火眼眼）** | 每次 PR 自动跑一遍标准清单，标记 🔴 候选，减轻人工负担（见第六节自动化） |

> 小改动（文案、日志、文档、纯前端样式）可走轻量评审（1 人 + AI）。任何触及"下单/平仓/风控/桥接/数据库写入"的改动，必须人工评审 + Risk Owner 确认。

---

## 四、评审流程（Workflow）

```
Fork/分支 → ① 作者本地自检 → ② 提 PR（带描述+资金路径说明）
        → ③ AI 预审（自动，标 🔴 候选 + 跑 lint/test）
        → ④ 人工评审（至少 1 人；资金/风控路径加 Risk Owner）
        → ⑤ 作者修改并回复每条评论（🔴 必改，🟡 必回应）
        → ⑥ Reviewer 确认无 🔴 残留 → Approve
        → ⑦ CI 全绿（lint + type + test）→ 合并到主分支
```

硬性门槛：
- **任何 🔴 未解决 → 禁止合并**（哪怕只是"看起来很小"）。
- **CI 失败 → 禁止合并**。
- **资金/风控路径变更无 Risk Owner 确认 → 禁止合并**。
- 合并前必须确认：本次变更在**纸面交易 / 模拟环境**跑过至少一个完整 tick 周期（见 `paper_bridge.py` / `paper_main.py`）。

---

## 五、代码审查清单（本项目特化版）

> 说明：下面每条都标注了"为什么重要"和"本项目对应证据"。证据里的 `文件:行` 来自当前代码快照，目的是让标准落地、可对照，不是一次性挑刺。

### 🔴 A. 资金安全与交易正确性（最高优先级）

- [ ] **下单价格/手数绝不可能是"假正常值"**
  - 桥接层任何获取报价的函数，失败时**必须返回 `None` 或抛异常**，绝不能返回 `0.0` 这种"看起来合法"的哨兵值。
  - 证据：`core/freemt4_bridge.py:186` `get_tick_price` 失败时返回 `(0.0, 0.0)`。若调用方直接拿它当下单价格，可能向 MT4 发一个价格=0 的市价单 → 由经纪商按市价成交还好，但若被当成挂单价格则灾难。**标准：桥接读取类接口失败一律 `None`/raise，调用方必须判空后再用。**
- [ ] **SL/TP 永不能用 `0` 当作"未设置"的隐式哨兵**
  - 证据：`core/freemt4_bridge.py:357` `open_order` 里 `sl = sl if sl is not None else 0`。若某策略把"计算出的止损价恰好为 0"或"忘记传"传成 `0`，在 MT4 里 `sl=0` 表示**不挂止损** → 风险保护被静默关闭。
  - **标准：价格类字段用 `Optional[float]`，`None` 才表示"不设置"；在 `open_order` 入口断言 `sl is None or sl > 0`，`tp` 同理；禁止用 `0.0` 表达"不挂"。**
- [ ] **下单指令不可被静默吞掉**
  - 证据：`core/freemt4_bridge.py:103` `_send_cmd` 中，若发送中途 `_recv_raw` 抛错，会 `disconnect()` 并直接 `return None`，**不会重试这条在途指令**。一次瞬时网络抖动就可能让"开仓"指令消失且无痕。
  - **标准：开仓/平仓类指令必须有明确的"成功/失败"回执；失败必须**上抛或返回可区分的错误码**，绝不允许调用方在不知情下以为下单成功。下单路径建议做幂等键 + 显式失败告警。**
- [ ] **风控判定函数与"改状态"必须分离**
  - 证据：`engine_standalone/risk_mgr.py:57` `check_consecutive_loss` 在"判断"的同时 `state.consecutive_losses += 1`。同一函数被调用两次会重复计数；某处只"探测"不"提交"时极易出错。
  - **标准：纯查询函数（`is_*`）不改状态；需要累加的状态变更单独成函数（如 `register_loss`/`reset_loss`），调用点语义清晰。**
- [ ] **确认性指标只能源自已闭合 K 线（bar1），禁止用正在形成的 forming bar（candles[-1]）做买卖判定**
  - 证据：重绘/未来函数是本仓最大的隐性资金风险。`services/data_factory.py` 已把 `_sync_indicators` 切到 F043 `shift=1`、`latest_ind` 取 `merged[-2]`（已闭合 bar1），策略 `get_indicator()` 读顶层缓存即 bar1；运动员 `athlete._verify` 同样只读 `get_cache(tf)`（bar1），`_execute` 才用 `tick[ask/bid]` 当成交价。但 `strategies/base.py:91` 的兜底路径曾用 `self.candles[-1].time`（forming bar0）算指标——已修复为 `candles[-2]`。
  - **标准：所有"买卖判定 / 风控指标（RSI/BB/MACD/ATR/ADX…）"只能取自上闭合 K 线——`get_indicator()` / `get_cache` 顶层 / `candles[-2]`。当前正在形成的 `candles[-1]` 仅可用于"价格/成交量是否触达某价位"的触发，绝不可在其上重算或读取指标做判定。策略 `_verify_entry` 同样只许读传入的 `latest` 字典，不得回读 `self.candles[-1]`。**
  - **forming bar（`candles[-1]`）允许 / 禁止清单**（防止"价格触发"旗号下偷算指标）：
    - ✅ **允许**：OHLCV 及其派生（振幅、实体大小、阴阳、上/下影线、量比、纯价格/量统计）。
    - ❌ **禁止**：任何指标值（RSI/BB/MACD/ATR/ADX/Stoch/MFI/EMA/SMA…），以及基于 forming bar 自算的指标（`talib.` / `numpy` 手算）。
- [ ] **禁止在策略内自算买卖指标（必须走 `get_indicator()`）**
  - 证据：`strategy_manual.md:17` 明文——"DataFactory + TA-Lib 是唯一数据来源，所有策略指标通过 `get_indicator(key)` 读取，禁止自算 RSI/MFI/BB/EMA/ATR/ADX/Stoch/MACD 等指标"。但扫描发现多个策略直接 `import talib` / `import numpy` 在 `self.candles`（含 forming bar0）上重算：如 `20260630_M30_rsi_bb_v1.py:101` `talib.RSI(np.array(self.get_close_prices()), …)`，其 `rsi_arr[-1]` 即在 forming bar0 上算的 RSI；`20260801_m30_vol_return_v1.py:90` `talib.ATR` 基于 `self.candles`；`20260811_xaubot_backup_v1.py` 整段 `calculate_all` 用 talib 算全套指标；`20260630_gold_auto_research_v1.py:128`、`20260630_entry_score_pro_v1.py:146`、`20260630_momentum_pulse_pro_v1.py:79`、`20260821_m15/m30_followave_v1.py:158/160` 等。这既违反手册禁令，又因基于含 forming bar0 的序列引入了**重绘/未来函数**（与上方 bar1 项是同源隐患，只是发生在策略内部）。
  - **标准：策略文件（除 `base.py` 框架 helper 外）一律不得 `import talib/numpy` 自算买卖指标；所有 RSI/ATR/BB/MACD/Stoch/ADX 等值必须来自 `get_indicator(key)`（DataFactory 已算好的 bar1 缓存）。确需自定义特征时，必须在 `services/data_factory.py` 的 `_ta_only_indicators` 中统一计算，再经 `get_indicator` 暴露，且使用已闭合序列（`candles[1:]`，剔除 forming bar0）。** 完整违规清单见 `docs/STRATEGY_SELF_COMPUTED_INDICATORS_AUDIT.md`。
  - **CI 静态门禁（已落地）**：本项目已用一条**不可绕过的自动化检查**把这条 🔴 卡进流程，而非只靠人工肉眼：
    - 检查文件：`tests/unit/test_strategy_indicators_refactor.py::test_no_talib_numpy_import_in_strategy_files`
    - 规则：扫描 `strategies/*.py`，**除 `base.py` / `scanner.py` / `__init__.py`（框架层）与 `xaubot_backup_v1.py`（ML 特征管线，模型耦合，已强制 `candles[:-1]` 仅闭合 K 线并豁免）外**，任何文件出现 `import talib` / `from talib` / `import numpy` / `from numpy` 即断言失败、CI 变红。
    - 行为回归：同一测试文件另含 `test_strategy_reads_cached_indicators`（7 个策略 parametrize，验证 helper 直接读 `get_indicator` 缓存而非 `self.candles` 上 talib 计算）与 `test_stoch_completed_graceful_when_cache_missing`（缓存缺失优雅返回 `None`，不因缺失回退 talib），确保"改完不靠自算"是被测试钉死的，而非口头约定。
    - 维护约定：**新增/复制策略文件时，若又在文件头 `import talib/numpy`，本测试会直接拦合并**；若要引入自定义特征，必须先在 `data_factory._ta_only_indicators` 内基于 `candles[1:]` 计算后经 `get_indicator` 暴露，再删除文件头自算 import。
    - ⚠️ **运行范围说明**：本仓库 `.gitignore` 第 66 行 `tests/`（commit `43a65b6`「测试目录不上传主应用」）约定测试目录不入库，故该门禁测试**仅本地运行**（`pytest tests/unit/test_strategy_indicators_refactor.py`），不会随主程序推送、也不在共享 CI 自动跑。若要让它真正卡住共享 CI，二选一：① `git add -f tests/unit/test_strategy_indicators_refactor.py` 强制纳入；② 调整 `.gitignore` 放开该测试文件。在采用前，这条 🔴 仍主要靠「作者本地跑测试 + 评审人核查」兜底。

- [ ] **策略每次改动必须 +1 版本号并补变更日志（禁止静默修改）**
  - 证据：本次「去 talib 自算」重构初版推送时，8 个策略文件只复制了旧副本、未升 `STRATEGY_VERSION`、未补 `STRATEGY_CHANGELOG` 条目——评审与回滚时无法区分「哪版改了什么」；且 `20260630_M30_rsi_bb_v1.py` 原本就存在 `STRATEGY_VERSION="v13"` 与日志末条 `v14_optimized` 错位的隐患，说明版本纪律此前未被强制。
  - **标准：任何对 `strategies/*.py` 的修改（含重构、参数调整、bug 修复），必须**：① 将文件顶部 `STRATEGY_VERSION` 由 `vN` 升到 `vN+1`（带小数位的如 `v1.2`→`v1.3`；若日志已存在更高版本号如 `v14_optimized`，新版本须跳过占用项，e.g. `v13`→`v15`）；② 在 `STRATEGY_CHANGELOG` 列表追加一条 `{"version": "v新", "magic": <同文件 STRATEGY_MAGIC>, "date": "<YYYY-MM-DD>", "desc": "<改了什么、为什么>"}`；③ 文件头 docstring 里的版本描述同步更新。无 `STRATEGY_CHANGELOG` 块的旧策略至少升 `STRATEGY_VERSION` 常量。
  - **回滚/追责**：版本号 + 日志是策略「出了事能查到哪一版、能否秒级回滚」的唯一依据，缺一则按 🔴 处理、禁止合并。

### 🔴 B. 安全（Secrets / 注入 / 鉴权）

- [ ] **密钥不落库、不进版本控制、不打印**
  - 证据：`services/llm_provider.py:142` `_save` 把含 `api_key` 的 provider 明文写入 `data/llm_providers.json`；`:220` `get_active_raw` 直接返回完整 key。若此文件被误提交或日志泄漏，即泄露 API Key。
  - **标准：密钥文件必须进 `.gitignore`；仓库内不得出现任何明文密钥（用占位 `""` + 环境变量/密钥库注入）；任何日志/接口返回密钥处必须经 `_sanitize` 脱敏（现有 `list_providers` 已做，保持一致）。** 建议长期迁移到 OS Keyring 或加密存储。
- [ ] **SQL 一律参数化，动态列名只来自白名单**
  - 证据：`data/database.py` 绝大多数查询已参数化（✅ 很好）。`update_signal_status`/`update_news_bias_report` 用固定 `allowed` 集合拼 `SET` 列名（非外部输入），安全。
  - **标准：所有 `execute` 用 `?` 占位；若必须拼列名/表名，来源只能是代码内白名单或 `PRAGMA` 返回（如 `migrate_timezone_fix`），严禁拼接任何外部字符串。新增 SQL 时审查人必须确认无 f-string 注入。**

### 🟡 C. 并发与线程安全

- [ ] **跨线程共享的可变状态有保护**
  - 证据：引擎在 `dashboard/backend/engine_runner.py` 的后台线程跑，Dashboard 经 WebSocket 读写同一份引擎状态；`core_loop.py:27` 用 `snapshot = list(self.strategies)` 做快照（✅ 正确），但 `_risk_states` 等字典的读写未显式加锁。
  - **标准：在模块级注释里写明"哪些对象只属于引擎线程、哪些会被 Dashboard 跨线程访问"；跨线程访问用 `threading.Lock` 或 `asyncio` 语义保护；不要在 tick 热路径里引入新的共享可变全局。**
- [ ] **主循环不能被长时间阻塞**
  - 证据：`engine_standalone/core_loop.py:67` `_check_news_blackout` 在 tick 循环里 `time.sleep(20)` × 3（约 60 秒），期间其他策略的 `_run_strategy` 全部被卡住。
  - **标准：tick 热路径里禁止 `sleep` 超过心跳间隔；需要等待应放到独立协程/线程，或改为"跳过本轮 + 标记冷却"，让主循环继续转。**

### 🟡 D. 网络 / 桥接健壮性

- [ ] **接收缓冲有上限，解码在收齐后做**
  - 证据：`core/freemt4_bridge.py:88` `_recv_raw` 每次 `recv(500000)` 并**在累积过程中反复 `decode("utf-8")`**——若 UTF-8 多字节字符被截断在 chunk 边界，会抛 `UnicodeDecodeError`；且无总字节上限，EA 异常狂发时会吃光内存。
  - **标准：先把字节收齐到结束符 `!` 再整体 `decode`；加一个最大长度保护（如 `MAX_MSG_BYTES`），超限即断连并报错。**
- [ ] **重连有节流、有上限、有可观测**
  - 证据：`core/freemt4_bridge.py:74` `_try_reconnect` 有 3 秒节流（✅），但无"连续重连 N 次后升级告警"的逻辑。
  - **标准：保留重连节流；增加"重连失败计数 → 触发告警/安全锁"的熔断，避免静默无限重连掩盖 EA 已死。**

### 🟡 E. 数据与持久化

- [ ] **批量写入的"吞异常"必须可解释**
  - 证据：`data/database.py` 的 `insert_trades_batch` / `insert_candles` 用 `try/except: pass` 逐行吞错后照常 `commit`，会出现**静默丢数据**（比如某字段类型变了，整批部分失败却无感知）。
  - **标准：批量写入要么整批失败回滚，要么对每一行失败明确计数+告警；不允许"悄悄跳过"。恢复类逻辑（如 `migrate_from_jsonl`）要有去重与计数日志。**
- [ ] **迁移幂等、可重入**
  - 证据：`migrate_timezone_fix` 用 `metadata` 表做"只跑一次"标记（✅ 很好），`migrate_ticket_to_text` 先改名再建新表（✅ 安全）。
  - **标准：所有 `ALTER`/数据迁移必须幂等；涉及历史数据的迁移先备份再执行，并在 PR 描述里说明"如何回滚"。**

### 🟡 F. 错误处理与可观测性

- [ ] **关键路径禁止 `except Exception: pass`**
  - 证据：`engine_standalone/core_loop.py:85` `_check_news_bias_block` 用 `except Exception: pass` 静默吞掉新闻偏向判断错误 → **fail-open**（出错就不阻断交易）。风控相关 fail-open 是 🔴 级隐患。
  - **标准：风控/新闻/下单相关异常至少 `logger.error` + 计数；不确定时**偏向 fail-safe（保守不交易）而非 fail-open。**
- [ ] **每笔订单/每笔成交都有结构化日志**
  - 证据：`freemt4_bridge.py` 开仓/平仓成功失败都有 `logger.info/error`（✅），`insert_trade` 有记录（✅）。保持。
  - **标准：任何"动钱"动作前后都留 `ticket / symbol / volume / price / sl / tp / magic` 日志，便于事后复盘。**

### 💭 G. 可维护性 / 测试 / 性能

- [ ] **临界纯逻辑必须有单测**
  - 证据：`risk_mgr.py` 已抽成无副作用友好的纯函数（✅ 易于测试），但 `tests/` 下**没有任何 `risk_mgr` / `freemt4_bridge` / `database` 交易写入的测试**（当前仅 12 个测试文件，集中在 agent/mcp/news_filter）。
  - **标准：凡是"算钱/算风控/解析 EA 报文"的函数，必须配单测（含边界：空返回、畸形字段、超阈值）。这是本仓库当前最大的测试缺口。**
- [ ] **解析 EA 报文要测"脏数据"**
  - 证据：`get_indicators`/`get_positions` 用 `$` 切分并 `float()`/`int()`，对字段数不足的返回空（✅ 有兜底），但缺针对"字段错位/部分缺失"的回归测试。
  - **标准：为报文解析加 fuzz/边界测试，防止 EA 升级改字段顺序时静默解析错。**
- [ ] **性能热点有基线**
  - DataFactory 增量拉 K 线 + TA-Lib 算 26+ 指标是性能核心；任何改动需确认不引入 O(n²) 或重复全量重算。

---

## 六、自动化检查建议（把标准"卡"进流程）

把人工审查重点从"格式/类型"释放到"资金/风控"，靠工具兜底机械项：

1. **Pre-commit（本地提交前）**
   - `ruff` / `flake8`：语法、未用导入、基础坏味道。
   - `black`：统一格式（或 `ruff format`）。
   - `bandit`：扫描硬编码密钥、危险函数（`eval`、`subprocess` 不校验输入等）。
   - `detect-secrets` / `gitleaks`：**密钥入库即拦**（针对 `llm_providers.json` 类明文风险）。
   - 推荐 `.pre-commit-config.yaml` 片段见文末。
2. **CI（PR 时，门槛：全绿才允许合并）**
   - `mypy --strict`（或 `pyright`）覆盖 `core/`、`engine_standalone/`、`services/` 关键模块。
   - `pytest tests/` 必须全过；**新增资金/风控/解析代码须带新单测**，CI 用覆盖率门禁（如关键模块 ≥ 70%）。
   - 跑一遍 `python tools/check_setup.py` 确认环境一致。
3. **AI 预审（火眼眼）**
   - 每次 PR 自动按第五节清单过一遍，输出带分级的评论；🔴 直接标红，由人工终审。
   - 对"下单/风控/桥接/DB 写入"改动额外触发一次"资金路径专项检查"。

> 注意：自动化只查机械项，**资金语义正确性（如"这个 sl 算得对不对"）必须人工判断**。

---

## 七、提交前自检清单（作者填在 PR 描述里）

```
□ 本次改动是否触及：下单 / 平仓 / 风控 / 桥接 / 数据库写入？（若是，已请 Risk Owner 评审）
□ 所有"读取报价/指标"的失败路径都返回 None/抛错，而不是 0.0 等假正常值
□ SL/TP/价格字段用 Optional，未用 0.0 表达"未设置"
□ 下单失败有明确回执，不会被静默吞掉
□ 无密钥入库、无密钥打印；SQL 全部参数化
□ tick 热路径无长时间 sleep；共享状态已加锁/已注明归属线程
□ 批量写入无"悄悄吞异常"；迁移幂等可回滚
□ 风控/新闻相关异常未被 except: pass 吞掉（fail-safe 而非 fail-open）
□ 新增/修改的"算钱/算风控/报文解析"函数已加单测（含边界）
□ 确认性指标取自已闭合 K 线（bar1 / F043 shift=1），forming bar 仅用于价格触发、未在其上做判定
□ 无策略内自算买卖指标（未在 self.candles 上 import talib/numpy 重算 RSI/ATR/BB/MACD/Stoch/ADX 等，一律走 get_indicator）
□ 已在纸面/模拟环境跑过一个完整 tick 周期验证
```

---

## 八、评审评论格式与礼仪（导师式，不居高临下）

每条评论固定三段，便于作者直接照做：

```
🔴 **资金安全：SL 被 0 静默关闭**
core/freemt4_bridge.py:357 — open_order 把 sl=None 兜底成 0，而 0 在 MT4 表示不挂止损。

**为什么：** 一旦调用方漏传 sl，风控止损会悄无声息失效，浮亏可能无限扩大。

**建议：** 入口改 `assert sl is None or sl > 0`；用 Optional 区分"不挂"与"传了价"。
```

礼仪：
- 先给**总体印象** + **值得肯定的地方**（本项目已有不少好实践：纯函数风控、参数化 SQL、WAL、`_sanitize` 脱敏、重连节流——要大声表扬）。
- 问问题而非下结论：意图不清时用"这里的 0 是想表达不挂止损吗？"而不是"你这里写错了"。
- 🔴 给"为什么 + 怎么改"；💭 给"另一种思路"。
- 结尾鼓励 + 下一步。

---

## 九、本仓库已具备的好实践（保持，并在评审中显式点赞）

- `engine_standalone/risk_mgr.py`：把风控状态抽成 `@dataclass` + 纯函数，易测易扩展。
- `data/database.py`：SQL 基本全参数化；迁移用 `metadata` 标记保证幂等；WAL + `busy_timeout` 抗并发。
- `core/freemt4_bridge.py`：重连有 3s 节流；socket 超时按指令类型分级；开仓/平仓有结构化日志。
- `services/llm_provider.py`：`_sanitize` 对外隐藏 API Key；支持 env 覆盖 + 故障转移到其他 provider。

---

## 附录 A：推荐 `.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.9
    hooks:
      - id: bandit
        args: ["-c", "pyproject.toml", "-r", "core,engine_standalone,services,dashboard/backend"]
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
```

## 附录 B：推荐 CI（GitHub Actions 风格）

```yaml
name: review-gate
on: [pull_request]
jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install ruff mypy pytest bandit
      - run: ruff check core engine_standalone services dashboard/backend
      - run: mypy core engine_standalone services
      - run: bandit -r core engine_standalone services -c pyproject.toml
      - run: pytest tests/ -q
```

---

*本标准随项目演进，由 Reviewer 在每次"资金/风控路径"评审后收集共性问题，季度更新一次。*
