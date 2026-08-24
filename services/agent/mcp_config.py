"""
MCP 连接器配置管理
==================
管理 Agent 可调用的 MCP（Model Context Protocol）连接器，
支持 stdio（本地命令）与 sse（远程服务）两种接入方式。

用法:
  from services.agent.mcp_config import get_mcp_manager
  mgr = get_mcp_manager()
  connectors = mgr.list_connectors()
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# 配置文件路径：项目根目录 / data / mcp_connectors.json
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                           "data", "mcp_connectors.json")

# 合法的连接器类型
VALID_TYPES = ("stdio", "sse")

# 导入重名冲突策略
CONFLICT_POLICIES = ("skip", "overwrite", "rename")

# 可选字段的默认值工厂（旧记录读取时按此补齐，完全向后兼容）
_OPTIONAL_DEFAULTS = {
    "env": dict,
    "headers": dict,
    "description": lambda: "",
    "source": lambda: None,
}


def _with_defaults(connector: dict) -> dict:
    """为连接器记录补齐可选字段默认值（不修改原记录）"""
    c = dict(connector)
    for key, factory in _OPTIONAL_DEFAULTS.items():
        if key not in c:
            c[key] = factory()
    return c


class McpConfigManager:
    """MCP 连接器配置管理器（JSON 文件持久化）"""

    def __init__(self):
        self._connectors: list[dict] = []
        self._load()

    # ── 持久化 ──────────────────────────────────────

    def _load(self):
        """从 JSON 文件加载连接器列表，失败时容错为空列表"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._connectors = json.load(f)
            else:
                self._connectors = []
                self._save()
        except Exception as e:
            logger.warning(f"[McpConfig] load failed: {e}")
            self._connectors = []

    def _save(self):
        """保存到 JSON 文件"""
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._connectors, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[McpConfig] save failed: {e}")

    # ── 校验 ────────────────────────────────────────

    @staticmethod
    def _validate(data: dict):
        """校验连接器数据，不合法时抛出 ValueError"""
        conn_type = data.get("type")
        if conn_type not in VALID_TYPES:
            raise ValueError(f"连接器类型必须为 {VALID_TYPES} 之一，当前为: {conn_type!r}")
        if conn_type == "stdio" and not str(data.get("command", "")).strip():
            raise ValueError("stdio 类型连接器必须提供 command 字段")
        if conn_type == "sse" and not str(data.get("url", "")).strip():
            raise ValueError("sse 类型连接器必须提供 url 字段")
        # 可选字段校验：env / headers 必须为 dict，source 必须为 dict 或 None
        if "env" in data and not isinstance(data["env"], dict):
            raise ValueError("env 字段必须为对象（键值对），如 {\"API_KEY\": \"xxx\"}")
        if "headers" in data and not isinstance(data["headers"], dict):
            raise ValueError("headers 字段必须为对象（键值对）")
        if "source" in data and data["source"] is not None and not isinstance(data["source"], dict):
            raise ValueError("source 字段必须为对象，如 {\"platform\": ..., \"ref\": ...}")

    # ── CRUD ────────────────────────────────────────

    def list_connectors(self) -> list[dict]:
        """返回所有连接器列表（旧记录自动补齐可选字段默认值）"""
        return [_with_defaults(c) for c in self._connectors]

    def get_connector(self, connector_id: str) -> Optional[dict]:
        """获取单个连接器，不存在返回 None"""
        for c in self._connectors:
            if c.get("id") == connector_id:
                return _with_defaults(c)
        return None

    def add_connector(self, data: dict) -> dict:
        """新增连接器，自动生成 id 与 created_at"""
        self._validate(data)
        connector = {
            "id": uuid.uuid4().hex[:8],
            "name": data.get("name", "新连接器"),
            "type": data.get("type"),
            "command": data.get("command", ""),
            "args": data.get("args", []),
            "url": data.get("url", ""),
            "env": data.get("env") or {},
            "headers": data.get("headers") or {},
            "description": data.get("description", ""),
            "source": data.get("source"),
            "enabled": data.get("enabled", True),
            "created_at": datetime.now().isoformat(),
        }
        self._connectors.append(connector)
        self._save()
        return dict(connector)

    # add/update 可透传的字段
    _UPDATABLE_KEYS = ("name", "type", "command", "args", "url", "enabled",
                       "env", "headers", "description", "source")

    def update_connector(self, connector_id: str, data: dict) -> Optional[dict]:
        """更新指定连接器，不存在返回 None"""
        for c in self._connectors:
            if c.get("id") == connector_id:
                # 用待更新的字段合并原值后做校验（未提供的字段沿用原值）
                merged = dict(c)
                for key in self._UPDATABLE_KEYS:
                    if key in data:
                        merged[key] = data[key]
                self._validate(merged)
                for key in self._UPDATABLE_KEYS:
                    if key in data:
                        c[key] = data[key]
                self._save()
                return _with_defaults(c)
        return None

    def delete_connector(self, connector_id: str) -> bool:
        """删除指定连接器，返回是否删除成功"""
        before = len(self._connectors)
        self._connectors = [c for c in self._connectors if c.get("id") != connector_id]
        if len(self._connectors) < before:
            self._save()
            return True
        return False

    def toggle_connector(self, connector_id: str) -> Optional[dict]:
        """切换连接器启用/禁用状态，不存在返回 None"""
        for c in self._connectors:
            if c.get("id") == connector_id:
                c["enabled"] = not c.get("enabled", True)
                self._save()
                return _with_defaults(c)
        return None

    # ── 批量导入 ──────────────────────────────────────

    def import_connectors(self, connectors: list, conflict_policy: str = "skip") -> dict:
        """批量导入连接器（来自 normalize_mcp_json 的 ok 列表）。

        重名检测策略：
        - skip：重名跳过；overwrite：覆盖已有同名连接器；rename：自动改名后导入。
        返回 {imported, skipped, overwritten, results: [{name, action, ...}...]}。
        """
        if conflict_policy not in CONFLICT_POLICIES:
            raise ValueError(f"conflict_policy 必须为 {CONFLICT_POLICIES} 之一，当前为: {conflict_policy!r}")

        imported = skipped = overwritten = 0
        results: list[dict] = []
        taken = {str(c.get("name", "")).strip().lower() for c in self._connectors}

        for item in connectors:
            orig_name = str(item.get("name", "")).strip()
            if not orig_name:
                skipped += 1
                results.append({"name": "", "action": "error", "error": "连接器缺少名称"})
                continue
            key = orig_name.lower()
            renamed_to: Optional[str] = None
            data = dict(item)
            try:
                if key in taken:
                    if conflict_policy == "skip":
                        skipped += 1
                        results.append({"name": orig_name, "action": "skipped",
                                        "reason": "已存在同名连接器"})
                        continue
                    if conflict_policy == "overwrite":
                        existing = next((c for c in self._connectors
                                         if str(c.get("name", "")).strip().lower() == key), None)
                        update = {k: v for k, v in item.items() if k in self._UPDATABLE_KEYS and k != "name"}
                        self.update_connector(existing["id"], update)
                        overwritten += 1
                        results.append({"name": orig_name, "action": "overwritten"})
                        continue
                    # rename：追加 _2/_3… 直到不冲突
                    n = 2
                    new_name = f"{orig_name}_{n}"
                    while new_name.lower() in taken:
                        n += 1
                        new_name = f"{orig_name}_{n}"
                    data["name"] = new_name
                    renamed_to = new_name

                created = self.add_connector(data)
                taken.add(created["name"].strip().lower())
                imported += 1
                if renamed_to:
                    results.append({"name": orig_name, "action": "renamed",
                                    "final_name": renamed_to})
                else:
                    results.append({"name": created["name"], "action": "imported"})
            except ValueError as e:
                skipped += 1
                results.append({"name": orig_name, "action": "error", "error": str(e)})

        return {"imported": imported, "skipped": skipped, "overwritten": overwritten,
                "results": results}


