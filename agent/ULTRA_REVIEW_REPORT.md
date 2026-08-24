# 🔍 Ultra Review 审查报告 — AlgoForge「金探」Agent

## 审查对象
- **Agent 名称**：金探
- **应用**：AlgoForge XAUUSD v3.3.8
- **文件位置**：D:\backup\BaoBao\PythonProgram\xauusd\services\agent\

## 总评

| 维度 | 评分 (1-10) | 关键发现 |
|------|-------------|----------|
| 灵魂 (Soul) | 7/10 | 人设定义清晰有辨识度，但 settings 表缺失导致持久化失败，且存在硬编码 SYSTEM_PROMPT 冗余 |
| 技能 (Skill) | 4/10 | 三个技能仅为提示词级别的大纲，全量注入浪费 token，无按需选择机制 |
| 连接器 (Connector) | 3/10 | ToolRegistry 设计良好但完全空置，无 MCP，无工具实际注册，LLM Provider 每次调用重新实例化 |
| 体验 (Experience) | 6/10 | 前端 UI 精致，快捷指令实用，但无历史消息截断、无重试机制、Provider 配置路径较深 |
| 架构 (Architecture) | 5/10 | 模块化合理但存在同步阻塞事件循环、单例不一致、无消息历史限制等工程问题 |
| **综合** | **5/10** | 框架骨架完整但关键连接器空置，是一个有潜力但尚未完工的 Agent 系统 |

## 详细发现

### 第一维：灵魂审查 (Soul Audit) — 7/10

**角色清晰度 (8/10)**：
DEFAULT_PERSONA 定义了明确的角色身份：「专业的 XAUUSD 黄金量化交易分析师，内置于 AlgoForge 交易系统中」。包含 role、style、expertise、limits 四个维度，覆盖了能力边界和风格约束。

代码证据：`persona_manager.py` L12-19 DEFAULT_PERSONA 字典包含 name/role/style/expertise/limits/language 字段。

**性格辨识度 (7/10)**：
style 字段明确规定「简洁专业，不废话」「涉及风险时主动提示」「不确定时不编造数据」。这些约束能从 AI 回复中识别出「金探」的风格。

**行为一致性 (6/10)**：
`build_system_prompt()` 方法 (L106-115) 正确将人设字段组装为 System Prompt。但存在严重问题：`ai_service.py` L21-40 有一个遗留的硬编码 SYSTEM_PROMPT 常量，虽然当前未被调用（`build_system_prompt()` 函数使用动态人设），但与动态人设并存造成混乱和维护负担。

**边界感知 (8/10)**：
limits 字段明确规定「不直接执行交易」「不预测精确价格点位」。这对交易场景非常重要，防止 AI 误导用户。delete_persona() 保护默认「金探」不被删除 (L94-96)。

**价值主张 (7/10)**：
结合实时交易上下文（持仓、指标、新闻、策略）提供分析，这是独特的价值。ContextBuilder 收集 10 类实时数据注入 System Prompt，让 AI 拥有「当前视野」。

**可扩展性 (6/10)**：
支持多 persona 切换、创建、删除，保护默认「金探」不被删除 (L94-96)。但 **settings 表在 database.py SCHEMA 中缺失**，导致 `_load_from_db()` 和 `_save_to_db()` 每次都会抛异常，人设修改永远无法持久化。重启后总是恢复默认。

代码证据：`database.py` SCHEMA 字符串 (L22-293) 中没有 `CREATE TABLE IF NOT EXISTS settings`。persona_manager L37 查询 `SELECT value FROM settings WHERE key=?` 必然失败。异常被 L51-54 的 try/except 静默捕获，回退到默认人设。

### 第二维：技能审查 (Skill Matrix) — 4/10

**技能覆盖度 (4/10)**：
三个技能（行情研判、持仓诊断、风险检查）均为 SKILL.md 文件，内容仅 5-11 行的分析要点大纲。每个技能只有「分析要点」列表，无具体的分析框架、评分标准或输出模板。

代码证据：`skills/market_analysis/SKILL.md` 仅 11 行，包含 5 个分析要点。其余两个技能类似。

**技能深度 (3/10)**：
技能内容极其简略。以「持仓诊断」为例，它列出了 5 个诊断要点，但没有定义健康度评估标准、风险阈值或具体的建议生成规则。LLM 只能凭自身能力发挥，技能文件本身提供的增量知识极为有限。

**技能组合 (4/10)**：
三个技能之间没有协同机制。它们被全量注入 System Prompt，LLM 自行决定如何组合使用。没有技能编排、无任务路由、无多步骤工作流。

