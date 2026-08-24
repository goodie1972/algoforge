"""
MCP 连接器导入/规范化单元测试
覆盖 services/agent/mcp_config.py：
  - normalize_mcp_json 各形态（mcpServers 包裹 / servers 别名 / 单对象 / 数组 / 非法输入）
  - 类型推断（command→stdio / url→sse / 显式 type 优先）
  - import_connectors 冲突三策略（skip / overwrite / rename）
  - env/headers 字段保留；旧记录无 env 字段读取时默认空 dict 不报错

隔离方式：CONFIG_FILE 为模块级常量且在方法调用时动态查找，
用 monkeypatch 替换到临时文件，绝不触碰真实 data/mcp_connectors.json。
"""

import json
import os
import sys

import pytest

# 确保项目根目录在 sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import services.agent.mcp_config as mcp_mod
from services.agent.mcp_config import McpConfigManager, normalize_mcp_json


@pytest.fixture
def mcp_env(tmp_path, monkeypatch):
    """把 CONFIG_FILE 切到临时文件，返回文件路径"""
    cfg_file = tmp_path / "mcp_connectors.json"
    monkeypatch.setattr(mcp_mod, "CONFIG_FILE", str(cfg_file))
    return cfg_file


# ════════════════════════════════════════════════════════════
# 1. normalize_mcp_json 各输入形态
# ════════════════════════════════════════════════════════════

class TestNormalizeShapes:

    def test_mcp_servers_wrapper(self):
        """{"mcpServers": {...}} 标准包裹体"""
        raw = {"mcpServers": {"fs": {"command": "npx", "args": ["-y", "fs-mcp"]}}}
        result = normalize_mcp_json(raw)
        assert result["errors"] == []
        assert len(result["ok"]) == 1
        conn = result["ok"][0]
        assert conn["name"] == "fs"
        assert conn["type"] == "stdio"
        assert conn["command"] == "npx"
        assert conn["args"] == ["-y", "fs-mcp"]

    def test_servers_alias(self):
        """{"servers": {...}} 别名包裹体"""
        raw = {"servers": {"remote": {"url": "https://mcp.example.com/sse"}}}
        result = normalize_mcp_json(raw)
        assert result["errors"] == []
        assert len(result["ok"]) == 1
        assert result["ok"][0]["name"] == "remote"
        assert result["ok"][0]["type"] == "sse"
        assert result["ok"][0]["url"] == "https://mcp.example.com/sse"

    def test_mcp_servers_snake_case_alias(self):
        """{"mcp_servers": {...}} 蛇形别名包裹体"""
        raw = {"mcp_servers": {"a": {"command": "python", "args": []}}}
        result = normalize_mcp_json(raw)
        assert len(result["ok"]) == 1
        assert result["ok"][0]["name"] == "a"

    def test_single_object_with_command(self):
        """单服务器对象（含 command）→ stdio，名称取 name 字段"""
        raw = {"name": "mytool", "command": "python", "args": ["-m", "tool"]}
        result = normalize_mcp_json(raw)
        assert result["errors"] == []
        assert len(result["ok"]) == 1
        conn = result["ok"][0]
        assert conn["name"] == "mytool"
        assert conn["type"] == "stdio"

    def test_single_object_with_url_inferred_sse(self):
        """单服务器对象（仅 url）→ 推断为 sse"""
        raw = {"url": "https://api.example.com/mcp"}
        result = normalize_mcp_json(raw)
        assert result["errors"] == []
        conn = result["ok"][0]
        assert conn["type"] == "sse"
        assert conn["name"] == "server"  # 缺省名称

    def test_array_form(self):
        """服务器对象数组"""
        raw = [
            {"name": "local", "command": "node", "args": ["server.js"]},
            {"name": "cloud", "url": "https://x.com/sse"},
        ]
        result = normalize_mcp_json(raw)
        assert result["errors"] == []
        assert [c["name"] for c in result["ok"]] == ["local", "cloud"]
        assert [c["type"] for c in result["ok"]] == ["stdio", "sse"]

    def test_json_string_input(self):
        """纯文本 JSON 字符串先 json.loads"""
        raw = '{"mcpServers": {"a": {"command": "uvx", "args": ["pkg"]}}}'
        result = normalize_mcp_json(raw)
        assert len(result["ok"]) == 1
        assert result["ok"][0]["name"] == "a"

    def test_invalid_json_string_returns_error(self):
        """非法 JSON 文本返回错误条目"""
        result = normalize_mcp_json("{这不是 JSON")
        assert result["ok"] == []
        assert len(result["errors"]) == 1
        assert "JSON" in result["errors"][0]["reason"]

    def test_empty_string_returns_error(self):
        """空字符串返回错误条目"""
        result = normalize_mcp_json("   ")
        assert result["ok"] == []
        assert result["errors"][0]["reason"] == "内容为空"

    def test_unsupported_structure_returns_error(self):
        """数字等非对象结构返回错误条目"""
        result = normalize_mcp_json(123)
        assert result["ok"] == []
        assert "不支持" in result["errors"][0]["reason"]

    def test_array_with_non_object_item(self):
        """数组内含非对象元素 → 该元素进 errors，合法元素进 ok"""
        result = normalize_mcp_json([{"command": "python"}, "bad-item"])
        assert len(result["ok"]) == 1
        assert len(result["errors"]) == 1
        assert result["errors"][0]["name"] == "#2"

    def test_entry_missing_command_and_url(self):
        """command 与 url 均缺失 → 错误条目"""
        result = normalize_mcp_json({"mcpServers": {"bad": {"args": []}}})
        assert result["ok"] == []
        assert "无法推断类型" in result["errors"][0]["reason"]