# ── mcpServers JSON 规范化 ────────────────────────────

# 常见远程类型别名 → sse
_TYPE_ALIASES = {
    "stdio": "stdio", "sse": "sse",
    "http": "sse", "streamable-http": "sse", "streamable_http": "sse",
    "streamablehttp": "sse", "remote": "sse", "local": "stdio",
}


def _normalize_entry(name: str, cfg) -> tuple[Optional[dict], Optional[str]]:
    """规范化单个服务器配置，返回 (连接器dict, None) 或 (None, 错误原因)"""
    if not isinstance(cfg, dict):
        return None, "配置必须为对象"

    # 类型：显式 type 字段优先，否则按 command / url 推断
    raw_type = str(cfg.get("type", "") or "").strip().lower()
    conn_type: Optional[str] = None
    if raw_type:
        conn_type = _TYPE_ALIASES.get(raw_type)
        if conn_type is None:
            return None, f"未知类型: {raw_type!r}（支持 stdio / sse）"
    else:
        if cfg.get("command"):
            conn_type = "stdio"
        elif cfg.get("url"):
            conn_type = "sse"
        else:
            return None, "无法推断类型：command 与 url 均缺失"

    # env / headers 必须为对象（兼容 smithery 的 envVars 写法）
    env = cfg.get("env", cfg.get("envVars"))
    if env is None:
        env = {}
    if not isinstance(env, dict):
        return None, "env 必须为对象（键值对）"
    headers = cfg.get("headers") or {}
    if not isinstance(headers, dict):
        return None, "headers 必须为对象（键值对）"

    # args 兼容字符串写法
    args = cfg.get("args") or []
    if isinstance(args, str):
        args = args.split()
    if not isinstance(args, list):
        return None, "args 必须为数组"
    args = [str(a) for a in args]

    connector = {
        "name": name,
        "type": conn_type,
        "command": str(cfg.get("command", "") or ""),
        "args": args,
        "url": str(cfg.get("url", "") or ""),
        "env": {str(k): ("" if v is None else str(v)) for k, v in env.items()},
        "headers": {str(k): ("" if v is None else str(v)) for k, v in headers.items()},
        "description": str(cfg.get("description", "") or ""),
    }
    if conn_type == "stdio" and not connector["command"].strip():
        return None, "stdio 类型缺少 command"
    if conn_type == "sse" and not connector["url"].strip():
        return None, "sse 类型缺少 url"
    return connector, None


