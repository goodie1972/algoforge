"""
MCP 市场 API 路由 — /api/mcp/store

平台分级：
- smithery.ai（A/B 级·条件固化）：有 SMITHERY_API_KEY 时系统内搜索/安装，
  无 Key 时降级为直链 + 粘贴 mcpServers JSON
- modelscope.cn/mcp（B 级·模板固化）：魔搭托管 / 本地 uvx 两个预置模板
- mcp.so（C 级·直连跳转）：详情页复制 mcpServers JSON 回系统粘贴导入
"""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.agent import mcp_marketplace as mp
from services.agent.mcp_config import (CONFLICT_POLICIES, get_mcp_manager,
                                       normalize_mcp_json)

router = APIRouter(prefix="/api/mcp/store", tags=["mcp-store"])
logger = logging.getLogger(__name__)


class ParseJsonRequest(BaseModel):
    raw: str = ""


class ImportJsonRequest(BaseModel):
    raw: str = ""
    conflict_policy: str = "skip"   # skip / overwrite / rename
    platform: str = ""              # 来源平台（可选，用于 source 徽章）


@router.get("/platforms")
def list_platforms():
    """返回平台注册表（smithery level 按 SMITHERY_API_KEY 动态计算）"""
    return {"platforms": mp.get_platforms()}


@router.get("/search")
def search_servers(platform: str = "smithery", q: str = ""):
    """系统内搜索 — 仅 smithery（且需 SMITHERY_API_KEY）生效"""
    p = mp.PLATFORM_BY_ID.get(platform)
    if not p:
        raise HTTPException(400, f"未知平台：{platform}")
    if platform != "smithery":
        raise HTTPException(
            400,
            f"「{p['name']}」不支持系统内搜索。"
            f"请打开 {p['url']} 浏览，复制 mcpServers JSON 后回本系统粘贴导入。",
        )
    try:
        results = mp.smithery_search(q)
    except mp.MarketplaceError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "platform": platform, "results": results}


@router.get("/detail")
def server_detail(platform: str = "smithery", qualified_name: str = ""):
    """拉取服务器详情并转换为连接器配置（仅 smithery 一键安装用）"""
    if platform != "smithery":
        raise HTTPException(400, f"平台 {platform} 不支持详情拉取，请复制 mcpServers JSON 粘贴导入")
    try:
        connectors = mp.smithery_detail(qualified_name)
    except mp.MarketplaceError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "platform": platform, "connectors": connectors}


@router.get("/templates")
def list_templates():
    """返回魔搭预置模板（托管 SSE / 本地 uvx）"""
    return {"templates": mp.get_templates()}


@router.post("/parse-json")
def parse_json(req: ParseJsonRequest):
    """解析预览：规范化 mcpServers JSON，不实际导入"""
    result = normalize_mcp_json(req.raw)
    return result


@router.post("/import-json")
def import_json(req: ImportJsonRequest):
    """导入 mcpServers JSON：normalize → import_connectors，返回逐条结果"""
    if req.conflict_policy not in CONFLICT_POLICIES:
        raise HTTPException(400, f"conflict_policy 必须为 {list(CONFLICT_POLICIES)} 之一")

    parsed = normalize_mcp_json(req.raw)
    if not parsed["ok"]:
        reasons = "; ".join(
            f"{e['name'] or '(整体)'}: {e['reason']}" for e in parsed["errors"][:5]
        ) or "未解析出任何连接器"
        raise HTTPException(400, f"JSON 解析失败：{reasons}")

    # 附加来源信息（供前端展示来源徽章）
    platform = req.platform if req.platform in mp.PLATFORM_BY_ID else (req.platform or "paste")
    for conn in parsed["ok"]:
        conn["source"] = {
            "platform": platform,
            "ref": "import-json",
            "installed_at": datetime.now().isoformat(timespec="seconds"),
        }

    summary = get_mcp_manager().import_connectors(parsed["ok"], req.conflict_policy)
    logger.info(f"[McpStore] import-json platform={platform} policy={req.conflict_policy} "
                f"imported={summary['imported']} skipped={summary['skipped']} "
                f"overwritten={summary['overwritten']}")
    return {"ok": True, "parse_errors": parsed["errors"], **summary}
