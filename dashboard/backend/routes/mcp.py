"""MCP 连接器配置管理 API 路由"""
import logging

from fastapi import APIRouter

from services.agent.mcp_config import get_mcp_manager

router = APIRouter(tags=["mcp"])
logger = logging.getLogger(__name__)


@router.get("/api/mcp/connectors")
async def list_connectors():
    """列出所有 MCP 连接器"""
    mgr = get_mcp_manager()
    return {"connectors": mgr.list_connectors()}


@router.post("/api/mcp/connectors")
async def add_connector(data: dict):
    """新增 MCP 连接器"""
    mgr = get_mcp_manager()
    return mgr.add_connector(data)


@router.put("/api/mcp/connectors/{connector_id}")
async def update_connector(connector_id: str, data: dict):
    """更新 MCP 连接器"""
    mgr = get_mcp_manager()
    result = mgr.update_connector(connector_id, data)
    if result is None:
        return {"error": "connector not found"}
    return result


@router.delete("/api/mcp/connectors/{connector_id}")
async def delete_connector(connector_id: str):
    """删除 MCP 连接器"""
    mgr = get_mcp_manager()
    result = mgr.delete_connector(connector_id)
    return {"ok": result}


@router.post("/api/mcp/connectors/{connector_id}/toggle")
async def toggle_connector(connector_id: str):
    """切换 MCP 连接器启用状态"""
    mgr = get_mcp_manager()
    result = mgr.toggle_connector(connector_id)
    if result is None:
        return {"error": "connector not found"}
    return result
