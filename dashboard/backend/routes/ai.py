"""
/api/ai 路由 — AI 交易助理（会话管理 + SSE 流式对话）
"""
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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


@router.get("/persona")
async def get_persona():
    """获取当前人设和所有可用人设"""
    from services.agent.persona_manager import get_persona_manager
    mgr = get_persona_manager()
    return {
        "current": mgr.get_current(),
        "list": mgr.get_list(),
    }


@router.put("/persona")
async def set_persona(req: dict):
    """保存/切换人设"""
    from services.agent.persona_manager import get_persona_manager
    mgr = get_persona_manager()
    name = req.get("name", "")
    if req.get("save", False):
        mgr.save_persona(req)
        return {"success": True, "name": name}
    if name:
        ok = mgr.set_current(name)
        return {"success": ok}
    return {"success": False}


@router.get("/skills")
async def list_skills():
    """列出已加载的技能"""
    from services.agent.skill_loader import get_loader
    loader = get_loader()
    if not loader.list_skills():
        loader.scan()
    return {"skills": get_loader().list_skills()}


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
    history_for_llm = history[:-1] if history else []

    messages = []
    messages.append({"role": "system", "content": build_system_prompt()})
    for msg in history_for_llm:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": req.message})

    async def stream():
        full_reply = ""
        try:
            for chunk in _stream_chat(messages):
                if isinstance(chunk, dict):
                    delta = chunk.get("content", "")
                elif isinstance(chunk, str):
                    delta = chunk
                else:
                    delta = ""
                if delta:
                    full_reply += delta
                    yield f"data: {json.dumps({'content': delta}, ensure_ascii=False)}\n\n"
            # 流结束后保存完整回复
            ai_msg = add_message(req.session_id, "assistant", full_reply)
            yield f"data: {json.dumps({'done': True, 'message_id': ai_msg['id']}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"AI chat stream error: {e}", exc_info=True)
            error = f"⚠️ 调用失败: {e}"
            ai_msg = add_message(req.session_id, "assistant", error)
            yield f"data: {json.dumps({'content': error, 'done': True, 'message_id': ai_msg['id'], 'error': True}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


def _stream_chat(messages: list[dict], temperature: float = 0.3):
    """流式调用 LLM，yield content chunks"""
    from services.llm_provider import LLMProviderManager
    manager = LLMProviderManager()
    provider = manager.get_active_raw()
    if not provider or not provider.get("api_key"):
        yield {"content": "⚠️ 尚未配置 LLM Provider，请在「设置 → AI Agent」页面配置。"}
        return

    model = provider.get("selected_model") or (provider.get("models")[0] if provider.get("models") and len(provider.get("models", [])) > 0 else "")
    if not model:
        yield {"content": "⚠️ 未选择模型。"}
        return

    base_url = provider.get("base_url", "https://api.openai.com/v1").rstrip("/")
    api_url = f"{base_url}/chat/completions"

    import httpx
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

    # 代理配置：优先使用环境变量，其次检测 v2rayN 默认 SOCKS5 端口
    proxy = os.environ.get("LLM_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        for port in ["10808", "7890", "1080"]:
            try:
                import socket
                s = socket.create_connection(("127.0.0.1", int(port)), timeout=1)
                s.close()
                proxy = f"socks5://127.0.0.1:{port}"
                break
            except OSError:
                continue

    client_kwargs = {"timeout": 60}
    if proxy:
        client_kwargs["proxy"] = proxy

    with httpx.stream("POST", api_url, json=payload, headers=headers, **client_kwargs) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
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


def _session_exists(session_id: str) -> bool:
    from data.database import get_conn
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM chat_sessions WHERE id=?", (session_id,)).fetchone()
        return row is not None
    finally:
        conn.close()
