"""
任务 #19：聊天 tool_calls 循环改造 — 模拟测试（零真实网络）

覆盖：
  1. 完整工具循环（tool_calls → execute → 最终答案）
  2. 字节级回归基准（开关关 / 工具目录为空时与原 _stream_chat 输出逐条相等）
  3. 工具异常不崩（异常文本回喂后正常最终答复）
  4. 5 轮上限（不死循环）
  5. 非法 JSON arguments（不调用 execute，错误文本回喂）
  6. 400 降级（去掉 tools 重试 + 已知模型直接抛 ToolsNotSupported）
  7. 非法 tool_calls 整体容错（message 缺 tool_calls 且 content 为空 → 不崩）
  8. chat_api 分流（工具路径 / 异常降级原流式路径 / 目录获取失败降级）

全部用 FakeClient 脚本化 httpx.AsyncClient，asyncio.run() 包裹（不新增依赖）。
"""

import asyncio
import copy
import inspect
import json
import os
import sys
import time

import pytest

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dashboard.backend.routes import ai as ai_routes  # noqa: E402

PROVIDER = {
    "id": "test",
    "name": "Test",
    "type": "openai",
    "api_key": "sk-test",
    "base_url": "http://fake.local/v1",
    "models": ["gpt-test"],
    "selected_model": "gpt-test",
}

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_market_price",
        "description": "获取市场价格",
        "parameters": {"type": "object", "properties": {}},
    },
}]

USER_MESSAGES = [{"role": "user", "content": "金价多少？"}]


# ════════════════════════════════════════════════════════════
# Fake httpx 基础设施
# ════════════════════════════════════════════════════════════

class FakePostResponse:
    """非流式响应（工具轮用）"""

    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        if text:
            self.text = text
        elif json_data is not None:
            self.text = json.dumps(json_data, ensure_ascii=False)
        else:
            self.text = ""

    def json(self):
        return self._json