def normalize_mcp_json(raw) -> dict:
    """把各种形态的 mcpServers JSON 规范化为连接器列表。

    输入兼容：
    - {"mcpServers": {...}} 标准包裹体（含 {"servers": ...} / {"mcp_servers": ...} 别名）
    - 单服务器对象（含 command 或 url，如 {"command": "python", "args": [...]}）
    - 服务器对象数组
    - 纯文本（先尝试 json.loads）

    类型自动推断：有 command → stdio；有 url → sse；显式 type 字段优先。
    返回 {"ok": [连接器dict...], "errors": [{"name": ..., "reason": ...}...]}。
    """
    data = raw
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return {"ok": [], "errors": [{"name": "", "reason": "内容为空"}]}
        try:
            data = json.loads(text)
        except Exception as e:
            return {"ok": [], "errors": [{"name": "", "reason": f"无法解析为 JSON: {e}"}]}

    if not isinstance(data, (dict, list)):
        return {"ok": [], "errors": [{"name": "", "reason": f"不支持的 JSON 结构: {type(data).__name__}"}]}

    # 解开 {"mcpServers": {...}} / {"servers": ...} / {"mcp_servers": ...} 包裹
    if isinstance(data, dict):
        unwrapped = None
        for key in ("mcpServers", "mcp_servers", "servers"):
            if key in data and isinstance(data[key], (dict, list)):
                unwrapped = data[key]
                break
        if unwrapped is not None:
            data = unwrapped
        elif "command" in data or "url" in data or "type" in data:
            # 单服务器对象：取 name 字段作为名称，缺省 "server"
            single_name = str(data.get("name") or data.get("id") or "server")
            data = {single_name: data}
        # 其余 dict 按 {名字: 配置} 映射处理

    ok: list[dict] = []
    errors: list[dict] = []
    if isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, dict):
                entry_name = str(item.get("name") or item.get("id") or f"server_{i + 1}")
                conn, err = _normalize_entry(entry_name, item)
            else:
                conn, err = None, "数组元素必须为对象"
            if conn:
                ok.append(conn)
            else:
                errors.append({"name": f"#{i + 1}", "reason": err or "未知错误"})
    else:
        for name, cfg in data.items():
            conn, err = _normalize_entry(str(name), cfg)
            if conn:
                ok.append(conn)
            else:
                errors.append({"name": str(name), "reason": err or "未知错误"})

    return {"ok": ok, "errors": errors}


# ── 全局单例 ────────────────────────────────────────

_manager: Optional[McpConfigManager] = None


def get_mcp_manager() -> McpConfigManager:
    """获取全局唯一的 McpConfigManager 实例"""
    global _manager
    if _manager is None:
        _manager = McpConfigManager()
    return _manager
