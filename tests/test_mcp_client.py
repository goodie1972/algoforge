"""
MCP 协议客户端单元测试（零真实子进程 / 零网络）
覆盖 services/agent/mcp_client.py：
  - JsonRpcSession / McpClient 经 FakeTransport 注入测协议层
  - initialize 握手请求体与时序
  - tools/list 解析、tools/call 文本抽取与 isError 前缀
  - JSON-RPC error → JsonRpcError；超时 TimeoutError
  - 并发多路复用乱序响应按 id 分发
  - SSE 行解析纯函数 parse_sse_lines
  - stdio .cmd 垫片解析纯函数 resolve_stdio_argv（monkeypatch shutil.which）
  - 坏 JSON 行容错（行解析函数）

异步用例统一用 asyncio.run() 包裹（项目 requirements 未含 pytest-asyncio，不新增依赖）。
"""

import asyncio
import os
import sys

import pytest

# 确保项目根目录在 sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import services.agent.mcp_client as mc
from services.agent.mcp_client import (
    JsonRpcError,
    JsonRpcSession,
    McpClient,
    parse_json_line,
    parse_sse_lines,
    resolve_stdio_argv,
)


# ════════════════════════════════════════════════════════════
# FakeTransport：内存传输，注入协议层测试
# ════════════════════════════════════════════════════════════

class FakeTransport:
    """内存假传输：feed() 注入脚本化响应，sent 记录所有发送消息"""

    def __init__(self):
        self.sent: list[dict] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self.started = False
        self.closed = False

    async def start(self):
        self.started = True

    async def send(self, msg: dict):
        self.sent.append(msg)

    async def recv(self):
        return await self._queue.get()

    async def close(self):
        self.closed = True
        # 唤醒可能阻塞在 recv 的读循环
        self._queue.put_nowait(None)

    def feed(self, msg: dict):
        self._queue.put_nowait(msg)


class AutoResponder:
    """监视 FakeTransport.sent，对带 id 的请求按 handler 自动回喂响应"""

    def __init__(self, transport: FakeTransport, handler):
        self.t = transport
        self.handler = handler
        self._seen: set[int] = set()

    async def run(self):
        while True:
            for i, msg in enumerate(self.t.sent):
                if i in self._seen:
                    continue
                self._seen.add(i)
                if msg.get("id") is None:
                    continue  # 通知不回复
                result = self.handler(msg)
                if result is not None:
                    self.t.feed({"jsonrpc": "2.0", "id": msg["id"], "result": result})
            await asyncio.sleep(0.001)


def _stdio_connector(**overrides):
    conn = {"id": "conn01abcdef", "name": "fake", "type": "stdio",
            "command": "python", "args": [], "url": "", "env": {}, "headers": {}}
    conn.update(overrides)
    return conn


