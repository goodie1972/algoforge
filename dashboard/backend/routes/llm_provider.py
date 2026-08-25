"""LLM Provider 管理 API 路由"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from services.llm_provider import LLMProviderManager

router = APIRouter(prefix="/api/llm", tags=["llm"])
logger = logging.getLogger(__name__)
manager = LLMProviderManager()


class ProviderCreate(BaseModel):
    name: str
    type: str = "openai"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    models: list[str] = []
    selected_model: str = ""
    is_active: bool = False


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    models: Optional[list[str]] = None
    enabled_models: Optional[list[str]] = None
    selected_model: Optional[str] = None
    is_active: Optional[bool] = None


class ChatRequest(BaseModel):
    messages: list[dict]
    provider_id: Optional[str] = None
    temperature: float = 0.3


@router.get("/providers")
def list_providers():
    return {"success": True, "data": manager.list_providers()}


@router.get("/providers/{provider_id}")
def get_provider(provider_id: str):
    p = manager.get_provider(provider_id)
    if not p:
        raise HTTPException(404, "Provider 不存在")
    return {"success": True, "data": p}


@router.post("/providers")
def add_provider(data: ProviderCreate):
    p = manager.add_provider(data.dict())
    return {"success": True, "data": p}


@router.put("/providers/{provider_id}")
def update_provider(provider_id: str, data: ProviderUpdate):
    p = manager.update_provider(provider_id, data.dict(exclude_none=True))
    if not p:
        raise HTTPException(404, "Provider 不存在")
    return {"success": True, "data": p}


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: str):
    ok = manager.delete_provider(provider_id)
    if not ok:
        raise HTTPException(404, "Provider 不存在")
    return {"success": True}


@router.post("/providers/{provider_id}/activate")
def activate_provider(provider_id: str):
    p = manager.set_active(provider_id)
    if not p:
        raise HTTPException(404, "Provider 不存在")
    return {"success": True, "data": p}


@router.get("/active")
def get_active():
    p = manager.get_active()
    if not p:
        return {"success": True, "data": None}
    return {"success": True, "data": p}


@router.post("/chat")
def chat(req: ChatRequest):
    result = manager.chat(req.messages, req.provider_id, req.temperature)
    if result is None:
        raise HTTPException(400, "LLM 调用失败，请检查 Provider 配置")
    return {"success": True, "data": {"content": result}}


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: str):
    result = manager.test_connection(provider_id)
    return {"success": True, "data": result}


@router.get("/status")
def llm_status():
    """LLM 可用性状态（每次新建实例，保证读到最新配置）"""
    try:
        mgr = LLMProviderManager()
        provider = mgr.get_active_raw()
        available = bool(provider and provider.get("api_key"))
        model = provider.get("selected_model") if available else None
        return {"available": available, "model": model}
    except Exception as e:
        logger.warning(f"[LLM] /status 检查失败: {e}")
        return {"available": False, "model": None}