# ════════════════════════════════════════════════════════════
# 2. 类型推断
# ════════════════════════════════════════════════════════════

class TestTypeInference:

    def test_command_infers_stdio(self):
        result = normalize_mcp_json({"a": {"command": "python"}})
        assert result["ok"][0]["type"] == "stdio"

    def test_url_infers_sse(self):
        result = normalize_mcp_json({"a": {"url": "https://x.com"}})
        assert result["ok"][0]["type"] == "sse"

    def test_explicit_type_wins(self):
        """显式 type 优先于推断"""
        result = normalize_mcp_json({"a": {"type": "sse", "url": "https://x.com", "command": "ignored"}})
        assert result["ok"][0]["type"] == "sse"

    def test_type_aliases(self):
        """http / streamable-http / remote → sse；local → stdio"""
        for alias, expected in [("http", "sse"), ("streamable-http", "sse"),
                                ("streamable_http", "sse"), ("remote", "sse"),
                                ("local", "stdio")]:
            cfg = {"command": "python"} if expected == "stdio" else {"url": "https://x.com"}
            cfg["type"] = alias
            result = normalize_mcp_json({"a": cfg})
            assert result["ok"][0]["type"] == expected, f"别名 {alias} 应推断为 {expected}"

    def test_unknown_type_returns_error(self):
        result = normalize_mcp_json({"a": {"type": "websocket", "url": "ws://x"}})
        assert result["ok"] == []
        assert "未知类型" in result["errors"][0]["reason"]


# ════════════════════════════════════════════════════════════
# 3. env / headers 字段处理
# ════════════════════════════════════════════════════════════

class TestEnvHeaders:

    def test_env_headers_preserved(self):
        raw = {"mcpServers": {"a": {"command": "python",
                                    "env": {"API_KEY": "k1", "PORT": 8080},
                                    "headers": {"Authorization": "Bearer t"}}}}
        conn = normalize_mcp_json(raw)["ok"][0]
        assert conn["env"] == {"API_KEY": "k1", "PORT": "8080"}  # 值统一转字符串
        assert conn["headers"] == {"Authorization": "Bearer t"}

    def test_env_vars_alias(self):
        """smithery 的 envVars 写法兼容"""
        conn = normalize_mcp_json({"a": {"command": "python", "envVars": {"K": "v"}}})["ok"][0]
        assert conn["env"] == {"K": "v"}

    def test_env_non_object_returns_error(self):
        result = normalize_mcp_json({"a": {"command": "python", "env": ["K=v"]}})
        assert result["ok"] == []
        assert "env" in result["errors"][0]["reason"]

    def test_add_connector_persists_env_headers(self, mcp_env):
        """add_connector 后 env/headers 持久化并可读回"""
        mgr = McpConfigManager()
        created = mgr.add_connector({
            "name": "svc", "type": "sse", "url": "https://x.com/sse",
            "env": {"TOKEN": "abc"}, "headers": {"X-Api": "1"},
        })
        assert created["env"] == {"TOKEN": "abc"}
        # 重新实例化从磁盘读回
        mgr2 = McpConfigManager()
        got = mgr2.get_connector(created["id"])
        assert got["env"] == {"TOKEN": "abc"}
        assert got["headers"] == {"X-Api": "1"}

    def test_legacy_record_without_env_defaults(self, mcp_env):
        """旧记录无 env/headers 字段，读取时默认空 dict 不报错"""
        legacy = [{
            "id": "legacy01", "name": "old", "type": "stdio",
            "command": "python", "args": [], "url": "",
            "description": "", "enabled": True, "created_at": "2024-01-01T00:00:00",
        }]  # 无 env / headers / source 字段
        mcp_env.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

        mgr = McpConfigManager()
        conns = mgr.list_connectors()
        assert len(conns) == 1
        assert conns[0]["env"] == {}
        assert conns[0]["headers"] == {}
        assert conns[0]["source"] is None

        got = mgr.get_connector("legacy01")
        assert got["env"] == {}
        assert got["headers"] == {}


