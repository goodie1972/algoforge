"""
MCP 运行时聚合层
================
把「内置工具注册表」与「MCP 连接器」聚合为统一的 OpenAI function calling
工具目录，并提供统一的执行入口：

  - get_openai_tools()：内置（原名）+ MCP（mcp__{cid[:6]}__{tool} 前缀）
    * 仅连接 enabled 连接器；asyncio.gather 并发，单连接器 8s 超时
    * 失败连接器记日志并进 60s 冷却，冷却期内不重试
    * data/mcp_connectors.json mtime 变化 → close_all 后重新发现
    * 结果缓存，invalidate() 供将来连接器 CRUD 路由调用
  - execute(name, arguments)：mcp__ 前缀 → MCP 客户端（断开重连一次）；
    原名 → 内置注册表（同步 handler 经 asyncio.to_thread 调用）。
    所有异常捕获转为可读字符串返回，不抛。

mcp_client 延迟导入，避免 import 环。
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Optional

from services.agent import mcp_config
from services.agent.mcp_config import get_mcp_manager
from services.agent.tool_registry import get_registry

logger = logging.getLogger(__name__)

# 失败连接器冷却时长（秒）
COOLDOWN_SECONDS = 60.0
# 单个连接器发现（connect + list_tools）总超时（秒）
DISCOVER_TIMEOUT = 8.0
# MCP 工具调用超时（秒）
EXECUTE_TIMEOUT = 30.0

# 工具名合法字符清洗（OpenAI 工具名约束）
_NAME_INVALID_RE = re.compile(r"[^a-zA-Z0-9_-]")
_TOOL_NAME_MAX = 64


def _now() -> float:
    """单调时钟（测试可 monkeypatch 本模块属性）"""
    return time.monotonic()


def _config_mtime() -> Optional[float]:
    """读取连接器配置文件 mtime（配置变化检测用），不存在返回 None"""
    try:
        return os.path.getmtime(mcp_config.CONFIG_FILE)
    except OSError:
        return None


def build_tool_name(connector_id: str, tool_name: str) -> str:
    """生成带前缀的 OpenAI 工具名：
    mcp__{connector_id[:6]}__{tool_name}，非法字符替换 _，截断 64 字符"""
    cid = str(connector_id or "")[:6]
    sanitized = _NAME_INVALID_RE.sub("_", str(tool_name or ""))
    return f"mcp__{cid}__{sanitized}"[:_TOOL_NAME_MAX]


def _client_class():
    """延迟导入 McpClient，避免 import 环（测试可 patch 模块属性）"""
    from services.agent.mcp_client import McpClient
    return McpClient


class _CooldownSkip(Exception):
    """内部信号：连接器处于失败冷却期，本轮跳过"""


async def _safe_close(client) -> None:
    if client is None:
        return
    try:
        await client.close()
    except Exception:
        pass


class McpRuntime:
    """MCP 运行时聚合层（工具目录 + 统一执行）"""

    def __init__(self):
        self._clients: dict = {}      # connector_id -> McpClient
        self._tool_map: dict = {}     # openai 工具名 -> (connector_id, 原始工具名)
        self._cooldown: dict = {}     # connector_id -> 失败时间戳
        self._cache: Optional[list] = None
        self._config_mtime: Optional[float] = None
        self._lock = asyncio.Lock()

    # ── 工具目录 ──────────────────────────────────────

    async def get_openai_tools(self) -> list:
        """聚合内置 + MCP 工具为 OpenAI function calling 目录（带缓存）"""
        async with self._lock:
            # 配置变化检测：配置文件 mtime 变化 → 关闭全部客户端后重新发现
            mtime = _config_mtime()
            if self._config_mtime is not None and mtime != self._config_mtime:
                logger.info("[McpRuntime] 连接器配置变化，重新发现工具")
                await self._close_all_locked()
            self._config_mtime = mtime

            if self._cache is not None:
                return list(self._cache)

            tools: list = list(get_registry().to_openai_tools())

            connectors = [c for c in get_mcp_manager().list_connectors()
                          if c.get("enabled")]

            async def discover(conn: dict):
                cid = conn.get("id")
                last_fail = self._cooldown.get(cid)
                if last_fail is not None and _now() - last_fail < COOLDOWN_SECONDS:
                    raise _CooldownSkip(cid)
                client = _client_class()(conn)
                try:
                    await client.connect()
                    tool_list = await client.list_tools()
                except BaseException:
                    # 含 CancelledError：wait_for 超时取消时也必须关闭新建
                    # 客户端（子进程/协程），然后 raise 保持取消语义
                    await _safe_close(client)
                    raise
                return cid, client, tool_list

            results = await asyncio.gather(
                *[asyncio.wait_for(discover(c), DISCOVER_TIMEOUT)
                  for c in connectors],
                return_exceptions=True,
            )

            for conn, res in zip(connectors, results):
                cid = conn.get("id")
                if isinstance(res, BaseException):
                    if isinstance(res, _CooldownSkip):
                        continue  # 冷却期内静默跳过
                    self._cooldown[cid] = _now()
                    logger.warning(
                        f"[McpRuntime] 连接器 {conn.get('name')!r}({cid}) "
                        f"发现失败，进入 {int(COOLDOWN_SECONDS)}s 冷却: {res}")
                    continue
                _, client, tool_list = res
                self._cooldown.pop(cid, None)
                old = self._clients.get(cid)
                if old is not None and old is not client:
                    await _safe_close(old)
                self._clients[cid] = client
                for tool in tool_list:
                    if not isinstance(tool, dict):
                        continue
                    orig_name = str(tool.get("name") or "")
                    if not orig_name:
                        continue
                    openai_name = build_tool_name(cid, orig_name)
                    self._tool_map[openai_name] = (cid, orig_name)
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": openai_name,
                            "description": str(tool.get("description") or ""),
                            "parameters": tool.get("inputSchema")
                            or {"type": "object", "properties": {}},
                        },
                    })

            self._cache = tools
            return list(tools)

    async def invalidate(self) -> None:
        """清除工具目录缓存（供将来连接器 CRUD 路由调用）"""
        self._cache = None

    # ── 统一执行 ──────────────────────────────────────

    async def execute(self, name: str, arguments: Optional[dict] = None) -> str:
        """统一工具执行入口；所有异常捕获转为可读字符串返回，不抛"""
        arguments = arguments or {}
        try:
            if name.startswith("mcp__"):
                entry = self._tool_map.get(name)
                if entry is None:
                    return "错误: 工具不存在"
                cid, tool_name = entry
                try:
                    client = await self._ensure_client(cid)
                    return await asyncio.wait_for(
                        client.call_tool(tool_name, arguments), EXECUTE_TIMEOUT)
                except Exception as first_err:
                    # 连接可能已断开：尝试重连一次后重试
                    logger.warning(
                        f"[McpRuntime] 调用 {name} 失败（{first_err}），尝试重连一次")
                    client = await self._reconnect(cid)
                    return await asyncio.wait_for(
                        client.call_tool(tool_name, arguments), EXECUTE_TIMEOUT)

            # 内置工具：同步 handler，必须经 asyncio.to_thread
            if get_registry().get(name) is None:
                return "错误: 工具不存在"
            result = await asyncio.to_thread(get_registry().call, name, **arguments)
            if isinstance(result, str):
                return result
            try:
                return json.dumps(result, ensure_ascii=False, default=str)
            except Exception:
                return str(result)
        except Exception as e:
            logger.error(f"[McpRuntime] 执行工具 {name} 失败: {e}")
            return f"错误: {e}"

    async def _ensure_client(self, cid: str):
        client = self._clients.get(cid)
        if client is not None and getattr(client, "connected", False):
            return client
        return await self._reconnect(cid)

    async def _reconnect(self, cid: str):
        """（重）连接指定连接器并登记客户端"""
        connector = get_mcp_manager().get_connector(cid)
        if connector is None:
            raise RuntimeError(f"连接器不存在: {cid}")
        old = self._clients.pop(cid, None)
        await _safe_close(old)
        client = _client_class()(connector)
        try:
            await asyncio.wait_for(client.connect(), DISCOVER_TIMEOUT)
        except BaseException:
            # 含 CancelledError：连接失败/被取消都必须关闭新建客户端，
            # 防止子进程/协程泄漏，然后 raise 保持取消语义
            await _safe_close(client)
            raise
        self._clients[cid] = client
        return client

    # ── 生命周期 ──────────────────────────────────────

    async def close_all(self) -> None:
        """关闭所有 MCP 客户端/子进程并清空映射与缓存"""
        async with self._lock:
            await self._close_all_locked()

    async def _close_all_locked(self) -> None:
        for client in list(self._clients.values()):
            await _safe_close(client)
        self._clients.clear()
        self._tool_map.clear()
        self._cache = None


# ── 模块级单例 ────────────────────────────────────────

_runtime: Optional[McpRuntime] = None


def get_mcp_runtime() -> McpRuntime:
    """获取全局唯一的 McpRuntime 实例"""
    global _runtime
    if _runtime is None:
        _runtime = McpRuntime()
    return _runtime