def _handshake_handler(msg):
    if msg.get("method") == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {},
                "serverInfo": {"name": "fake-server", "version": "0.0"}}
    if msg.get("method") == "tools/list":
        return {"tools": [
            {"name": "echo", "description": "回显",
             "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
            {"name": "add", "description": "加法"},
        ]}
    return None


async def _connect_fake_client(handler=_handshake_handler):
    """建立注入 FakeTransport 的 McpClient，返回 (client, transport, responder_task)"""
    t = FakeTransport()
    task = asyncio.create_task(AutoResponder(t, handler).run())
    client = McpClient(_stdio_connector(), transport=t)
    await asyncio.wait_for(client.connect(), 2)
    return client, t, task


def _stop(task):
    task.cancel()


# ════════════════════════════════════════════════════════════
# 1. initialize 握手
# ════════════════════════════════════════════════════════════

class TestInitializeHandshake:

    def test_initialize_request_body_and_sequence(self):
        """① initialize 请求体（protocolVersion/2024-11-05/clientInfo）与
        握手序列（先 initialize 后 notifications/initialized 通知）"""
        async def main():
            client, t, task = await _connect_fake_client()
            try:
                # 第一条：initialize 请求
                first = t.sent[0]
                assert first["method"] == "initialize"
                assert first.get("id") is not None
                params = first["params"]
                assert params["protocolVersion"] == "2024-11-05"
                assert params["capabilities"] == {}
                assert params["clientInfo"] == {"name": "AlgoForge", "version": "1.0"}
                # 第二条：initialized 通知（无 id）
                second = t.sent[1]
                assert second["method"] == "notifications/initialized"
                assert "id" not in second
                assert client.connected is True
                assert t.started is True
            finally:
                _stop(task)
                await client.close()
        asyncio.run(main())

    def test_close_marks_disconnected(self):
        async def main():
            client, t, task = await _connect_fake_client()
            _stop(task)
            await client.close()
            assert client.connected is False
            assert t.closed is True
        asyncio.run(main())


# ════════════════════════════════════════════════════════════
# 2. tools/list 与 tools/call
# ════════════════════════════════════════════════════════════

class TestToolCalls:

    def test_list_tools_parses_result(self):
        """② tools/list 返回原始 result.tools"""
        async def main():
            client, t, task = await _connect_fake_client()
            try:
                tools = await client.list_tools()
                assert [x["name"] for x in tools] == ["echo", "add"]
                req = next(m for m in t.sent if m.get("method") == "tools/list")
                assert req.get("id") is not None
            finally:
                _stop(task)
                await client.close()
        asyncio.run(main())

    def test_call_tool_concatenates_text_segments(self):
        """③ tools/call：多段 text content 拼接，非 text 段忽略"""
        def handler(msg):
            if msg.get("method") == "initialize":
                return {"protocolVersion": "2024-11-05"}
            if msg.get("method") == "tools/call":
                return {"content": [
                    {"type": "text", "text": "Hello, "},
                    {"type": "image", "data": "xxx"},
                    {"type": "text", "text": "world!"},
                ]}
            return None

        async def main():
            client, t, task = await _connect_fake_client(handler)
            try:
                result = await client.call_tool("echo", {"text": "hi"})
                assert result == "Hello, world!"
                req = next(m for m in t.sent if m.get("method") == "tools/call")
                assert req["params"] == {"name": "echo", "arguments": {"text": "hi"}}
            finally:
                _stop(task)
                await client.close()
        asyncio.run(main())

    def test_call_tool_is_error_prefix(self):
        """③ isError 为真时加前缀「工具执行错误: 」"""
        def handler(msg):
            if msg.get("method") == "initialize":
                return {"protocolVersion": "2024-11-05"}
            if msg.get("method") == "tools/call":
                return {"isError": True,
                        "content": [{"type": "text", "text": "boom"}]}
            return None

        async def main():
            client, t, task = await _connect_fake_client(handler)
            try:
                result = await client.call_tool("bad", {})
                assert result == "工具执行错误: boom"
            finally:
                _stop(task)
                await client.close()
        asyncio.run(main())

    def test_call_tool_no_content_hint(self):
        """③ 无 content 返回非空提示字符串"""
        def handler(msg):
            if msg.get("method") == "initialize":
                return {"protocolVersion": "2024-11-05"}
            if msg.get("method") == "tools/call":
                return {}
            return None

        async def main():
            client, t, task = await _connect_fake_client(handler)
            try:
                result = await client.call_tool("void", {})
                assert isinstance(result, str) and result
            finally:
                _stop(task)
                await client.close()
        asyncio.run(main())


# ════════════════════════════════════════════════════════════
# 3. JsonRpcSession：error / 超时 / 多路复用
# ════════════════════════════════════════════════════════════

class TestJsonRpcSession:

    async def _make_session(self):
        t = FakeTransport()
        await t.start()
        s = JsonRpcSession(t)
        await s.start()
        return s, t

    def test_error_response_raises_jsonrpc_error(self):
        """④ error 响应 → JsonRpcError，含可读信息与 code"""
        async def main():
            s, t = await self._make_session()
            try:
                task = asyncio.create_task(s.request("nope", {}, timeout=2))
                await asyncio.sleep(0.01)
                req_id = t.sent[0]["id"]
                t.feed({"jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32601, "message": "Method not found"}})
                with pytest.raises(JsonRpcError) as ei:
                    await task
                assert "Method not found" in str(ei.value)
                assert ei.value.code == -32601
            finally:
                await s.close()
        asyncio.run(main())

    def test_request_timeout_raises(self):
        """⑤ 不喂消息 → wait_for 超时抛 TimeoutError"""
        async def main():
            s, t = await self._make_session()
            try:
                with pytest.raises(TimeoutError):
                    await s.request("slow", {}, timeout=0.05)
                # 超时后 pending 表已清理，仍可继续发请求
                assert len(s._pending) == 0
            finally:
                await s.close()
        asyncio.run(main())

    def test_concurrent_multiplexing_out_of_order(self):
        """⑦ 并发 3 个 pending 请求，乱序响应按 id 正确分发"""
        async def main():
            s, t = await self._make_session()
            try:
                ta = asyncio.create_task(s.request("m_a", {"i": 1}, timeout=2))
                tb = asyncio.create_task(s.request("m_b", {"i": 2}, timeout=2))
                tc = asyncio.create_task(s.request("m_c", {"i": 3}, timeout=2))
                await asyncio.sleep(0.02)
                ids = {m["method"]: m["id"] for m in t.sent}
                assert len(ids) == 3 and len(set(ids.values())) == 3
                # 乱序回包：b → c → a
                t.feed({"jsonrpc": "2.0", "id": ids["m_b"], "result": {"v": "B"}})
                t.feed({"jsonrpc": "2.0", "id": ids["m_c"], "result": {"v": "C"}})
                t.feed({"jsonrpc": "2.0", "id": ids["m_a"], "result": {"v": "A"}})
                ra, rb, rc = await asyncio.gather(ta, tb, tc)
                assert (ra["v"], rb["v"], rc["v"]) == ("A", "B", "C")
            finally:
                await s.close()
        asyncio.run(main())

    def test_notification_without_id_ignored(self):
        """无 id 的通知消息被忽略，不影响 pending 请求"""
        async def main():
            s, t = await self._make_session()
            try:
                task = asyncio.create_task(s.request("m1", {}, timeout=2))
                await asyncio.sleep(0.01)
                t.feed({"jsonrpc": "2.0", "method": "notifications/ping"})
                await asyncio.sleep(0.01)
                assert not task.done()
                req_id = t.sent[0]["id"]
                t.feed({"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}})
                assert (await task)["ok"] is True
            finally:
                await s.close()
        asyncio.run(main())


# ════════════════════════════════════════════════════════════
# 4. 行解析纯函数
# ════════════════════════════════════════════════════════════

class TestLineParsing:

    def test_parse_json_line_good_and_bad(self):
        """⑥ 坏 JSON 行容错：坏行返回 None，正常行可解析"""
        assert parse_json_line("这不是 JSON {") is None
        assert parse_json_line("") is None
        assert parse_json_line('{"a": 1}') == {"a": 1}
        assert parse_json_line('  {"b": 2}\r\n') == {"b": 2}
        # 非对象/数组的合法 JSON 也不作为消息（返回 None）
        assert parse_json_line("123") is None

    def test_parse_sse_endpoint_event(self):
        """⑧ event: endpoint 事件提取 POST 地址"""
        events = parse_sse_lines(["event: endpoint", "data: /msg?sid=1", ""])
        assert len(events) == 1
        assert events[0]["event"] == "endpoint"
        assert events[0]["data"] == "/msg?sid=1"

    def test_parse_sse_plain_data_message(self):
        """⑧ 普通 data 消息（缺省 event 为 message）"""
        payload = '{"jsonrpc": "2.0", "id": 1, "result": {"ok": true}}'
        events = parse_sse_lines([f"data: {payload}", ""])
        assert len(events) == 1
        assert events[0]["event"] == "message"
        assert events[0]["data"] == payload

    def test_parse_sse_multiple_events_and_comments(self):
        """⑧ 多事件 + 注释行忽略 + 无结尾空行的尾事件"""
        lines = [
            ": keep-alive",
            "event: endpoint",
            "data: /a",
            "",
            "data: hello",
        ]
        events = parse_sse_lines(lines)
        assert [e["event"] for e in events] == ["endpoint", "message"]
        assert events[0]["data"] == "/a"
        assert events[1]["data"] == "hello"


# ════════════════════════════════════════════════════════════
# 5. stdio 命令解析纯函数
# ════════════════════════════════════════════════════════════

class TestResolveStdioArgv:

    def test_plain_resolved_command(self, monkeypatch):
        """which 解析到普通可执行文件 → [解析值, *args]"""
        monkeypatch.setattr(mc.shutil, "which", lambda c: "/usr/bin/python3")
        assert resolve_stdio_argv("python3", ["-m", "srv"]) == ["/usr/bin/python3", "-m", "srv"]

    def test_cmd_shim_wrapped_with_cmd(self, monkeypatch):
        """解析到 .cmd 垫片（npx/uvx）→ cmd /c 包裹仍以 argv 启动"""
        monkeypatch.setattr(mc.shutil, "which", lambda c: r"C:\node\npx.cmd")
        argv = resolve_stdio_argv("npx", ["-y", "fs-mcp"])
        assert argv == ["cmd", "/c", r"C:\node\npx.cmd", "-y", "fs-mcp"]

    def test_bat_shim_wrapped_with_cmd(self, monkeypatch):
        """.bat 垫片同样包裹"""
        monkeypatch.setattr(mc.shutil, "which", lambda c: r"C:\tools\uvx.BAT")
        argv = resolve_stdio_argv("uvx", ["pkg"])
        assert argv[:2] == ["cmd", "/c"]
        assert argv[2].lower().endswith(".bat")

    def test_not_found_but_has_path_separator(self, monkeypatch):
        """which 找不到但命令含路径分隔符 → 直接用原值"""
        monkeypatch.setattr(mc.shutil, "which", lambda c: None)
        assert resolve_stdio_argv("./local/server", []) == ["./local/server"]
        assert resolve_stdio_argv(r"C:\srv\run.exe", ["--port", "9"]) == [r"C:\srv\run.exe", "--port", "9"]

    def test_not_found_raises_readable(self, monkeypatch):
        """which 找不到且无路径分隔符 → 抛带可读信息的异常"""
        monkeypatch.setattr(mc.shutil, "which", lambda c: None)
        with pytest.raises(RuntimeError) as ei:
            resolve_stdio_argv("missing-tool-xyz", [])
        assert "missing-tool-xyz" in str(ei.value)

    def test_empty_command_raises(self, monkeypatch):
        monkeypatch.setattr(mc.shutil, "which", lambda c: None)
        with pytest.raises(RuntimeError):
            resolve_stdio_argv("  ", [])


# ════════════════════════════════════════════════════════════
# 6. SseTransport：endpoint 相对路径拼接（mock httpx 流）
# ════════════════════════════════════════════════════════════

class _FakeSseResponse:
    """脚本化 SSE 流响应：aiter_lines 逐行吐出脚本行"""

    def __init__(self, lines):
        self._lines = list(lines)

    def raise_for_status(self):
        pass

    def aiter_lines(self):
        async def gen():
            for ln in self._lines:
                yield ln
        return gen()


class _FakeStreamCtx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *exc):
        return False


class _FakeSseClient:
    """httpx.AsyncClient 替身（SSE 测试用，记录构造 kwargs）"""

    def __init__(self, lines, **kwargs):
        self.kwargs = kwargs
        self._lines = lines

    def stream(self, method, url, headers=None):
        return _FakeStreamCtx(_FakeSseResponse(self._lines))

    async def aclose(self):
        pass


class TestSseTransport:

    def test_relative_endpoint_joined_with_base_url(self, monkeypatch):
        """endpoint 事件为相对路径 /messages → POST 地址 = urljoin(base_url, endpoint)"""
        base = "http://fake.local/sse"
        lines = ["event: endpoint", "data: /messages", ""]
        monkeypatch.setattr(mc.httpx, "AsyncClient",
                            lambda **kw: _FakeSseClient(lines, **kw))
        transport = mc.SseTransport({"type": "sse", "url": base})

        async def main():
            await asyncio.wait_for(transport.start(), 2)
            try:
                import urllib.parse
                assert transport._post_url == urllib.parse.urljoin(base, "/messages")
                assert transport._post_url == "http://fake.local/messages"
            finally:
                await transport.close()

        asyncio.run(main())

    def test_sse_read_timeout_is_none(self, monkeypatch):
        """C1：SSE 客户端读侧无超时（长连接），连接/写/池保持 15s"""
        lines = ["event: endpoint", "data: /m", ""]
        created = {}

        def _factory(**kw):
            created.update(kw)
            return _FakeSseClient(lines, **kw)

        monkeypatch.setattr(mc.httpx, "AsyncClient", _factory)
        transport = mc.SseTransport({"type": "sse", "url": "http://fake.local/sse"})

        async def main():
            await asyncio.wait_for(transport.start(), 2)
            try:
                timeout = created["timeout"]
                assert timeout.read is None
                assert timeout.connect == 15.0
                assert timeout.write == 15.0
                assert timeout.pool == 15.0
            finally:
                await transport.close()

        asyncio.run(main())


# ════════════════════════════════════════════════════════════
# 7. _quote_for_cmd：cmd /c 元字符注入防护
# ════════════════════════════════════════════════════════════

class TestQuoteForCmd:

    def test_metachar_ampersand_quoted(self):
        """含 & 元字符 → 整体加双引号"""
        assert mc._quote_for_cmd("-y&calc") == '"-y&calc"'

    def test_metachar_semicolon_quoted(self):
        """含 ; 元字符 → 整体加双引号"""
        assert mc._quote_for_cmd("a;b") == '"a;b"'

    def test_whitespace_quoted(self):
        """含空白字符 → 整体加双引号"""
        assert mc._quote_for_cmd("dir with space") == '"dir with space"'

    def test_plain_arg_unchanged(self):
        """普通安全参数原样返回"""
        assert mc._quote_for_cmd("-y") == "-y"
        assert mc._quote_for_cmd("fs-mcp") == "fs-mcp"
        assert mc._quote_for_cmd(r"C:\node\npx.cmd") == r"C:\node\npx.cmd"

    def test_empty_arg_quoted(self):
        """空参数加引号（防 argv 空串被 cmd 吞掉）"""
        assert mc._quote_for_cmd("") == '""'

    def test_inner_quotes_escaped(self):
        """内部已有双引号转义为 \\"""
        assert mc._quote_for_cmd('a"b&c') == '"a\\"b&c"'


class TestResolveStdioArgvCmdQuoting:

    def test_cmd_shim_args_safely_quoted(self, monkeypatch):
        """cmd /c 参数含元字符/空白时被安全加引号，普通参数不变"""
        monkeypatch.setattr(mc.shutil, "which", lambda c: r"C:\node\npx.cmd")
        argv = resolve_stdio_argv("npx", ["-y&calc", "a;b", r"C:\dir with space\x"])
        assert argv == ["cmd", "/c", r"C:\node\npx.cmd",
                        '"-y&calc"', '"a;b"', '"C:\\dir with space\\x"']

    def test_cmd_shim_plain_args_unchanged(self, monkeypatch):
        """无元字符/空白的参数不加引号（既有行为保持）"""
        monkeypatch.setattr(mc.shutil, "which", lambda c: r"C:\node\npx.cmd")
        argv = resolve_stdio_argv("npx", ["-y", "fs-mcp"])
        assert argv == ["cmd", "/c", r"C:\node\npx.cmd", "-y", "fs-mcp"]
