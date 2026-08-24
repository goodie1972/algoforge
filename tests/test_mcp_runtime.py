"""
MCP 运行时聚合层单元测试（零真实子进程 / 零网络）
覆盖 services/agent/mcp_runtime.py：
  ① 禁用连接器不连接
  ② 某连接器连接失败被跳过，内置工具与其它连接器正常
  ③ 失败后 60s 冷却（时间 mock）
  ④ 前缀命名：非法字符清洗、64 字符截断
  ⑤ execute 路由：mcp__ 前缀 → MCP 客户端；原名 → 内置工具
  ⑥ 内置工具经 asyncio.to_thread（结果正确即可）
  ⑦ execute 异常返回字符串不抛
  ⑧ close_all 清理
  另附：配置文件 mtime 变化触发重连、invalidate 清缓存

隔离方式：
  - monkeypatch services.agent.mcp_config.CONFIG_FILE 到临时文件
  - monkeypatch mcp_runtime.get_mcp_manager 返回假管理器
  - monkeypatch mcp_client.McpClient 为脚本化 Mock 类（延迟导入每次取属性）
  - monkeypatch mcp_runtime._now 为假时钟

异步用例统一用 asyncio.run() 包裹（不依赖 pytest-asyncio）。
"""

import asyncio
import json
import os
import sys

import pytest

# 确保项目根目录在 sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import services.agent.mcp_client as client_mod
import services.agent.mcp_config as cfg_mod
import services.agent.mcp_runtime as rt_mod
from services.agent.mcp_runtime import McpRuntime
from services.agent.tool_registry import get_registry


# ════════════════════════════════════════════════════════════
# 测试替身
# ════════════════════════════════════════════════════════════

def make_mock_client_class(fail_ids=(), tools_by_id=None, call_result="mcp-ok",
                           call_error=None):
    """构造脚本化 Mock McpClient 类；类属性 instances 记录全部实例"""
    _fail = set(fail_ids)
    _tools = dict(tools_by_id or {})
    _result = call_result
    _error = call_error

    class MockMcpClient:
        instances: list = []
        # 类属性：测试中途可改写（如解除失败注入）
        fail_ids = _fail
        tools_by_id = _tools
        call_result = _result
        call_error = _error

        def __init__(self, connector, transport=None):
            self.connector = connector
            self.connected = False
            self.closed = False
            self.calls: list = []
            MockMcpClient.instances.append(self)

        async def connect(self):
            if self.connector.get("id") in type(self).fail_ids:
                raise RuntimeError(f"connect boom: {self.connector.get('id')}")
            self.connected = True

        async def list_tools(self):
            return list(type(self).tools_by_id.get(self.connector.get("id"), []))

        async def call_tool(self, name, arguments=None, timeout=30):
            self.calls.append((name, dict(arguments or {})))
            if type(self).call_error:
                raise RuntimeError(type(self).call_error)
            return type(self).call_result

        async def close(self):
            self.connected = False
            self.closed = True

    return MockMcpClient


class FakeManager:
    """假 McpConfigManager：list_connectors / get_connector"""

    def __init__(self, connectors):
        self._connectors = connectors

    def list_connectors(self):
        return [dict(c) for c in self._connectors]

    def get_connector(self, connector_id):
        for c in self._connectors:
            if c.get("id") == connector_id:
                return dict(c)
        return None


class FakeClock:
    """可推进的假时钟（替换 mcp_runtime._now）"""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def _conn(cid, name="srv", enabled=True):
    return {"id": cid, "name": name, "type": "stdio", "command": "python",
            "args": [], "url": "", "env": {}, "headers": {}, "enabled": enabled}


def _tool(name, with_schema=True, description="desc"):
    t = {"name": name, "description": description}
    if with_schema:
        t["inputSchema"] = {"type": "object",
                            "properties": {"q": {"type": "string"}}}
    return t


