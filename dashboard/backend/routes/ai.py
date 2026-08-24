"""
/api/ai 路由 — AI 交易助理（会话管理 + SSE 流式对话）
"""
import asyncio
import json
import logging
import os
import time

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from services.llm_provider import LLMProviderManager
import httpx

from dashboard.backend.ai_service import (
    build_system_prompt,
    create_session,
    list_sessions,
    get_messages,
    add_message,
    delete_session,
    update_session_title,
    auto_title,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])
logger = logging.getLogger("dashboard.backend.routes.ai")

_llm_manager = LLMProviderManager()

# 记忆自动积累后台任务引用集合（防 GC）
_accumulate_tasks: set = set()


class ToolsNotSupported(Exception):
    """模型不支持 tools 参数 — 信号异常，由 chat_api 外层降级到原流式路径"""


# 已确认不支持 tools 参数的模型黑名单：模型名 → 失效时间戳（dict[str, float]）。
# 命中则直接抛 ToolsNotSupported 让外层降级；TTL 过期后自动恢复，避免永久误判。
_tools_unsupported_models: dict = {}

# 黑名单 TTL（秒）
_TOOLS_UNSUPPORTED_TTL = 600

# 400 响应体中判定「模型不支持 tools」的明确短语（收窄判定，
# 避免含 tool/function 字样的普通业务错误被误判为不支持）
_TOOLS_UNSUPPORTED_PHRASES = (
    "does not support",
    "not support",
    "unsupported",
    "unknown parameter",
    "invalid parameter",
    "unrecognized parameter",
)


def _model_tools_unsupported(model: str) -> bool:
    """查询模型黑名单（带 TTL 剪枝：过期项删除，模型自动恢复 tools 能力）"""
    expire_at = _tools_unsupported_models.get(model)
    if expire_at is None:
        return False
    if time.time() >= expire_at:
        _tools_unsupported_models.pop(model, None)
        return False
    return True

# 工具循环最大轮次
_MAX_TOOL_ROUNDS = 5

# 单次工具执行超时（秒）
_TOOL_EXECUTE_TIMEOUT = 30.0

# 非流式最终答案分块大小（字符）
_FINAL_CHUNK_SIZE = 20


def _build_llm_headers(provider: dict) -> dict:
    """构造 LLM 请求头（与 _stream_chat 相同逻辑，供工具路径共用）"""
    headers = {"Content-Type": "application/json"}
    if provider.get("type") != "ollama":
        headers["Authorization"] = f"Bearer {provider['api_key']}"
    return headers


def _build_llm_client_kwargs(provider: dict) -> dict:
    """构造 httpx.AsyncClient 参数（与 _stream_chat 相同逻辑：固定超时 + 环境变量代理）"""
    client_kwargs = {"timeout": 60, "http2": False}
    proxy = os.environ.get("LLM_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
    if proxy:
        client_kwargs["proxy"] = proxy
    return client_kwargs


class ChatRequest(BaseModel):
    session_id: str
    message: str


class CreateSessionRequest(BaseModel):
    title: str = "新会话"


class UpdateTitleRequest(BaseModel):
    title: str


@router.get("/sessions")
async def list_sessions_api():
    """列出所有聊天会话"""
    return {"sessions": list_sessions()}


@router.post("/sessions")
async def create_session_api(req: CreateSessionRequest):
    """创建新会话"""
    return create_session(req.title)


@router.get("/sessions/{session_id}/messages")
async def get_messages_api(session_id: str):
    """获取会话所有消息"""
    messages = get_messages(session_id)
    if not messages and not _session_exists(session_id):
        raise HTTPException(404, "会话不存在")
    return {"messages": messages}


@router.delete("/sessions/{session_id}")
async def delete_session_api(session_id: str):
    """删除会话"""
    ok = delete_session(session_id)
    if not ok:
        raise HTTPException(404, "会话不存在")
    return {"message": "已删除"}


@router.put("/sessions/{session_id}/title")
async def update_title_api(session_id: str, req: UpdateTitleRequest):
    """更新会话标题"""
    ok = update_session_title(session_id, req.title)
    if not ok:
        raise HTTPException(404, "会话不存在")
    return {"message": "已更新"}


class PersonaUpdateRequest(BaseModel):
    soul: str = ""
    memory: str = ""


@router.get("/persona")
async def get_persona():
    """获取 soul.md / memory.md 双文件人设"""
    from services.agent.persona_manager import get_persona_manager, MAX_PERSONA_CHARS
    mgr = get_persona_manager()
    return {
        "soul": mgr.load_soul(),
        "memory": mgr.load_memory(),
        "soul_limit": MAX_PERSONA_CHARS,
    }


@router.put("/persona")
async def set_persona(req: PersonaUpdateRequest):
    """保存 soul/memory 双文件人设（各 ≤2000 字，超限 400）"""
    from services.agent.persona_manager import get_persona_manager
    from fastapi.responses import JSONResponse
    mgr = get_persona_manager()
    try:
        mgr.save_soul(req.soul)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": "人设超过 2000 字限制", "current_chars": len(req.soul)},
        )
    try:
        mgr.save_memory(req.memory)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": "日常记忆超过 2000 字限制", "current_chars": len(req.memory)},
        )
    return {"success": True, "soul_chars": len(req.soul), "memory_chars": len(req.memory)}