class FakeStreamResponse:
    """流式响应（_stream_chat 降级路径用）：脚本化 SSE 行"""

    def __init__(self, lines):
        self._lines = list(lines)

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeClient:
    """脚本化的 httpx.AsyncClient 替身：按调用次序弹出响应，并记录每次调用的 payload"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []  # [(kind, payload), ...]

    async def post(self, url, json=None, headers=None, **kwargs):
        # 深拷贝快照：调用方可能事后修改同一 payload（如 400 重试时 pop tools）
        self.calls.append(("post", copy.deepcopy(json)))
        assert self.script, "FakeClient 脚本已耗尽"
        kind, item = self.script.pop(0)
        assert kind == "post", f"脚本类型不匹配: 期望 post，实际 {kind}"
        return item

    def stream(self, method, url, json=None, headers=None, **kwargs):
        self.calls.append(("stream", copy.deepcopy(json)))
        assert self.script, "FakeClient 脚本已耗尽"
        kind, item = self.script.pop(0)
        assert kind == "stream", f"脚本类型不匹配: 期望 stream，实际 {kind}"
        return FakeStreamResponse(item)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


# ── 脚本构造助手 ──────────────────────────────────────────

def post_final(content):
    """非流式最终答案响应"""
    return ("post", FakePostResponse(
        200, {"choices": [{"message": {"content": content}}]}))


def post_tool_call(name, arguments, call_id="call_1", content=None):
    """非流式 tool_calls 响应"""
    tc = {"id": call_id, "type": "function",
          "function": {"name": name, "arguments": arguments}}
    return ("post", FakePostResponse(
        200, {"choices": [{"message": {"content": content, "tool_calls": [tc]}}]}))


def post_raw(json_data):
    return ("post", FakePostResponse(200, json_data))


def post_error(status_code, text):
    return ("post", FakePostResponse(status_code, text=text))


def sse_chunks(*chunks):
    """脚本化 SSE 行（供 _stream_chat 流式路径）"""
    lines = [
        f'data: {json.dumps({"choices": [{"delta": {"content": c}}]}, ensure_ascii=False)}'
        for c in chunks
    ]
    lines.append("data: [DONE]")
    return ("stream", lines)


class FakeRuntime:
    """McpRuntime 替身：记录 execute 调用，可注入返回值/异常"""

    def __init__(self, effect=None, tools=None):
        self.calls = []
        self._effect = effect
        self._tools = TOOLS if tools is None else tools

    async def get_openai_tools(self):
        return list(self._tools)

    async def execute(self, name, arguments=None):
        self.calls.append((name, dict(arguments or {})))
        if self._effect is not None:
            res = self._effect(name, arguments)
            if isinstance(res, BaseException):
                raise res
            return res
        return "4500"


class BrokenCatalogRuntime(FakeRuntime):
    async def get_openai_tools(self):
        raise RuntimeError("connector down")


# ── 公共 fixture / 补丁助手 ───────────────────────────────

@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """每个用例：清空不支持模型集合 + 注入 fake provider"""
    ai_routes._tools_unsupported_models.clear()
    monkeypatch.setattr(ai_routes._llm_manager, "get_active_raw",
                        lambda: dict(PROVIDER))
    yield
    ai_routes._tools_unsupported_models.clear()


def _patch_client(monkeypatch, script):
    fake = FakeClient(script)
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: fake)
    return fake


def _patch_runtime(monkeypatch, runtime):
    import services.agent.mcp_runtime as mcp_runtime_mod
    monkeypatch.setattr(mcp_runtime_mod, "get_mcp_runtime", lambda: runtime)


def _collect(async_gen):
    """asyncio.run 收集异步生成器全部事件"""
    async def run():
        return [item async for item in async_gen]
    return asyncio.run(run())


def _content_of(events):
    return "".join(e.get("content", "") for e in events if isinstance(e, dict))


def _install_chat_api_mocks(monkeypatch, stored):
    """monkeypatch 掉 chat_api 的 DB/人设/记忆积累依赖；stored 记录 add_message 调用"""
    def fake_add_message(sid, role, content):
        stored.append((role, content))
        return {"id": f"m-{len(stored)}", "role": role, "content": content}

    monkeypatch.setattr(ai_routes, "add_message", fake_add_message)
    monkeypatch.setattr(ai_routes, "get_messages", lambda sid: [])
    monkeypatch.setattr(ai_routes, "auto_title", lambda sid, msg: None)
    monkeypatch.setattr(ai_routes, "build_system_prompt", lambda: "SYS")

    import services.agent.memory_accumulator as mem_mod

    async def _noop_acc(sid, reply):
        return None

    monkeypatch.setattr(mem_mod, "accumulate", _noop_acc)


def _run_chat_api(message="金价多少？"):
    async def run():
        resp = await ai_routes.chat_api(
            ai_routes.ChatRequest(session_id="s1", message=message))
        return [p async for p in resp.body_iterator]
    return asyncio.run(run())


def _parse_sse(pieces):
    objs = []
    for p in pieces:
        assert p.startswith("data: "), f"非法 SSE 片段: {p!r}"
        objs.append(json.loads(p[len("data: "):].strip()))
    return objs


# ════════════════════════════════════════════════════════════
# 生成器级测试：_stream_chat_with_tools
# ════════════════════════════════════════════════════════════

class TestToolLoopGenerator:

    def test_full_tool_loop(self, monkeypatch):
        """用例1：完整工具循环 — execute 被正确调用、结果回喂、最终内容收集、含工具状态事件"""
        runtime = FakeRuntime()
        _patch_runtime(monkeypatch, runtime)
        fake = _patch_client(monkeypatch, [
            post_tool_call("get_market_price", "{}"),
            post_final("当前金价 4500"),
        ])

        events = _collect(ai_routes._stream_chat_with_tools(USER_MESSAGES, TOOLS))

        # execute 被调用且参数正确
        assert runtime.calls == [("get_market_price", {})]
        # yield 过 {"tool": ...} 状态事件
        tool_events = [e for e in events if e.get("tool")]
        assert any("正在调用 get_market_price" in e["tool"] for e in tool_events)
        assert any("已完成 get_market_price" in e["tool"] for e in tool_events)
        # 最终 content 被完整收集（20 字符分块）
        assert _content_of(events) == "当前金价 4500"
        assert all(len(e["content"]) <= 20 for e in events if "content" in e)
        # 两次 post；第二次 payload 含 assistant(tool_calls) + tool 结果回喂
        assert len(fake.calls) == 2
        assert "tools" in fake.calls[0][1]
        msgs = fake.calls[1][1]["messages"]
        assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in msgs)
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert tool_msgs and tool_msgs[0]["content"] == "4500"
        assert tool_msgs[0]["tool_call_id"] == "call_1"

    def test_tool_exception_feeds_back(self, monkeypatch):
        """用例3：execute 抛异常 → 结果文本回喂 → 第二轮正常最终答复"""
        runtime = FakeRuntime(effect=lambda n, a: RuntimeError("boom"))
        _patch_runtime(monkeypatch, runtime)
        fake = _patch_client(monkeypatch, [
            post_tool_call("get_market_price", "{}"),
            post_final("工具暂时不可用，但我仍然回答了"),
        ])

        events = _collect(ai_routes._stream_chat_with_tools(USER_MESSAGES, TOOLS))

        assert runtime.calls == [("get_market_price", {})]
        assert _content_of(events) == "工具暂时不可用，但我仍然回答了"
        # 异常文本作为工具结果回喂
        tool_msgs = [m for m in fake.calls[1][1]["messages"] if m.get("role") == "tool"]
        assert tool_msgs and "boom" in tool_msgs[0]["content"]

    def test_five_round_limit(self, monkeypatch):
        """用例4：永远返回 tool_calls → 5 轮后终止，不死循环"""
        runtime = FakeRuntime()
        _patch_runtime(monkeypatch, runtime)
        fake = _patch_client(monkeypatch, [
            post_tool_call("get_market_price", "{}", call_id=f"call_{i}")
            for i in range(10)
        ])

        events = _collect(ai_routes._stream_chat_with_tools(USER_MESSAGES, TOOLS))

        assert len([c for c in fake.calls if c[0] == "post"]) == 5, "应恰好 5 轮"
        assert len(fake.script) == 5, "脚本只应消费 5 条"
        content = _content_of(events)
        assert "轮次已达上限" in content
        assert "4500" in content, "应输出最后一轮工具结果摘要"
        assert len(runtime.calls) == 5

    def test_invalid_json_arguments(self, monkeypatch):
        """用例5：arguments 非法 JSON → 不调用 execute，错误文本作为工具结果回喂"""
        runtime = FakeRuntime()
        _patch_runtime(monkeypatch, runtime)
        fake = _patch_client(monkeypatch, [
            post_tool_call("get_market_price", "not-json"),
            post_final("OK"),
        ])

        events = _collect(ai_routes._stream_chat_with_tools(USER_MESSAGES, TOOLS))

        assert runtime.calls == [], "非法参数不应调用 execute"
        assert _content_of(events) == "OK"
        tool_msgs = [m for m in fake.calls[1][1]["messages"] if m.get("role") == "tool"]
        assert tool_msgs and tool_msgs[0]["content"].startswith("参数解析失败")

    def test_400_retry_without_tools(self, monkeypatch):
        """用例6：首个请求 400（含 tools 字样）→ 去掉 tools 重试成功，模型被记录"""
        runtime = FakeRuntime()
        _patch_runtime(monkeypatch, runtime)
        fake = _patch_client(monkeypatch, [
            post_error(400, '{"error": "tools is not supported by this model"}'),
            post_final("降级后的答案"),
        ])

        events = _collect(ai_routes._stream_chat_with_tools(USER_MESSAGES, TOOLS))

        assert _content_of(events) == "降级后的答案"
        assert len(fake.calls) == 2
        assert "tools" in fake.calls[0][1], "第一次请求应带 tools"
        assert "tools" not in fake.calls[1][1], "重试请求不应带 tools"
        assert "gpt-test" in ai_routes._tools_unsupported_models

    def test_unsupported_model_raises_tools_not_supported(self, monkeypatch):
        """用例6续：已知不支持的模型 → 直接抛 ToolsNotSupported（外层降级）"""
        ai_routes._tools_unsupported_models["gpt-test"] = \
            time.time() + ai_routes._TOOLS_UNSUPPORTED_TTL
        runtime = FakeRuntime()
        _patch_runtime(monkeypatch, runtime)
        _patch_client(monkeypatch, [])

        async def run():
            with pytest.raises(ai_routes.ToolsNotSupported):
                async for _ in ai_routes._stream_chat_with_tools(USER_MESSAGES, TOOLS):
                    pass

        asyncio.run(run())
        assert runtime.calls == []

    def test_empty_message_no_crash(self, monkeypatch):
        """用例7：message 缺 tool_calls 且 content 为空 → 不崩、正常结束"""
        runtime = FakeRuntime()
        _patch_runtime(monkeypatch, runtime)
        fake = _patch_client(monkeypatch, [
            post_raw({"choices": [{"message": {"content": ""}}]}),
        ])

        events = _collect(ai_routes._stream_chat_with_tools(USER_MESSAGES, TOOLS))

        assert events == []
        assert len(fake.calls) == 1
        assert runtime.calls == []


# ════════════════════════════════════════════════════════════
# 字节级回归基准（最重要）
# ════════════════════════════════════════════════════════════

class TestByteLevelRegression:
    """开关关 / 工具目录为空时，chat_api 的 stream 输出与直接调用原 _stream_chat 逐条相等"""

    def _direct_stream_chat(self, monkeypatch, script):
        _patch_client(monkeypatch, script)
        messages = [{"role": "system", "content": "SYS"},
                    {"role": "user", "content": "hello"}]
        return _collect(ai_routes._stream_chat(messages))

    def _chat_api_pieces(self, monkeypatch, script):
        _patch_client(monkeypatch, script)
        stored = []
        _install_chat_api_mocks(monkeypatch, stored)
        pieces = _run_chat_api(message="hello")
        return pieces, stored

    def test_switch_off_byte_equal(self, monkeypatch):
        """tools_enabled=False → 走原路径，输出序列逐条相等"""
        import services.agent.agent_settings as settings_mod
        monkeypatch.setattr(settings_mod, "get_setting",
                            lambda key, default=None: False)

        direct = self._direct_stream_chat(monkeypatch, [sse_chunks("你好", "，世界")])
        pieces, stored = self._chat_api_pieces(monkeypatch, [sse_chunks("你好", "，世界")])

        objs = _parse_sse(pieces)
        content_objs = [o for o in objs if "content" in o]
        done_objs = [o for o in objs if o.get("done")]
        assert len(done_objs) == 1 and "message_id" in done_objs[0]
        # 逐条相等：chat_api 内容序列 == 直接 _stream_chat 输出
        assert [o["content"] for o in content_objs] == \
            [d.get("content", "") for d in direct]
        assert "".join(d.get("content", "") for d in direct) == "你好，世界"
        # full_reply 完整落库
        assert stored[-1] == ("assistant", "你好，世界")

    def test_empty_tool_catalog_byte_equal(self, monkeypatch):
        """tools_enabled=True 但工具目录为空 → 同样走原路径，输出逐条相等"""
        import services.agent.agent_settings as settings_mod
        monkeypatch.setattr(settings_mod, "get_setting",
                            lambda key, default=None: True)
        runtime = FakeRuntime(tools=[])
        _patch_runtime(monkeypatch, runtime)

        direct = self._direct_stream_chat(monkeypatch, [sse_chunks("abc", "def")])
        pieces, stored = self._chat_api_pieces(monkeypatch, [sse_chunks("abc", "def")])

        objs = _parse_sse(pieces)
        content_objs = [o for o in objs if "content" in o]
        assert [o["content"] for o in content_objs] == \
            [d.get("content", "") for d in direct]
        assert not any("tool" in o for o in objs), "不应出现工具状态事件"
        assert stored[-1] == ("assistant", "abcdef")


# ════════════════════════════════════════════════════════════
# chat_api 分流测试（DB 已 monkeypatch）
# ════════════════════════════════════════════════════════════

class TestChatApiRouting:

    def test_tools_path_used_when_enabled(self, monkeypatch):
        """开关开 + 有工具 → 走工具路径：工具事件透传、不累加进 full_reply"""
        import services.agent.agent_settings as settings_mod
        monkeypatch.setattr(settings_mod, "get_setting",
                            lambda key, default=None: True)
        runtime = FakeRuntime()
        _patch_runtime(monkeypatch, runtime)
        fake = _patch_client(monkeypatch, [
            post_tool_call("get_market_price", "{}"),
            post_final("当前金价 4500"),
        ])
        stored = []
        _install_chat_api_mocks(monkeypatch, stored)

        pieces = _run_chat_api()

        objs = _parse_sse(pieces)
        tool_events = [o for o in objs if "tool" in o]
        assert tool_events, "应透传工具状态事件"
        assert any("正在调用" in o["tool"] for o in tool_events)
        content = "".join(o.get("content", "") for o in objs if "content" in o)
        assert content == "当前金价 4500"
        # {"tool": ...} 事件不得累加进 full_reply
        assert stored[-1] == ("assistant", "当前金价 4500")
        assert runtime.calls == [("get_market_price", {})]
        assert any(o.get("done") for o in objs)

    def test_fallback_to_stream_chat_on_tools_failure(self, monkeypatch):
        """工具路径抛 ToolsNotSupported（尚未输出内容）→ 降级原流式路径重发成功"""
        import services.agent.agent_settings as settings_mod
        monkeypatch.setattr(settings_mod, "get_setting",
                            lambda key, default=None: True)
        runtime = FakeRuntime()
        _patch_runtime(monkeypatch, runtime)
        ai_routes._tools_unsupported_models["gpt-test"] = \
            time.time() + ai_routes._TOOLS_UNSUPPORTED_TTL
        fake = _patch_client(monkeypatch, [sse_chunks("降级流式答案")])
        stored = []
        _install_chat_api_mocks(monkeypatch, stored)

        pieces = _run_chat_api()

        objs = _parse_sse(pieces)
        content = "".join(o.get("content", "") for o in objs if "content" in o)
        assert content == "降级流式答案"
        assert fake.calls and fake.calls[0][0] == "stream", "降级应走流式路径"
        assert stored[-1] == ("assistant", "降级流式答案")
        assert any(o.get("done") for o in objs)

    def test_get_openai_tools_failure_falls_back(self, monkeypatch):
        """工具目录获取异常 → tools=[] → 直接走原流式路径"""
        import services.agent.agent_settings as settings_mod
        monkeypatch.setattr(settings_mod, "get_setting",
                            lambda key, default=None: True)
        _patch_runtime(monkeypatch, BrokenCatalogRuntime())
        fake = _patch_client(monkeypatch, [sse_chunks("无工具答案")])
        stored = []
        _install_chat_api_mocks(monkeypatch, stored)

        pieces = _run_chat_api()

        objs = _parse_sse(pieces)
        content = "".join(o.get("content", "") for o in objs if "content" in o)
        assert content == "无工具答案"
        assert fake.calls and fake.calls[0][0] == "stream"
        assert not any("tool" in o for o in objs)

    def test_chat_api_source_structure(self):
        """结构性检查：chat_api 源码包含分流/降级/开关关键逻辑"""
        src = inspect.getsource(ai_routes.chat_api)
        assert "_stream_chat_with_tools" in src, "应分流到工具路径"
        assert "tools_enabled" in src, "应读取 tools_enabled 开关"
        assert "emitted" in src, "应有 emitted 标志控制降级重发"
        assert "_stream_chat(" in src, "应保留原路径降级"
        assert "memory_accumulator" in src or "accumulate" in src, "应保留记忆积累挂钩"


# ════════════════════════════════════════════════════════════
# 400 判定收窄 + 黑名单 TTL
# ════════════════════════════════════════════════════════════

class TestBlacklistNarrowingAndTTL:

    def test_400_with_tool_word_but_no_phrase_not_blacklisted(self, monkeypatch):
        """400 报文含 tool 字样但不含不支持短语 → 不进黑名单，按普通错误抛"""
        runtime = FakeRuntime()
        _patch_runtime(monkeypatch, runtime)
        _patch_client(monkeypatch, [
            post_error(400, '{"error": "tool call rejected by policy"}'),
        ])

        async def run():
            with pytest.raises(RuntimeError):
                async for _ in ai_routes._stream_chat_with_tools(USER_MESSAGES, TOOLS):
                    pass

        asyncio.run(run())
        assert "gpt-test" not in ai_routes._tools_unsupported_models, (
            "未命中不支持短语时不应进黑名单")

    def test_phrase_hit_blacklisted_and_ttl_recovers(self, monkeypatch):
        """命中不支持短语 → 进黑名单（带 TTL）；过期前抛 ToolsNotSupported，过期后恢复"""
        fake_now = {"t": 1_000_000.0}
        monkeypatch.setattr(ai_routes.time, "time", lambda: fake_now["t"])
        runtime = FakeRuntime()
        _patch_runtime(monkeypatch, runtime)
        fake = _patch_client(monkeypatch, [
            post_error(400, '{"error": "this model does not support tools"}'),
            post_final("降级后的答案"),
        ])

        events = _collect(ai_routes._stream_chat_with_tools(USER_MESSAGES, TOOLS))

        assert _content_of(events) == "降级后的答案"
        assert "tools" not in fake.calls[1][1], "重试请求不应带 tools"
        assert "gpt-test" in ai_routes._tools_unsupported_models
        expire_at = ai_routes._tools_unsupported_models["gpt-test"]
        assert expire_at == fake_now["t"] + ai_routes._TOOLS_UNSUPPORTED_TTL

        # 过期前：仍判定不支持，直接抛 ToolsNotSupported（不发请求）
        fake_now["t"] += ai_routes._TOOLS_UNSUPPORTED_TTL - 1

        async def run_blocked():
            with pytest.raises(ai_routes.ToolsNotSupported):
                async for _ in ai_routes._stream_chat_with_tools(USER_MESSAGES, TOOLS):
                    pass

        asyncio.run(run_blocked())
        assert len(fake.calls) == 2, "黑名单命中时不应再发请求"

        # 过期后：黑名单条目被剪除，模型恢复
        fake_now["t"] += 2.0
        assert ai_routes._model_tools_unsupported("gpt-test") is False
        assert "gpt-test" not in ai_routes._tools_unsupported_models