@pytest.fixture
def runtime_env(tmp_path, monkeypatch):
    """隔离环境：临时配置文件 + 假管理器挂钩 + 假时钟"""
    cfg_file = tmp_path / "mcp_connectors.json"
    cfg_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", str(cfg_file))

    holder = {"connectors": [], "cfg_file": cfg_file}

    monkeypatch.setattr(rt_mod, "get_mcp_manager",
                        lambda: FakeManager(holder["connectors"]))
    clock = FakeClock()
    monkeypatch.setattr(rt_mod, "_now", clock)

    holder["clock"] = clock
    return holder


def _patch_client(monkeypatch, mock_cls):
    """替换 McpClient（mcp_runtime 延迟导入，每次读取模块属性）"""
    monkeypatch.setattr(client_mod, "McpClient", mock_cls)


# ════════════════════════════════════════════════════════════
# 1. 工具发现
# ════════════════════════════════════════════════════════════

class TestDiscovery:

    def test_disabled_connector_not_connected(self, runtime_env, monkeypatch):
        """① 禁用连接器不连接"""
        async def main():
            mock_cls = make_mock_client_class()
            _patch_client(monkeypatch, mock_cls)
            runtime_env["connectors"] = [_conn("aaa111xxxx"),
                                         _conn("bbb222yyyy", enabled=False)]
            r = McpRuntime()
            try:
                await r.get_openai_tools()
                assert len(mock_cls.instances) == 1
                assert mock_cls.instances[0].connector["id"] == "aaa111xxxx"
            finally:
                await r.close_all()
        asyncio.run(main())

    def test_failed_connector_skipped_others_and_builtin_ok(self, runtime_env, monkeypatch):
        """② 某连接器连接失败被跳过，内置工具与其它连接器正常"""
        async def main():
            mock_cls = make_mock_client_class(
                fail_ids={"badconn1"},
                tools_by_id={"goodcon2": [_tool("hello")]})
            _patch_client(monkeypatch, mock_cls)
            runtime_env["connectors"] = [_conn("badconn1"), _conn("goodcon2")]

            # 注册一个临时内置工具，确保内置目录仍在
            registry = get_registry()
            registry.register("_t18_builtin", "临时工具",
                              handler=lambda: "ok",
                              parameters={"type": "object", "properties": {}})
            try:
                r = McpRuntime()
                try:
                    tools = await r.get_openai_tools()
                finally:
                    await r.close_all()
                names = [t["function"]["name"] for t in tools]
                assert "_t18_builtin" in names          # 内置仍在
                assert "mcp__goodco__hello" in names    # 好连接器正常
                assert not any(n.startswith("mcp__badco") for n in names)
            finally:
                registry.unregister("_t18_builtin")
        asyncio.run(main())

    def test_failure_cooldown_60s(self, runtime_env, monkeypatch):
        """③ 失败后 60s 冷却：冷却期内不重试，过期后重试"""
        async def main():
            mock_cls = make_mock_client_class(fail_ids={"failid1"})
            _patch_client(monkeypatch, mock_cls)
            runtime_env["connectors"] = [_conn("failid1")]
            clock = runtime_env["clock"]
            r = McpRuntime()
            try:
                await r.get_openai_tools()           # 第 1 次：连接失败
                assert len(mock_cls.instances) == 1

                await r.invalidate()
                await r.get_openai_tools()           # 冷却期内：不重试
                assert len(mock_cls.instances) == 1

                clock.advance(30)                    # 30s 后仍在冷却
                await r.invalidate()
                await r.get_openai_tools()
                assert len(mock_cls.instances) == 1

                clock.advance(31)                    # 累计 61s > 60：重试（解除失败注入）
                mock_cls.fail_ids = set()
                await r.invalidate()
                await r.get_openai_tools()
                assert len(mock_cls.instances) == 2
            finally:
                await r.close_all()
        asyncio.run(main())

    def test_prefix_naming_sanitize_and_truncate(self, runtime_env, monkeypatch):
        """④ 前缀命名：非法字符清洗、64 字符截断；inputSchema 缺失给默认"""
        long_name = "x" * 100
        async def main():
            mock_cls = make_mock_client_class(tools_by_id={
                "abcdef123456": [
                    _tool("weird.tool/name"),
                    _tool(long_name),
                    _tool("noschema", with_schema=False),
                ]})
            _patch_client(monkeypatch, mock_cls)
            runtime_env["connectors"] = [_conn("abcdef123456")]
            r = McpRuntime()
            try:
                tools = await r.get_openai_tools()
                mcp_tools = [t for t in tools
                             if t["function"]["name"].startswith("mcp__")]
                names = [t["function"]["name"] for t in mcp_tools]
                # 非法字符（. /）清洗为下划线；前缀取 connector id 前 6 位
                assert "mcp__abcdef__weird_tool_name" in names
                # 截断 64 字符
                assert all(len(n) <= 64 for n in names)
                # inputSchema 缺失 → 默认空 object schema
                by_name = {t["function"]["name"]: t for t in mcp_tools}
                noschema = by_name["mcp__abcdef__noschema"]
                assert noschema["function"]["parameters"] == {"type": "object", "properties": {}}
            finally:
                await r.close_all()
        asyncio.run(main())

    def test_config_mtime_change_triggers_reconnect(self, runtime_env, monkeypatch):
        """配置变化检测：配置文件 mtime 变化 → close_all 后重新发现"""
        async def main():
            mock_cls = make_mock_client_class(
                tools_by_id={"aaa111xxxx": [_tool("t1")]})
            _patch_client(monkeypatch, mock_cls)
            runtime_env["connectors"] = [_conn("aaa111xxxx")]
            cfg_file = runtime_env["cfg_file"]
            r = McpRuntime()
            try:
                await r.get_openai_tools()
                assert len(mock_cls.instances) == 1
                first = mock_cls.instances[0]

                # 模拟配置被外部修改：内容 + mtime 均变化
                cfg_file.write_text('[{"id": "aaa111xxxx"}]', encoding="utf-8")
                st = os.stat(cfg_file)
                os.utime(cfg_file, (st.st_atime, st.st_mtime + 10))

                tools = await r.get_openai_tools()
                assert len(mock_cls.instances) == 2      # 重新连接
                assert first.closed is True              # 旧客户端已关闭
                assert any(t["function"]["name"] == "mcp__aaa111__t1" for t in tools)
            finally:
                await r.close_all()
        asyncio.run(main())

    def test_cache_hit_no_reconnect(self, runtime_env, monkeypatch):
        """结果缓存：配置未变时二次调用不重连"""
        async def main():
            mock_cls = make_mock_client_class()
            _patch_client(monkeypatch, mock_cls)
            runtime_env["connectors"] = [_conn("aaa111xxxx")]
            r = McpRuntime()
            try:
                await r.get_openai_tools()
                await r.get_openai_tools()
                assert len(mock_cls.instances) == 1
            finally:
                await r.close_all()
        asyncio.run(main())