@router.get("/skills")
def list_skills():
    """列出全部已加载技能（含禁用），带启用状态与来源标识"""
    from services.agent.skill_loader import get_loader
    from services.agent.skill_config import get_config
    from services.agent.skill_marketplace import SKILL_PLATFORMS
    loader = get_loader()
    if not loader.all_skills():
        loader.rescan()
    config = get_config()
    installed_map = {r.get("name"): r for r in config.get_installed()}
    platform_name = {p["id"]: p["name"] for p in SKILL_PLATFORMS}
    custom_dirs = [os.path.normpath(d) for d in config.get_custom_dirs()]
    skills = []
    for s in loader.all_skills():
        spath = os.path.normpath(s.path or "")
        rec = installed_map.get(s.name)
        if rec:
            pid = rec.get("source_platform", "")
            source = pid if pid in platform_name else "paste"
            source_label = platform_name.get(pid, "粘贴导入")
        elif any(spath.startswith(d + os.sep) for d in custom_dirs):
            source, source_label = "local", "本地目录"
        else:
            source, source_label = "builtin", "内置"
        skills.append({
            "name": s.name,
            "description": s.description,
            "enabled": config.is_enabled(s.name),
            "source": source,
            "source_label": source_label,
        })
    return {"skills": skills}


@router.put("/skills/{skill_name}/enable")
async def enable_skill(skill_name: str):
    """启用指定技能"""
    from services.agent.skill_config import get_config
    config = get_config()
    config.set_enabled(skill_name, True)
    return {"ok": True, "skill": skill_name, "enabled": True}


@router.put("/skills/{skill_name}/disable")
async def disable_skill(skill_name: str):
    """禁用指定技能"""
    from services.agent.skill_config import get_config
    config = get_config()
    config.set_enabled(skill_name, False)
    return {"ok": True, "skill": skill_name, "enabled": False}


class LocalDirRequest(BaseModel):
    path: str


def _dir_has_skill_md(path: str) -> bool:
    """目录（递归）内是否含 SKILL.md"""
    for _root, _dirs, files in os.walk(path):
        if any(f.lower() == "skill.md" or f.endswith(".skill.md") for f in files):
            return True
    return False


@router.get("/skills/local-dirs")
def list_local_dirs():
    """已注册的本地技能目录列表"""
    from services.agent.skill_config import get_config
    return {"dirs": get_config().get_custom_dirs()}


@router.post("/skills/local-dir")
def add_local_dir(req: LocalDirRequest):
    """注册本地技能目录（需存在且含 SKILL.md），然后触发重扫"""
    from services.agent.skill_config import get_config
    from services.agent.skill_loader import get_loader
    path = os.path.normpath(os.path.abspath(req.path or ""))
    if not os.path.isdir(path):
        return JSONResponse(status_code=400, content={"error": f"目录不存在：{path}"})
    if not _dir_has_skill_md(path):
        return JSONResponse(status_code=400, content={"error": f"目录下未找到 SKILL.md：{path}"})
    try:
        get_config().add_custom_dir(path)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    count = get_loader().rescan()
    return {"ok": True, "path": path, "skill_count": count}


@router.delete("/skills/local-dir")
def remove_local_dir(req: LocalDirRequest):
    """取消注册本地技能目录，然后触发重扫"""
    from services.agent.skill_config import get_config
    from services.agent.skill_loader import get_loader
    removed = get_config().remove_custom_dir(req.path or "")
    count = get_loader().rescan()
    return {"ok": removed, "skill_count": count}


