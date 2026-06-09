# AI 助理模块 — 浮动面板 + 接入Claude/GPT

日期：2026-06-09
状态：设计方案（待开发）

## Context

用户在交易仪表盘中增加 AI 助理模块，需求有三层：
1. **对话可追溯** — 当前的聊天（Claude Code）会话结束就没了，查不到历史
2. **交易上下文感知** — AI 能自动读取持仓、账户、信号、行情，问什么都知道
3. **给其他人用** — 未来系统给别人用时，内置助理降低使用门槛

交互方式：浮动面板（右下角），卡通形象触发（送财童子），点开弹出聊天窗口覆盖在所有页面上。

技术选型：
- 后端：FastAPI SSE 流式响应
- AI API：可配置 Anthropic / OpenAI（用户自备 API key）
- 前端：Vue 3 + Naive UI 浮动面板组件
- 存储：SQLite 新表 chat_sessions + chat_messages

---

## 实施步骤

### 1. 数据库 — 新表

**文件**: `data/database.py`

在 SCHEMA 末尾追加：

```sql
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'New Conversation',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
    content TEXT NOT NULL,
    tokens INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id, id);
```

新增 CRUD 函数：`create_chat_session`, `list_chat_sessions`, `get_chat_session`, `delete_chat_session`, `save_chat_message`, `get_chat_messages`

### 2. 设置 — AI 配置默认值

**文件**: `config/settings.py`

追加：
```python
AI_API_KEY = ""
AI_PROVIDER = "anthropic"
AI_MODEL = "claude-sonnet-4-20250514"
AI_BASE_URL = ""
AI_MAX_TOKENS = 4096
AI_TEMPERATURE = 0.7
AI_ENABLED = True
```

### 3. 运行时配置 — 暴露 AI 密钥管理

**文件**: `dashboard/backend/config_service.py`

- 在 `_get_default()` 中添加 AI 各字段到 settings.py 的映射
- `get_all()` 返回时包含 `has_api_key: bool` 但不暴露原始密钥
- 密钥通过 `POST /api/ai/config` 单独设置

### 4. AI 服务模块（核心）

**新文件**: `dashboard/backend/ai_service.py`

三个功能：
1. `build_trading_context()` — 从 DB + 引擎缓存收集账户/持仓/信号/行情/策略摘要
2. `build_system_prompt(context)` — 用上下文组装 AI 系统提示，定位为交易助手
3. `chat_stream()` — 流式调用 AI API，支持 Anthropic（官方 SDK）和 OpenAI（httpx）
   - Anthropic: 用 `AsyncAnthropic.messages.stream()` 
   - OpenAI: 用 `httpx.AsyncClient` 流式 POST

### 5. AI 路由

**新文件**: `dashboard/backend/routes/ai.py`

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | /api/ai/config | 获取 AI 配置（不含 key） |
| POST | /api/ai/config | 更新 AI 配置 |
| GET | /api/ai/sessions | 列出会话列表 |
| POST | /api/ai/sessions | 创建新会话 |
| DELETE | /api/ai/sessions/{id} | 删除会话 |
| GET | /api/ai/history/{id} | 获取某会话历史消息 |
| POST | /api/ai/chat | **流式聊天**（SSE）|

`/chat` 端点是核心：
1. 保存用户消息到 DB
2. 构建交易上下文 → 系统提示
3. 组装消息历史（最近 50 条）
4. 调用 `chat_stream()` 流式返回
5. 完整响应完成后保存到 DB

### 6. 注册路由

**文件**: `dashboard/backend/main.py`

- 新增 import: `from dashboard.backend.routes import ai as route_ai`
- 注入 `route_ai.config_service = config_service`
- 注册 `app.include_router(route_ai.router)`

### 7. 前端类型

**文件**: `dashboard/frontend/src/types/index.ts`

新增接口：`ChatSession`, `ChatMessage`, `AiConfig`, `ChatSseChunk`

### 8. 前端 API 客户端

**文件**: `dashboard/frontend/src/api/client.ts`

新增方法：`getAiConfig`, `updateAiConfig`, `listChatSessions`, `createChatSession`, `deleteChatSession`, `getChatHistory`

### 9. Chat Pinia Store

**新文件**: `dashboard/frontend/src/stores/chat.ts`

管理状态：
- 面板开关、设置窗口开关
- 会话列表、当前会话、消息列表
- SSE 流式状态（streaming / streamBuffer / streamError）
- AI 配置（provider / model / hasApiKey）

### 10. ChatMessage 组件

**新文件**: `dashboard/frontend/src/components/chat/ChatMessage.vue`

- 用户消息：右对齐，金色背景
- AI 消息：左对齐，深灰背景
- 流式中的消息显示打字动画

### 11. AiChatPanel 组件（核心）

**新文件**: `dashboard/frontend/src/components/chat/AiChatPanel.vue`

包含全部状态的处理：

| 状态 | 表现 |
|------|------|
| 折叠态 | 右下角 **送财童子卡通形象**，点击展开 |
| 未配置 API Key | 欢迎页面引导配置，输入禁用 |
| 无会话 | 欢迎页面 + "开始新对话" 按钮 |
| 加载中 | 中央 spin 动画 |
| 空闲 | 消息列表 + 输入框就绪 |
| 流式响应 | 输入禁用，AI 消息实时追加内容，打字动画 |
| 流式错误 | 红色错误提示 + 重试按钮 |

**送财童子实现方案**（折叠态）：
- 用 CSS 绘制一个圆形卡通头像 + 金色元宝/铜钱元素
- 或者用 emoji 🧧 + 圆形背景 + 微动画（呼吸光效/浮动效果）
- 尺寸稍大（56px），点击触发展开
- 不直接用纯气泡图标，而是有角色感的形象

### 12. 注册到 App.vue

**文件**: `dashboard/frontend/src/App.vue`

- import AiChatPanel
- 在 `<n-config-provider>` 末尾添加 `<AiChatPanel />`

---

## 执行顺序

1. `data/database.py` — 加表 + CRUD
2. `config/settings.py` — AI 配置默认值
3. `dashboard/backend/config_service.py` — AI 配置暴露
4. `dashboard/backend/ai_service.py` — AI 服务
5. `dashboard/backend/routes/ai.py` — API 路由
6. `dashboard/backend/main.py` — 注册路由
7. 前端类型 + API 客户端
8. `stores/chat.ts` — Pinia store
9. `ChatMessage.vue` + `AiChatPanel.vue` — 组件
10. `App.vue` — 注册面板

## 需要用户准备的

1. Anthropic API Key 或 OpenAI API Key（配置在面板设置中）
2. pip 确认 `httpx` 和 `anthropic` 包已安装

## Verify

1. 启动 Dashboard，右下角出现送财童子卡通按钮
2. 点击弹出聊天面板，未配置时引导设置 API Key
3. 配置 Key 后新建会话，发送消息，AI 流式返回
4. AI 自动知道当前持仓、账户余额、信号
5. 关闭面板再打开，历史消息还在
6. 切换/删除会话正常工作
7. 数据库 `chat_messages` 表能看到所有对话记录

## 后续可能扩展

- 送财童子形象可以用 SVG 或 Lottie 动画做得更精致
- 对话搜索功能
- AI 主动推送交易提醒（通过 WebSocket）
- 多语言支持