# ════════════════════════════════════════════════════════════
# 2. execute 路由
# ════════════════════════════════════════════════════════════

class TestExecute:

    def test_execute_routes_mcp_prefix_and_builtin(self, runtime_env, monkeypatch):
        """⑤ mcp__ 前缀路由到 MCP 客户端（还原原始工具名与参数），
        原名路由到内置工具"""
        async def main():
            mock_cls = make_mock_client_class(
                tools_by_id={"aaa111xxxx": [_tool("orig_tool")]},
                call_result="mcp-ok")
            _patch_client(monkeypatch, mock_cls)
            runtime_env["connectors"] = [_conn("aaa111xxxx")]

            registry = get_registry()
            registry.register(
                "_t18_echo", "临时回显",
                handler=lambda text="": f"echo:{text}",
                parameters={"type": "object",
                            "properties": {"text": {"type": "string"}}})
            try:
                r = McpRuntime()
                try:
                    await r.get_openai_tools()
                    # MCP 路由
                    res = await r.execute("mcp__aaa111__orig_tool", {"q": "v"})
                    assert res == "mcp-ok"
                    inst = mock_cls.instances[0]
                    assert inst.calls == [("orig_tool", {"q": "v"})]
                    # 内置路由
                    res2 = await r.execute("_t18_echo", {"text": "hi"})
                    assert res2 == "echo:hi"
                    # 未知工具
                    assert await r.execute("no_such_tool", {}) == "错误: 工具不存在"
                    assert await r.execute("mcp__zzz__none", {}) == "错误: 工具不存在"
                finally:
                    await r.close_all()
            finally:
                registry.unregister("_t18_echo")
        asyncio.run(main())

    def test_builtin_via_to_thread_result_correct(self, runtime_env, monkeypatch):
        """⑥ 内置工具经 asyncio.to_thread 调用（结果正确即可）"""
        async def main():
            mock_cls = make_mock_client_class()
            _patch_client(monkeypatch, mock_cls)
            runtime_env["connectors"] = []
            registry = get_registry()
            registry.register("_t18_add", "加法",
                              handler=lambda a=0, b=0: f"sum={int(a) + int(b)}",
                              parameters={"type": "object", "properties": {}})
            try:
                r = McpRuntime()
                try:
                    res = await r.execute("_t18_add", {"a": 2, "b": 3})
                    assert res == "sum=5"
                finally:
                    await r.close_all()
            finally:
                registry.unregister("_t18_add")
        asyncio.run(main())

    def test_execute_exception_returns_string(self, runtime_env, monkeypatch):
        """⑦ execute 异常返回可读字符串，不抛"""
        async def main():
            mock_cls = make_mock_client_class(
                tools_by_id={"aaa111xxxx": [_tool("boom_tool")]},
                call_error="call exploded")
            _patch_client(monkeypatch, mock_cls)
            runtime_env["connectors"] = [_conn("aaa111xxxx")]
            r = McpRuntime()
            try:
                await r.get_openai_tools()
                res = await r.execute("mcp__aaa111__boom_tool", {})
                assert isinstance(res, str)
                assert "错误" in res or "call exploded" in res
            finally:
                await r.close_all()
        asyncio.run(main())

    def test_execute_reconnects_when_disconnected(self, runtime_env, monkeypatch):
        """连接断开（客户端被置为未连接）时 execute 尝试重连一次"""
        async def main():
            mock_cls = make_mock_client_class(
                tools_by_id={"aaa111xxxx": [_tool("t1")]},
                call_result="ok2")
            _patch_client(monkeypatch, mock_cls)
            runtime_env["connectors"] = [_conn("aaa111xxxx")]
            r = McpRuntime()
            try:
                await r.get_openai_tools()
                mock_cls.instances[0].connected = False  # 模拟连接断开
                res = await r.execute("mcp__aaa111__t1", {})
                assert res == "ok2"
                assert len(mock_cls.instances) == 2      # 重连产生了新实例
                assert mock_cls.instances[1].connected is True
            finally:
                await r.close_all()
        asyncio.run(main())