@router.post("/skills/rescan")
def rescan_skills():
    """手动重扫技能目录"""
    from services.agent.skill_loader import get_loader
    count = get_loader().rescan()
    return {"ok": True, "skill_count": count}


@router.get("/tools")
async def list_tools():
    """列出已注册的 AI 工具"""
    from services.agent.tool_registry import get_registry
    registry = get_registry()
    return {"tools": registry.list_tools()}


def _masked_settings_payload() -> dict:
    """返回 agent 设置（smithery_api_key 打码 + configured 标志）"""
    from services.agent.agent_settings import get_all, mask_key
    settings = dict(get_all())
    raw_key = str(settings.get("smithery_api_key") or "")
    settings["smithery_api_key"] = mask_key(raw_key)
    settings["smithery_api_key_configured"] = bool(raw_key)
    return settings


@router.get("/agent-settings")
async def get_agent_settings():
    """获取 Agent 全局设置（smithery_api_key 打码返回）"""
    return _masked_settings_payload()


@router.put("/agent-settings")
async def update_agent_settings(req: dict = Body(...)):
    """更新 Agent 全局设置。

    smithery_api_key 语义：空字符串=清除（同时移除环境变量）；
    非空=保存并写入环境变量；与当前存储值打码结果完全一致的打码值忽略不写回。
    """
    from services.agent.agent_settings import get_setting, mask_key, update
    body = dict(req or {})
    updates = {}
    if "smithery_api_key" in body:
        key = str(body.pop("smithery_api_key") or "")
        if key != "" and key == mask_key(get_setting("smithery_api_key")):
            # 前端把打码值原样传回（与当前存储值的打码结果精确一致），忽略该字段；
            # 精确比对使真实含 * 的 Key 仍可正常保存
            pass
        elif key == "":
            updates["smithery_api_key"] = ""
            os.environ.pop("SMITHERY_API_KEY", None)
        else:
            updates["smithery_api_key"] = key
            os.environ["SMITHERY_API_KEY"] = key
    updates.update(body)
    if updates:
        update(updates)
    return _masked_settings_payload()


@router.post("/chat")
async def chat_api(req: ChatRequest):
    """SSE 流式对话 — 逐字返回 AI 回复"""
    # 保存用户消息
    user_msg = add_message(req.session_id, "user", req.message)
    # 如果是第一条消息，自动生成标题
    existing = get_messages(req.session_id)
    if len(existing) == 1:
        auto_title(req.session_id, req.message)

    # 获取 LLM Provider（流式调用在 _stream_chat 中处理）
    # 无 LLM 时 _stream_chat 会返回提示

    # 收集历史消息
    history = get_messages(req.session_id)
    # 去掉刚插入的用户消息（最后一条），后面单独加
    history_for_llm = (history[:-1] if history else [])[-20:]  # 只保留最近20条消息，避免token超限

    messages = []
    messages.append({"role": "system", "content": build_system_prompt()})
    for msg in history_for_llm:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": req.message})

    # ── 工具目录获取（失败安全：任何异常都降级为无工具模式）──
    tools: list = []
    try:
        from services.agent.agent_settings import get_setting
        from services.agent.mcp_runtime import get_mcp_runtime
        if get_setting("tools_enabled", True):
            tools = await get_mcp_runtime().get_openai_tools()
    except Exception as tools_e:
        logger.warning(f"[Tools] 获取工具目录失败，降级为无工具模式: {tools_e}")
        tools = []

    async def stream():
        full_reply = ""
        emitted = False  # 是否已向客户端输出过 content（降级重发只在此之前有意义）
        use_tools = bool(tools)

        def _delta_of(chunk):
            if isinstance(chunk, dict):
                return chunk.get("content", "")
            if isinstance(chunk, str):
                return chunk
            return ""

        async def _drain(source):
            """消费生成器：工具状态事件透传（不累加进 full_reply），内容块转 SSE"""
            nonlocal full_reply, emitted
            async for chunk in source:
                if isinstance(chunk, dict) and chunk.get("tool"):
                    # 工具状态事件：旧前端解析器自动忽略
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    continue
                delta = _delta_of(chunk)
                if delta:
                    full_reply += delta
                    emitted = True
                    yield f"data: {json.dumps({'content': delta}, ensure_ascii=False)}\n\n"

        async def _finish_success():
            """保存完整回复 + done 事件 + 记忆自动积累挂钩（与原逻辑一致）"""
            ai_msg = add_message(req.session_id, "assistant", full_reply)
            yield f"data: {json.dumps({'done': True, 'message_id': ai_msg['id']}, ensure_ascii=False)}\n\n"
            # 记忆自动积累挂钩：正常结束时后台提取记忆，不阻塞响应，异常静默吞掉
            try:
                if full_reply and not full_reply.startswith("⚠️"):
                    from services.agent.memory_accumulator import accumulate
                    _acc_task = asyncio.create_task(accumulate(req.session_id, full_reply))
                    _accumulate_tasks.add(_acc_task)
                    _acc_task.add_done_callback(_accumulate_tasks.discard)
            except Exception as hook_e:
                logger.warning(f"[MemoryAccumulate] 挂钩调度失败: {hook_e}")

        try:
            source = _stream_chat_with_tools(messages, tools) if use_tools else _stream_chat(messages)
            async for sse in _drain(source):
                yield sse
            async for sse in _finish_success():
                yield sse
        except Exception as e:
            if use_tools and not emitted:
                # 工具路径失败且尚未输出任何内容：降级用原流式路径重发
                logger.warning(f"AI chat 工具路径失败({e})，降级到原流式路径重发")
                try:
                    async for sse in _drain(_stream_chat(messages)):
                        yield sse
                    async for sse in _finish_success():
                        yield sse
                    return
                except Exception as e2:
                    e = e2
            logger.error(f"AI chat stream error: {e}", exc_info=True)
            error = f"⚠️ 调用失败: {e}"
            ai_msg = add_message(req.session_id, "assistant", error)
            yield f"data: {json.dumps({'content': error, 'done': True, 'message_id': ai_msg['id'], 'error': True}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