# ════════════════════════════════════════════════════════════
# 4. import_connectors 冲突三策略
# ════════════════════════════════════════════════════════════

class TestImportConflictPolicies:

    def _seed(self, mgr, name="github"):
        mgr.add_connector({"name": name, "type": "stdio", "command": "old-cmd"})

    def _import_items(self, name="github", command="new-cmd"):
        return [{"name": name, "type": "stdio", "command": command,
                 "args": [], "url": "", "env": {}, "headers": {}, "description": ""}]

    def test_skip_policy(self, mcp_env):
        """skip：重名跳过，原连接器不变"""
        mgr = McpConfigManager()
        self._seed(mgr)
        result = mgr.import_connectors(self._import_items(), conflict_policy="skip")
        assert result["imported"] == 0
        assert result["skipped"] == 1
        assert result["results"][0]["action"] == "skipped"
        assert len(mgr.list_connectors()) == 1
        assert mgr.list_connectors()[0]["command"] == "old-cmd"

    def test_overwrite_policy(self, mcp_env):
        """overwrite：覆盖已有同名连接器（沿用原 id，字段更新）"""
        mgr = McpConfigManager()
        self._seed(mgr)
        old_id = mgr.list_connectors()[0]["id"]
        result = mgr.import_connectors(self._import_items(), conflict_policy="overwrite")
        assert result["overwritten"] == 1
        assert result["results"][0]["action"] == "overwritten"
        assert len(mgr.list_connectors()) == 1
        conn = mgr.list_connectors()[0]
        assert conn["id"] == old_id
        assert conn["command"] == "new-cmd"

    def test_rename_policy(self, mcp_env):
        """rename：自动改名 github_2 后导入"""
        mgr = McpConfigManager()
        self._seed(mgr)
        result = mgr.import_connectors(self._import_items(), conflict_policy="rename")
        assert result["imported"] == 1
        assert result["results"][0]["action"] == "renamed"
        assert result["results"][0]["final_name"] == "github_2"
        names = {c["name"] for c in mgr.list_connectors()}
        assert names == {"github", "github_2"}

    def test_rename_policy_increments(self, mcp_env):
        """rename 连续冲突递增 _2/_3"""
        mgr = McpConfigManager()
        self._seed(mgr)
        mgr.import_connectors(self._import_items(), conflict_policy="rename")  # → github_2
        result = mgr.import_connectors(self._import_items(), conflict_policy="rename")
        assert result["results"][0]["final_name"] == "github_3"

    def test_no_conflict_imports_normally(self, mcp_env):
        """无冲突时正常导入"""
        mgr = McpConfigManager()
        result = mgr.import_connectors(self._import_items(name="newone"))
        assert result["imported"] == 1
        assert result["skipped"] == 0
        assert result["results"][0]["action"] == "imported"

    def test_case_insensitive_conflict(self, mcp_env):
        """重名检测大小写不敏感"""
        mgr = McpConfigManager()
        self._seed(mgr, name="GitHub")
        result = mgr.import_connectors(self._import_items(name="github"), conflict_policy="skip")
        assert result["skipped"] == 1

    def test_invalid_policy_raises(self, mcp_env):
        """非法策略抛 ValueError"""
        mgr = McpConfigManager()
        with pytest.raises(ValueError):
            mgr.import_connectors([], conflict_policy="merge")

    def test_import_item_without_name_counted_error(self, mcp_env):
        """缺少名称的条目计入 skipped 并给出错误原因"""
        mgr = McpConfigManager()
        result = mgr.import_connectors([{"type": "stdio", "command": "python"}])
        assert result["imported"] == 0
        assert result["skipped"] == 1
        assert result["results"][0]["action"] == "error"

    def test_normalize_then_import_end_to_end(self, mcp_env):
        """端到端：normalize_mcp_json 输出直接喂给 import_connectors"""
        raw = {"mcpServers": {
            "fs": {"command": "npx", "args": ["-y", "fs"]},
            "remote": {"url": "https://x.com/sse"},
        }}
        normalized = normalize_mcp_json(raw)
        mgr = McpConfigManager()
        result = mgr.import_connectors(normalized["ok"])
        assert result["imported"] == 2
        # 持久化到临时配置文件
        saved = json.loads(mcp_env.read_text(encoding="utf-8"))
        assert {c["name"] for c in saved} == {"fs", "remote"}