# ════════════════════════════════════════════════════════════
# 3. 生命周期
# ════════════════════════════════════════════════════════════

class TestLifecycle:

    def test_close_all_cleanup(self, runtime_env, monkeypatch):
        """⑧ close_all 关闭所有客户端并清空映射"""
        async def main():
            mock_cls = make_mock_client_class(
                tools_by_id={"aaa111xxxx": [_tool("t1")]})
            _patch_client(monkeypatch, mock_cls)
            runtime_env["connectors"] = [_conn("aaa111xxxx")]
            r = McpRuntime()
            await r.get_openai_tools()
            inst = mock_cls.instances[0]
            await r.close_all()
            assert inst.closed is True
            # 清空后 MCP 工具不可路由
            assert await r.execute("mcp__aaa111__t1", {}) == "错误: 工具不存在"
        asyncio.run(main())

    def test_invalidate_clears_cache(self, runtime_env, monkeypatch):
        """invalidate 清缓存：下次调用重新发现（配置未变也应重连）"""
        async def main():
            mock_cls = make_mock_client_class()
            _patch_client(monkeypatch, mock_cls)
            runtime_env["connectors"] = [_conn("aaa111xxxx")]
            r = McpRuntime()
            try:
                await r.get_openai_tools()
                await r.invalidate()
                await r.get_openai_tools()
                assert len(mock_cls.instances) == 2
            finally:
                await r.close_all()
        asyncio.run(main())