async def _stream_chat_with_tools(messages: list[dict], tools: list[dict], temperature: float = 0.3):
    """带工具循环的 LLM 调用（非流式工具轮，外层循环 ≤ _MAX_TOOL_ROUNDS 轮）。

    yield {"tool": ...} 为工具状态事件（前端旧解析器自动忽略）；
    yield {"content": ...} 为最终答案文本块（每 _FINAL_CHUNK_SIZE 字符一块）。
    400 且响应体命中不支持短语（_TOOLS_UNSUPPORTED_PHRASES）→ 去掉 tools 重试一次；
    已知不支持的模型直接抛 ToolsNotSupported，其余异常抛出由 chat_api 外层降级。
    """
    provider = _llm_manager.get_active_raw()
    if not provider or not provider.get("api_key"):
        yield {"content": "⚠️ 尚未配置 LLM Provider，请在「设置 → AI Agent」页面配置。"}
        return

    model = provider.get("selected_model") or (provider.get("models")[0] if provider.get("models") and len(provider.get("models", [])) > 0 else "")
    if not model:
        yield {"content": "⚠️ 未选择模型。"}
        return

    # 防御性降级：ollama 直接走原流式路径（调用方通常已分流）
    if provider.get("type") == "ollama":
        async for chunk in _stream_chat(messages, temperature):
            yield chunk
        return

    if _model_tools_unsupported(model):
        raise ToolsNotSupported(model)

    base_url = provider.get("base_url", "https://api.openai.com/v1").rstrip("/")
    api_url = f"{base_url}/chat/completions"
    headers = _build_llm_headers(provider)
    client_kwargs = _build_llm_client_kwargs(provider)

    from services.agent.mcp_runtime import get_mcp_runtime
    runtime = get_mcp_runtime()

    work_messages = list(messages)
    last_round_results: list = []

    async with httpx.AsyncClient(**client_kwargs) as client:
        for _round in range(_MAX_TOOL_ROUNDS):
            use_tools_this_round = bool(tools) and not _model_tools_unsupported(model)
            payload = {
                "model": model,
                "messages": work_messages,
                "temperature": temperature,
                "stream": False,
            }
            if use_tools_this_round:
                payload["tools"] = tools

            resp = await client.post(api_url, json=payload, headers=headers)
            if resp.status_code == 400:
                body_lower = (getattr(resp, "text", "") or "").lower()
                if use_tools_this_round and any(
                        p in body_lower for p in _TOOLS_UNSUPPORTED_PHRASES):
                    # 该模型不支持 tools：带 TTL 记录后去掉 tools 重试一次
                    logger.warning(f"[Tools] 模型 {model} 不支持 tools 参数，去掉 tools 重试")
                    _tools_unsupported_models[model] = time.time() + _TOOLS_UNSUPPORTED_TTL
                    payload.pop("tools", None)
                    resp = await client.post(api_url, json=payload, headers=headers)
                if resp.status_code == 400:
                    raise RuntimeError(f"LLM 返回 400: {(getattr(resp, 'text', '') or '')[:200]}")
            if resp.status_code != 200:
                raise RuntimeError(f"LLM 返回 HTTP {resp.status_code}")

            data = resp.json()
            message = ((data.get("choices") or [{}])[0]).get("message") or {}
            tool_calls = message.get("tool_calls") or []
            # 入口处一次性清洗：后续执行、assistant 回喂与结果配对统一用清洗后列表
            tool_calls = [tc for tc in tool_calls if isinstance(tc, dict)]

            if not tool_calls:
                # 最终答案：已有文本按块输出（本期允许最终轮非流式分块）
                content = str(message.get("content") or "")
                for i in range(0, len(content), _FINAL_CHUNK_SIZE):
                    yield {"content": content[i:i + _FINAL_CHUNK_SIZE]}
                return

            # ── 工具轮：逐个执行 tool_calls ──
            results: list = []
            for tc in tool_calls:
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
                tool_name = str(fn.get("name") or "")
                args_raw = fn.get("arguments")
                yield {"tool": f"正在调用 {tool_name}..."}
                try:
                    if isinstance(args_raw, dict):
                        args = args_raw
                    else:
                        args = json.loads(args_raw or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("arguments 不是 JSON 对象")
                except Exception as je:
                    result = f"参数解析失败: {je}"
                else:
                    try:
                        result = await asyncio.wait_for(
                            runtime.execute(tool_name, args),
                            timeout=_TOOL_EXECUTE_TIMEOUT)
                    except TimeoutError:
                        result = "工具调用超时"
                    except Exception as ee:
                        result = f"工具调用失败: {ee}"
                results.append(str(result))
                yield {"tool": f"已完成 {tool_name}"}

            # 回喂消息：先 assistant（含 tool_calls），再逐个 tool 结果
            work_messages.append({
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            })
            for tc, result in zip(tool_calls, results):
                work_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id") or "",
                    "content": result,
                })
            last_round_results = results

        # 循环耗尽仍有 tool_calls：输出上限提示 + 最后一轮工具结果摘要后结束（不死循环）
        yield {"content": "（工具调用轮次已达上限，以下是已获取的信息）"}
        if last_round_results:
            summary = "\n".join(last_round_results[-10:])
            for i in range(0, len(summary), _FINAL_CHUNK_SIZE):
                yield {"content": summary[i:i + _FINAL_CHUNK_SIZE]}


