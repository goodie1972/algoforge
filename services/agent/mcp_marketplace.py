"""
MCP 市场 — 平台注册表 + Smithery Registry API 适配 + 魔搭模板

原则：能固化就固化、不能固化就提供直连 URL 跳浏览器。
- smithery.ai（A/B 级·条件固化）：环境变量 SMITHERY_API_KEY 存在时
  走 Registry API 系统内搜索/安装（A 级）；否则降级为直链 + 粘贴 JSON（B 级）
- modelscope.cn/mcp（B 级·模板固化）：魔搭托管（粘贴专属 SSE URL）/ 本地 uvx 两个预置模板
- mcp.so（C 级·直连跳转）：详情页复制 mcpServers JSON 回系统粘贴导入
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 10.0

# Smithery Registry API
SMITHERY_REGISTRY = "https://registry.smithery.ai"
SMITHERY_WEB = "https://smithery.ai"
SMITHERY_KEY_ENV = "SMITHERY_API_KEY"


class MarketplaceError(Exception):
    """MCP 市场操作的明确错误（消息可直接展示给用户）"""


def _smithery_key() -> str:
    """Smithery API Key：环境变量优先；为空时回退读 agent_settings 持久化配置"""
    key = (os.environ.get(SMITHERY_KEY_ENV) or "").strip()
    if key:
        return key
    try:
        # 延迟导入避免循环依赖；任何异常回退空串不影响市场功能
        from services.agent.agent_settings import get_setting
        return str(get_setting("smithery_api_key") or "").strip()
    except Exception:
        return ""


def _proxy() -> str:
    """复用系统代理环境变量（与 skill_marketplace 保持一致）"""
    return (os.environ.get("LLM_PROXY")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or "")


def _client() -> httpx.Client:
    kwargs = {"timeout": HTTP_TIMEOUT, "follow_redirects": True}
    proxy = _proxy()
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs)


# ── 平台注册表（直链 URL 固化在此）────────────────────────
# smithery 的 level 随 SMITHERY_API_KEY 动态变化：有 Key → "api"（A 级），无 → "link"（B 级）
MCP_PLATFORMS = [
    {
        "id": "smithery",
        "name": "Smithery",
        "url": SMITHERY_WEB,
        "grade": "A/B",
        "level": "link",  # 动态，见 get_platforms()
        "description": "MCP 服务器注册表 — 配置 API Key 后系统内搜索安装；未配置时直链浏览并粘贴 mcpServers JSON",
    },
    {
        "id": "modelscope",
        "name": "魔搭 ModelScope",
        "url": "https://modelscope.cn/mcp",
        "grade": "B",
        "level": "template",
        "description": "魔搭社区 MCP 广场 — 托管服务粘贴专属 SSE URL，或本地 uvx modelscope-mcp-server",
    },
    {
        "id": "mcpso",
        "name": "mcp.so",
        "url": "https://mcp.so",
        "grade": "C",
        "level": "link",
        "description": "MCP 服务器目录站 — 详情页复制 mcpServers JSON，回本系统粘贴导入",
    },
]

PLATFORM_BY_ID = {p["id"]: p for p in MCP_PLATFORMS}


def get_platforms() -> list[dict]:
    """返回平台注册表（smithery level 按 SMITHERY_API_KEY 动态计算）"""
    result = []
    for p in MCP_PLATFORMS:
        item = dict(p)
        if item["id"] == "smithery":
            item["level"] = "api" if _smithery_key() else "link"
            item["has_api_key"] = bool(_smithery_key())
        result.append(item)
    return result


# ── Smithery Registry API（A 级条件固化）────────────────────

def smithery_search(query: str) -> list[dict]:
    """代理搜索 Smithery Registry（需 SMITHERY_API_KEY，Bearer 认证，10s 超时）。

    返回 [{name, description, qualifiedName}]；无 Key 或失败抛 MarketplaceError
    并给出明确降级指引。
    """
    key = _smithery_key()
    if not key:
        raise MarketplaceError(
            f"未配置 {SMITHERY_KEY_ENV}，无法系统内搜索。"
            f"请打开 {SMITHERY_WEB} 浏览服务器，在详情页复制 mcpServers JSON，"
            "回本系统「JSON 导入」粘贴导入。"
        )
    query = (query or "").strip()
    if not query:
        raise MarketplaceError("搜索关键词不能为空")

    try:
        with _client() as client:
            resp = client.get(
                f"{SMITHERY_REGISTRY}/servers",
                params={"q": query, "pageSize": 10},
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.TimeoutException:
        raise MarketplaceError(f"Smithery 搜索超时（10s），请稍后重试；或打开 {SMITHERY_WEB} 网页搜索后粘贴 JSON 导入")
    except Exception as e:  # noqa: BLE001
        raise MarketplaceError(f"Smithery 搜索请求失败：{type(e).__name__}: {e}")

    if resp.status_code == 401 or resp.status_code == 403:
        raise MarketplaceError(
            f"Smithery API Key 无效或无权限（HTTP {resp.status_code}）。"
            f"请检查 {SMITHERY_KEY_ENV}，或打开 {SMITHERY_WEB} 复制 mcpServers JSON 粘贴导入。"
        )
    if resp.status_code != 200:
        raise MarketplaceError(
            f"Smithery 搜索返回 HTTP {resp.status_code}（响应前 120 字符：{resp.text[:120]!r}）。"
            f"可打开 {SMITHERY_WEB} 网页搜索后，复制 mcpServers JSON 粘贴导入。"
        )
    try:
        data = resp.json()
    except Exception:
        raise MarketplaceError(f"Smithery 搜索响应不是有效 JSON（前 120 字符：{resp.text[:120]!r}）")
    return _normalize_search_results(data)


def _normalize_search_results(data) -> list[dict]:
    """尽力兼容 Registry 返回结构：列表或 {servers|results|items|data: [...]}"""
    items = data
    if isinstance(data, dict):
        for k in ("servers", "results", "items", "hits", "data"):
            v = data.get(k)
            if isinstance(v, list):
                items = v
                break
    if not isinstance(items, list):
        return []
    results = []
    for it in items[:10]:
        if not isinstance(it, dict):
            continue
        qn = str(it.get("qualifiedName") or it.get("id") or it.get("slug") or "")
        name = str(it.get("displayName") or it.get("name") or qn.split("/")[-1] or "")
        desc = str(it.get("description") or "")
        if qn or name:
            results.append({"name": name, "description": desc, "qualifiedName": qn})
    return results


def smithery_detail(qualified_name: str) -> list[dict]:
    """拉取 Smithery 服务器详情并把 connections[] 转成连接器配置（尽力而为）。

    返回连接器 dict 列表（可直接交给 normalize 后的导入流程）；失败抛 MarketplaceError。
    """
    key = _smithery_key()
    if not key:
        raise MarketplaceError(
            f"未配置 {SMITHERY_KEY_ENV}，无法拉取详情。请打开 {SMITHERY_WEB} 复制 mcpServers JSON 粘贴导入。"
        )
    qualified_name = (qualified_name or "").strip()
    if not qualified_name:
        raise MarketplaceError("qualifiedName 不能为空")

    try:
        with _client() as client:
            resp = client.get(
                f"{SMITHERY_REGISTRY}/servers/{qualified_name}",
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.TimeoutException:
        raise MarketplaceError("Smithery 详情请求超时（10s），请稍后重试")
    except Exception as e:  # noqa: BLE001
        raise MarketplaceError(f"Smithery 详情请求失败：{type(e).__name__}: {e}")

    if resp.status_code != 200:
        raise MarketplaceError(
            f"Smithery 详情返回 HTTP {resp.status_code}（响应前 120 字符：{resp.text[:120]!r}）。"
            f"请打开 {SMITHERY_WEB}/{qualified_name} 手动复制 mcpServers JSON 粘贴导入。"
        )
    try:
        data = resp.json()
    except Exception:
        raise MarketplaceError("Smithery 详情响应不是有效 JSON")

    display_name = str(data.get("displayName") or qualified_name.split("/")[-1] or "smithery-server")
    description = str(data.get("description") or "")
    connections = data.get("connections") or []
    if not isinstance(connections, list) or not connections:
        raise MarketplaceError(
            f"「{qualified_name}」详情中未找到 connections 配置，"
            f"请打开 {SMITHERY_WEB}/{qualified_name} 手动复制 mcpServers JSON 粘贴导入。"
        )

    connectors = []
    for conn in connections:
        if not isinstance(conn, dict):
            continue
        ctype = str(conn.get("type", "")).strip().lower()
        deployment = conn.get("deployment") or {}
        if not isinstance(deployment, dict):
            deployment = {}
        env = {}
        if isinstance(deployment.get("envVars"), dict):
            env = {str(k): str(v) for k, v in deployment["envVars"].items()}
        if ctype in ("stdio", "local"):
            cmd_list = deployment.get("commandArgs") or deployment.get("startCommand")
            if isinstance(cmd_list, str):
                cmd_list = cmd_list.split()
            if not isinstance(cmd_list, list) or not cmd_list:
                continue  # 尽力而为：无法解析的条目跳过
            connectors.append({
                "name": display_name if len(connectors) == 0 and len(connections) == 1
                        else f"{display_name}_{len(connectors) + 1}",
                "type": "stdio",
                "command": str(cmd_list[0]),
                "args": [str(a) for a in cmd_list[1:]],
                "url": "", "env": env, "headers": {},
                "description": description,
            })
        elif ctype in ("http", "sse", "remote", "websocket", "ws"):
            url = str(deployment.get("endpoint") or deployment.get("url") or conn.get("url") or "")
            if not url:
                continue
            connectors.append({
                "name": display_name if len(connectors) == 0 and len(connections) == 1
                        else f"{display_name}_{len(connectors) + 1}",
                "type": "sse",
                "command": "", "args": [], "url": url,
                "env": env, "headers": {},
                "description": description,
            })

    if not connectors:
        raise MarketplaceError(
            f"「{qualified_name}」的 connections 无法转换为连接器配置（可能是 Docker 部署模板）。"
            f"请打开 {SMITHERY_WEB}/{qualified_name} 使用其 CLI/JSON 配置，粘贴回本系统导入。"
        )
    return connectors


# ── 魔搭预置模板（B 级模板固化）────────────────────────────

MODELSCOPE_WEB = "https://modelscope.cn/mcp"
MODELSCOPE_SSE_HINT = "https://mcp.api-inference.modelscope.net/{server-id}/sse"

MODELSCOPE_TEMPLATES = [
    {
        "id": "ms_hosted",
        "title": "魔搭托管服务（SSE 远程）",
        "description": "魔搭为每个 MCP 服务器提供托管的专属 SSE URL（需登录魔搭账号获取），粘贴即可接入。",
        "type": "sse",
        "platform_url": MODELSCOPE_WEB,
        "note": f"专属 SSE URL 形如 {MODELSCOPE_SSE_HINT}，在服务器详情页登录后复制",
        "fields": [
            {"key": "name", "label": "连接器名称", "placeholder": "如：modelscope-mcp"},
            {"key": "url", "label": "专属 SSE URL", "placeholder": MODELSCOPE_SSE_HINT},
        ],
    },
    {
        "id": "ms_local",
        "title": "本地运行（uvx）",
        "description": "使用 uvx 本地启动 modelscope-mcp-server，可调用魔搭平台的工具能力，需配置 API Token。",
        "type": "stdio",
        "command": "uvx",
        "args": ["modelscope-mcp-server"],
        "platform_url": MODELSCOPE_WEB,
        "note": "MODELSCOPE_API_TOKEN 可在魔搭个人中心 → 访问令牌获取",
        "fields": [
            {"key": "name", "label": "连接器名称", "placeholder": "如：modelscope-local"},
            {"key": "env.MODELSCOPE_API_TOKEN", "label": "MODELSCOPE_API_TOKEN",
             "placeholder": "YOUR_MODELSCOPE_API_TOKEN", "secret": True},
        ],
    },
]


def get_templates() -> list[dict]:
    """返回魔搭两个预置模板结构（供前端渲染表单）"""
    return [dict(t) for t in MODELSCOPE_TEMPLATES]