**容错能力 (5/10)**：
SkillLoader 的 scan() 方法有路径容错 (L40-41)，解析失败不会崩溃。但技能本身没有降级策略：如果某个技能的上下文数据不可用（如无持仓时调用持仓诊断），没有显式处理。

**可验证性 (3/10)**：
技能是纯描述性的提示词，无法单独测试。没有单元测试、无集成测试、无评估基准。

**技能注入方式 (3/10)**：
`ai_service.py` L60 调用 `loader.get_all_context()` 将所有技能全量注入 System Prompt。这意味着每次对话都携带全部技能描述，浪费 token。合理的做法是按需加载：用户问行情时只注入行情研判技能。

代码证据：`skill_loader.py` L88-93 `get_all_context()` 合并所有技能；`ai_service.py` L60 调用它并注入 context。

### 第三维：连接器审查 (Connector Audit) — 3/10

**ToolRegistry 设计 vs 实际使用 (2/10)**：
ToolRegistry 设计良好：支持动态参数推断 (inspect.signature)、分类管理、OpenAI function calling 格式输出 (to_openai_tools)。但 **没有任何工具被实际注册**。全局搜索 `register(` 和 `get_registry` 在整个项目中零匹配。Agent 完全无法主动查询任何信息。

代码证据：`tool_registry.py` 定义了完整的 register/call/list_tools/to_openai_tools，但 grep 全项目无任何调用。

**ContextBuilder 作为唯一信息通道 (6/10)**：
10 个 section 设计较好，支持按需选择。但问题：
- 直接访问 engine 内部属性 (`_cached_account`, `_fresh_positions()`, `_cached_price`)，违反封装原则
- 每次 build() 都重新查询数据库（信号、成交、新闻），无缓存
- 循环依赖：`_section_news()` 导入 `ai_service._get_latest_news`，而 ai_service 又调用 context_builder

**LLM Provider 管理 (5/10)**：
- 支持多 Provider（DeepSeek/Agnes/GLM/Mimo/Ollama），CRUD 完整
- 环境变量优先级机制合理
- 代理自动检测 (L286-294) 有创意但生产环境不可靠（socket 探测本地端口）
- **严重问题**：`_stream_chat()` L167 每次调用都创建新的 `LLMProviderManager()`，重新加载 JSON 配置文件。同样，`routes/llm_provider.py` L11 也有独立实例。多个实例并存存在状态不一致风险。
- 单激活模式，无故障转移：激活的 Provider 失败时不会自动切换到备用

**MCP 连接器 (0/10)**：
无 MCP 服务器连接。Agent 无法与外部工具链集成。

**SSE 流式通信 (6/10)**：
前端 SSE 实现较好：`chat.ts` 使用 ReadableStream 解析，支持完成标记和错误处理。但后端 `_stream_chat()` 在 async 函数中使用同步 `httpx.Client`，阻塞事件循环。

代码证据：`routes/ai.py` L164 `def _stream_chat()` 是同步函数，L203 使用 `httpx.Client`（同步）而非 `httpx.AsyncClient`。该函数在 L142 的 `async def stream()` 生成器中被调用，阻塞整个事件循环。