async def _stream_chat(messages: list[dict], temperature: float = 0.3):
    """流式调用 LLM，yield content chunks"""
    provider = _llm_manager.get_active_raw()
    if not provider or not provider.get("api_key"):
        yield {"content": "⚠️ 尚未配置 LLM Provider，请在「设置 → AI Agent」页面配置。"}
        return

    model = provider.get("selected_model") or (provider.get("models")[0] if provider.get("models") and len(provider.get("models", [])) > 0 else "")
    if not model:
        yield {"content": "⚠️ 未选择模型。"}
        return

    base_url = provider.get("base_url", "https://api.openai.com/v1").rstrip("/")
    api_url = f"{base_url}/chat/completions"

    import os

    headers = {"Content-Type": "application/json"}
    if provider.get("type") != "ollama":
        headers["Authorization"] = f"Bearer {provider['api_key']}"

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }

    # 代理配置：仅使用环境变量，不自动检测
    proxy = os.environ.get("LLM_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""

    client_kwargs = {"timeout": 60, "http2": False}
    if proxy:
        client_kwargs["proxy"] = proxy

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            async with client.stream("POST", api_url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield {"content": delta}
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        yield {"content": f"⚠️ 调用失败: {e}"}


def _session_exists(session_id: str) -> bool:
    from data.database import get_conn
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
        return row is not None
    finally:
        conn.close()