**前端 UI 交互质量 (7/10)**：
AiChatPanel.vue 设计精致：拖拽浮动面板、会话列表 Drawer、快捷指令栏、打字动画、空状态引导。金色主题 (#f0b90b) 与黄金交易主题契合。AiAgentConfig.vue 提供完整的 Provider CRUD 和人设编辑界面。

### 第四维：体验审查 (Experience Review) — 6/10

**发现性 (6/10)**：
聊天面板是浮动在 dashboard 上的组件，需要关闭才能看到（emit('close')）。没有明显的入口按钮或菜单项提示用户 AI 功能的存在。快捷指令（行情研判/持仓诊断/新闻解读等）在空状态时有引导展示，这是好的。

**配置体验 (5/10)**：
Provider 配置在 AiAgentConfig.vue 中，卡片式 UI 较直观。但配置路径较深：需要先在设置页配置 Provider → 获取 API Key → 填入 → 测试连接 → 激活。没有「一键配置」或默认 Provider 引导。首次使用时所有 Provider 的 is_active 都是 False，用户需要手动配置才能使用。

**交互流畅度 (7/10)**：
- 快捷指令设计实用（6 个预设命令覆盖主要场景）
- SSE 流式输出体验好，逐字显示
- 会话管理完整（新建/切换/删除/自动标题）
- 但 `AiChatPanel.vue` L35-39 和 L56-59 有重复的 `onMounted` 钩子，`fetchSessions()` 被调用两次

代码证据：`AiChatPanel.vue` 有两个 `onMounted` 块（L35 和 L56），都调用 `chat.fetchSessions()`。

**结果质量 (7/10)**：
ContextBuilder 注入 10 类实时上下文，让 AI 回答有据可依。但：
- **无消息历史截断**：`routes/ai.py` L128-137 将所有历史消息发送给 LLM，长对话会超出 token 限制
- 每次对话都重新构建完整 System Prompt + 全量技能 + 全量上下文 + 全量历史，效率低

**错误恢复 (4/10)**：
- LLM 调用失败时显示「⚠️ 调用失败」，但没有重试机制
- 没有 Provider 故障转移
- 没有请求超时后的用户提示（timeout 设为 60s，用户需等待很久）
- Provider 未配置时的提示友好（「请在设置 → AI Agent 页面配置」）

### 第五维：架构审查 (Architecture Review) — 5/10

**模块化设计 (7/10)**：
agent 包分为 4 个模块（persona_manager/skill_loader/tool_registry/context_builder），职责清晰。`__init__.py` 导出正确。与外部通过 `ai_service.py` 桥接。但模块间存在循环依赖风险（context_builder ↔ ai_service）。

**代码质量 — Bug 和反模式**：

1. **settings 表缺失 (P0)**：`database.py` SCHEMA 无 settings 表，persona 持久化永远失败
2. **同步阻塞事件循环 (P0)**：`_stream_chat()` 在 async 上下文中使用同步 httpx
3. **LLMProviderManager 多实例 (P1)**：`_stream_chat()` L167、`routes/llm_provider.py` L11、`services/huicong_news.py` L432、`services/news_filter.py` L214 各自创建独立实例
4. **无消息历史截断 (P1)**：`routes/ai.py` L128-137 发送全部历史消息
5. **重复 onMounted (P2)**：`AiChatPanel.vue` L35 和 L56 重复注册
6. **context_snapshot 预留未用 (P2)**：`chat_messages` 表有 context_snapshot 字段，`add_message()` 接受该参数但始终传空字符串
7. **signals 表 status/void_reason 列依赖迁移 (P2)**：`context_builder.py` L155 查询 `SELECT strategy, signal, status, void_reason, timestamp FROM signals`，但 status 和 void_reason 是通过 `migrate_signals_lifecycle()` ALTER TABLE 添加的，如果迁移未运行会报错

**数据流设计 (6/10)**：
用户输入 → routes/ai.py chat_api → build_system_prompt() → [ContextBuilder.build() + SkillLoader.get_all_context() + PersonaManager.build_system_prompt()] → _stream_chat() → LLM API → SSE → 前端

调用链清晰但有问题：
- build_system_prompt() 每次调用都触发全量数据收集
- 历史消息在 chat_api 中组装，与 ai_service 的会话管理耦合
- `_stream_chat()` 每次创建新 LLMProviderManager 实例

**可扩展性 (6/10)**：
- 新增技能：只需在 skills/ 目录添加 SKILL.md，SkillLoader 自动扫描 ✓
- 新增人设：通过 API/UI 创建 ✓
- 新增工具：ToolRegistry 支持注册，但无实际工具可参考 ✗
- 新增 Provider：UI 支持 ✓
- 新增 MCP：无基础设施支持 ✗

**安全性 (5/10)**：
- API Key 在 JSON 文件中明文存储（`data/llm_providers.json`）
- `_sanitize()` 方法在 API 返回时隐藏 Key，但文件本身不安全
- 前端 `AiAgentConfig.vue` L56 编辑时能获取到 masked key（但不应如此）
- 无输入验证/过滤：用户消息直接拼入 messages 数组发给 LLM
- 无速率限制：chat API 无防刷保护

## 亮点 ✨

1. **ContextBuilder 的 10 维实时上下文**：引擎状态/持仓/价格/指标/K线/信号/成交/策略/新闻/日历，让 AI 拥有交易系统的「全景视野」，这是同类系统的差异化优势
2. **前端 UI 设计精致**：浮动拖拽面板、金色主题、打字动画、会话 Drawer、快捷指令，用户体验考虑周到
3. **ToolRegistry 的 OpenAI function calling 兼容**：`to_openai_tools()` 方法直接输出标准格式，为未来 function calling 集成打好基础
4. **SkillLoader 的 skillhub 兼容设计**：YAML frontmatter + body 格式与生态兼容，扫描加载机制完善
5. **LLM Provider 的环境变量覆盖机制**：支持 .env / 环境变量 / JSON 文件三级配置，部署灵活
6. **代理自动检测**：`llm_provider.py` L286-294 自动检测本地 SOCKS5 代理端口，对中国用户友好
7. **人设保护机制**：默认「金探」不可删除，保证系统始终有基础人设

## 问题清单 🐛

| 优先级 | 问题 | 影响 | 建议修复方案 |
|--------|------|------|--------------|
| P0 | settings 表在 database.py SCHEMA 中缺失 | 人设持久化永远失败，修改/切换人设重启后丢失 | 在 SCHEMA 中添加 `CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)` |
| P0 | `_stream_chat()` 在 async 上下文中使用同步 httpx.Client | 阻塞 FastAPI 事件循环，并发请求时所有用户卡顿 | 改用 `httpx.AsyncClient` + `async with client.stream()` |
| P1 | ToolRegistry 完全空置，无工具注册 | Agent 无法主动查询信息，只能被动依赖 ContextBuilder 注入的上下文 | 注册核心工具：get_positions, get_indicators, get_trades_history, get_account_info |
| P1 | ai_service.py 顶部遗留硬编码 SYSTEM_PROMPT | 与动态人设并存造成混乱，可能被误用 | 删除 L21-40 的硬编码常量，或标注为 deprecated |
| P1 | LLMProviderManager 多处独立实例化 | 状态不一致，每次调用重新读取 JSON 文件 | 改为全局单例模式，类似 PersonaManager 的 `_persona_mgr` 模式 |
| P1 | 无消息历史截断 | 长对话超出 LLM token 限制，导致调用失败 | 在 `chat_api()` 中限制历史消息数量（如最近 20 条），或实现 token 计数截断 |
| P1 | 技能全量注入 System Prompt | 每次对话浪费 token，技能越多问题越严重 | 实现按需加载：根据用户消息关键词选择相关技能注入 |
| P2 | AiChatPanel.vue 重复 onMounted | fetchSessions() 被调用两次，浪费一次 API 请求 | 合并两个 onMounted 为一个 |
| P2 | context_snapshot 字段预留未使用 | 数据库字段浪费，无法回溯 AI 回答时的上下文 | 在 build_system_prompt() 返回时同时保存快照，传入 add_message() |
| P2 | ContextBuilder 直接访问 engine 私有属性 | 违反封装，engine 内部重构会导致 ContextBuilder 崩溃 | 为 engine_runner 添加公开 API 方法：get_account_info(), get_positions() 等 |
| P2 | context_builder ↔ ai_service 循环依赖 | _section_news() 导入 ai_service._get_latest_news，而 ai_service 调用 context_builder | 将 _get_latest_news 和 _get_today_calendar 移到 context_builder 或独立的 news_service |
| P2 | API Key 明文存储在 JSON 文件 | 文件泄露即 Key 泄露 | 使用系统密钥链或加密存储，至少对文件设置权限限制 |
| P2 | 无 LLM 故障转移 | 激活的 Provider 宕机时用户无法使用 AI | 实现 fallback 链：主 Provider 失败时自动尝试下一个 |

## 改进路线图

### 短期（1-2 周）— 修复关键 Bug
1. 在 database.py SCHEMA 中添加 settings 表定义
2. 将 `_stream_chat()` 改为异步实现（httpx.AsyncClient）
3. 删除 ai_service.py 中的硬编码 SYSTEM_PROMPT
4. 合并 AiChatPanel.vue 的重复 onMounted
5. 添加消息历史截断（限制最近 20 条）

### 中期（1-2 月）— 补全核心能力
1. 注册 5-8 个核心工具到 ToolRegistry（持仓查询、指标查询、成交历史、账户信息等）
2. 将 LLMProviderManager 改为全局单例
3. 实现技能按需加载（基于关键词匹配或 LLM 自主选择）
4. 解除 context_builder ↔ ai_service 循环依赖
5. 丰富技能内容：为每个技能添加分析框架、评分标准、输出模板
6. 添加 API Key 加密存储

### 长期（3-6 月）— 架构升级
1. 实现 LLM Provider 故障转移链
2. 引入 MCP 协议支持，让 Agent 可连接外部工具
3. 为 ContextBuilder 添加缓存层（TTL 30s），减少 DB 查询
4. 实现 function calling 集成：让 Agent 能主动调用注册的工具获取信息
5. 添加对话质量评估和反馈机制
6. 实现人设版本控制和回滚
7. 添加速率限制和输入安全过滤
8. 考虑引入对话摘要机制，支持超长对话的上下文压缩
