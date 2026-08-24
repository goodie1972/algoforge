"""
MCP 协议客户端（零第三方 SDK，仅 httpx + asyncio + 标准库）
==============================================================
实现 Model Context Protocol（JSON-RPC 2.0）客户端，支持两种传输：
  - StdioTransport：本地子进程（stdin/stdout 换行分隔 JSON），绝不 shell=True
  - SseTransport  ：旧版 HTTP+SSE 远程传输（endpoint 事件 + POST）

分层设计（协议层对传输无感知，可注入假传输测试）：
  Transport（抽象） → JsonRpcSession（请求/响应分发） → McpClient（MCP 语义）

关键纯函数（便于单测）：
  - resolve_stdio_argv(command, args)：Windows .cmd/.bat 垫片解析
  - parse_sse_lines(lines)：SSE 行解析
  - parse_json_line(line)：坏行容错的 JSON 行解析
"""

import asyncio
import json
import logging
import os
import shutil
import urllib.parse
from collections import deque
from typing import Optional, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

# MCP 协议版本与客户端标识（任务规格约定）
PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "AlgoForge", "version": "1.0"}

# 超时约定（秒）
INITIALIZE_TIMEOUT = 15.0
LIST_TOOLS_TIMEOUT = 8.0
CALL_TOOL_TIMEOUT = 30.0
SSE_ENDPOINT_TIMEOUT = 15.0
STDERR_RING_LINES = 100


# ════════════════════════════════════════════════════════════
# 异常
# ════════════════════════════════════════════════════════════

class McpConnectionError(Exception):
    """连接/传输层错误（可读信息）"""


class JsonRpcError(Exception):
    """JSON-RPC error 响应"""

    def __init__(self, code, message):
        self.code = code
        self.message = message or ""
        super().__init__(f"JSON-RPC 错误 [{code}]: {self.message}")


# ════════════════════════════════════════════════════════════
# 纯函数：行解析 / 命令解析（单测直接覆盖）
# ════════════════════════════════════════════════════════════

def parse_json_line(line: str) -> Optional[dict]:
    """解析一行 JSON 消息；坏行或非对象返回 None（容错，不抛）"""
    text = (line or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def parse_sse_lines(lines: list) -> list:
    """解析 SSE 行序列为事件列表 [{"event": ..., "data": ...}, ...]

    规则：空行分隔事件；`:` 开头为注释；`event:` 指定事件类型（缺省 message）；
    多个 `data:` 行以 \\n 拼接；末尾无空行的尾事件也会输出。
    """
    events = []
    event_type = None
    data_parts: list = []

    def flush():
        nonlocal event_type, data_parts
        if event_type is not None or data_parts:
            events.append({"event": event_type or "message",
                           "data": "\n".join(data_parts)})
        event_type = None
        data_parts = []

    for raw in lines:
        line = str(raw).rstrip("\r")
        if line == "":
            flush()
            continue
        if line.startswith(":"):
            continue  # 注释（含 keep-alive）
        if ":" in line:
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
        else:
            field, value = line, ""
        if field == "event":
            event_type = value
        elif field == "data":
            data_parts.append(value)
    flush()
    return events


# cmd 元字符集合（&|<>^%";, 任一出现即需整体加引号）
_CMD_METACHARS = frozenset('&|<>^%";,')


def _quote_for_cmd(arg: str) -> str:
    """`cmd /c` 垫片参数的 cmd 元字符安全处理。

    若 arg 为空、或含任一 &|<>^%";, 元字符、或含空白字符，则整体加双引号，
    并把内部已有双引号转义为 \"（采用反斜杠转义风格：cmd 将引号内内容
    原样透传给目标程序，目标程序按 C 运行时惯例解析 \"）；否则原样返回。
    """
    arg = str(arg)
    if not arg or any(c in _CMD_METACHARS for c in arg) or any(c.isspace() for c in arg):
        return '"' + arg.replace('"', '\\"') + '"'
    return arg


def resolve_stdio_argv(command: str, args: list) -> list:
    """解析 stdio 启动 argv（绝不经过 shell）。

    - shutil.which 解析成功：普通可执行文件 → [解析值, *args]
    - 解析结果为 .cmd/.bat（npx/uvx 垫片）→ ["cmd", "/c", 解析值, *args]
    - which 找不到且原命令含路径分隔符 → 直接用原值
    - 其余失败 → 抛可读 RuntimeError
    """
    command = str(command or "").strip()
    if not command:
        raise RuntimeError("stdio 连接器缺少 command")
    resolved = shutil.which(command)
    if resolved is None:
        if "/" in command or "\\" in command:
            return [command, *[str(a) for a in args]]
        raise RuntimeError(f"找不到命令: {command!r}（请确认已安装并位于 PATH 中）")
    argv = [resolved, *[str(a) for a in args]]
    if resolved.lower().endswith((".cmd", ".bat")):
        # 经 cmd /c 的所有参数（含解析出的垫片路径）都做 cmd 元字符安全处理，防注入
        return ["cmd", "/c", *[_quote_for_cmd(a) for a in argv]]
    return argv


# ════════════════════════════════════════════════════════════
# 传输抽象
# ════════════════════════════════════════════════════════════

@runtime_checkable
class Transport(Protocol):
    """传输抽象：协议层对传输无感知（可注入假传输测试）"""

    async def start(self) -> None: ...

    async def send(self, msg: dict) -> None: ...

    async def recv(self) -> dict:
        """接收一条消息；返回 None 表示连接已断开"""
        ...

    async def close(self) -> None: ...


class StdioTransport:
    """stdio 子进程传输：换行分隔 JSON，绝不 shell=True"""

    def __init__(self, connector: dict):
        self._connector = connector or {}
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self._stderr_ring: deque = deque(maxlen=STDERR_RING_LINES)
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._closed = False
        self.disconnected = False
        self.bad_lines = 0  # 坏 JSON 行计数（容错诊断）

    async def start(self) -> None:
        argv = resolve_stdio_argv(self._connector.get("command"),
                                  list(self._connector.get("args") or []))
        env = {**os.environ,
               **(self._connector.get("env") or {}),
               "PYTHONIOENCODING": "utf-8"}
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except Exception as e:
            raise McpConnectionError(
                f"启动子进程失败: {argv[0]}: {e}") from e
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        logger.info(f"[McpClient] stdio 已启动: {argv}")

    async def _read_stdout(self):
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:  # EOF → 标记断开
                self.disconnected = True
                self._queue.put_nowait(None)
                break
            msg = parse_json_line(line.decode("utf-8", errors="replace"))
            if msg is None:
                if line.strip():
                    self.bad_lines += 1
                    logger.debug(f"[McpClient] 跳过坏 JSON 行（累计 {self.bad_lines}）")
                continue
            self._queue.put_nowait(msg)

    async def _read_stderr(self):
        """stderr 单独吸入环形缓冲，防止管道写满卡死"""
        assert self._proc and self._proc.stderr
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                self._stderr_ring.append(text)

    def stderr_tail(self) -> list:
        """返回 stderr 环形缓冲内容（供错误诊断）"""
        return list(self._stderr_ring)

    async def send(self, msg: dict) -> None:
        if self._closed or self._proc is None or self._proc.stdin is None:
            raise McpConnectionError("stdio 传输未连接，无法发送")
        payload = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self._proc.stdin.write(payload)
            await self._proc.stdin.drain()
        except Exception as e:
            raise McpConnectionError(f"stdio 写入失败: {e}") from e

    async def recv(self) -> dict:
        return await self._queue.get()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        proc = self._proc
        if proc is not None and proc.returncode is None:
            try:
                if proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.close()
            except Exception:
                pass
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), 2)
            except (asyncio.TimeoutError, TimeoutError):
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            except Exception:
                pass
        for task in (self._reader_task, self._stderr_task):
            if task and not task.done():
                task.cancel()
        self._queue.put_nowait(None)


class SseTransport:
    """旧版 HTTP+SSE 传输：首个 `event: endpoint` 事件给出 POST 地址，
    之后请求走 POST，响应经 SSE 流 data 行回传。

    注：Streamable HTTP 新传输暂不支持（15s 未收到 endpoint 会给出提示）。
    """

    def __init__(self, connector: dict):
        self._connector = connector or {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._client: Optional[httpx.AsyncClient] = None
        self._stream_ctx = None
        self._resp = None
        self._lines_iter = None
        self._reader_task: Optional[asyncio.Task] = None
        self._post_url: str = ""
        self._closed = False
        self.disconnected = False

    async def start(self) -> None:
        url = str(self._connector.get("url") or "").strip()
        if not url:
            raise McpConnectionError("sse 连接器缺少 url")
        # 代理约定与现有 routes/ai.py 一致：仅环境变量
        proxy = (os.environ.get("LLM_PROXY") or os.environ.get("HTTPS_PROXY")
                 or os.environ.get("https_proxy") or "")
        # SSE 为长连接：读侧不设超时（避免与 30s 工具调用矛盾），
        # 读侧时限交给协议层 wait_for；连接/写/池超时保持 15s
        kwargs: dict = {"timeout": httpx.Timeout(connect=15.0, read=None, write=15.0, pool=15.0)}
        if proxy:
            kwargs["proxy"] = proxy
        headers = {str(k): str(v) for k, v in (self._connector.get("headers") or {}).items()}
        headers.setdefault("Accept", "text/event-stream")

        self._client = httpx.AsyncClient(**kwargs)
        try:
            self._stream_ctx = self._client.stream("GET", url, headers=headers)
            self._resp = await self._stream_ctx.__aenter__()
            self._resp.raise_for_status()
            self._lines_iter = self._resp.aiter_lines()
            try:
                endpoint = await asyncio.wait_for(self._read_endpoint(),
                                                  SSE_ENDPOINT_TIMEOUT)
            except (asyncio.TimeoutError, TimeoutError):
                raise McpConnectionError(
                    "未收到 endpoint 事件，该服务可能为 Streamable HTTP 传输，暂不支持")
            # 相对路径 → 基于 SSE url 拼接
            self._post_url = urllib.parse.urljoin(url, endpoint)
            self._reader_task = asyncio.create_task(self._read_loop())
            logger.info(f"[McpClient] sse 已连接: {url} → POST {self._post_url}")
        except McpConnectionError:
            await self._teardown()
            raise
        except Exception as e:
            await self._teardown()
            raise McpConnectionError(f"sse 连接失败: {url}: {e}") from e

    async def _read_endpoint(self) -> str:
        """从流头部读取首个 endpoint 事件的 data（POST 地址）"""
        buffer: list = []
        async for line in self._lines_iter:
            buffer.append(line)
            if str(line).strip() == "":
                events = parse_sse_lines(buffer)
                buffer = []
                for ev in events:
                    if ev.get("event") == "endpoint" and ev.get("data"):
                        return ev["data"].strip()
        raise McpConnectionError("SSE 流已结束但未收到 endpoint 事件")

    def _dispatch_events(self, events: list) -> None:
        """把解析出的 SSE 事件分发入消息队列（endpoint 事件忽略）"""
        for ev in events:
            if ev.get("event") == "endpoint":
                continue
            data = parse_json_line(ev.get("data") or "")
            if data is not None:
                self._queue.put_nowait(data)

    async def _read_loop(self):
        buffer: list = []
        try:
            async for line in self._lines_iter:
                buffer.append(line)
                if str(line).strip() == "":
                    self._dispatch_events(parse_sse_lines(buffer))
                    buffer = []
            # 流正常结束：对残留 buffer 中未以空行收尾的尾事件再解析分发一次
            if buffer:
                self._dispatch_events(parse_sse_lines(buffer))
        except Exception as e:
            logger.debug(f"[McpClient] sse 读循环结束: {e}")
        finally:
            self.disconnected = True
            self._queue.put_nowait(None)

    async def send(self, msg: dict) -> None:
        if self._closed or self._client is None or not self._post_url:
            raise McpConnectionError("sse 传输未连接，无法发送")
        try:
            resp = await self._client.post(self._post_url, json=msg)
            resp.raise_for_status()
        except Exception as e:
            raise McpConnectionError(f"sse POST 失败: {e}") from e

    async def recv(self) -> dict:
        return await self._queue.get()

    async def _teardown(self):
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        if self._stream_ctx is not None:
            try:
                await self._stream_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._stream_ctx = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._teardown()
        self._queue.put_nowait(None)


def _create_transport(connector: dict) -> Transport:
    conn_type = (connector or {}).get("type")
    if conn_type == "stdio":
        return StdioTransport(connector)
    if conn_type == "sse":
        return SseTransport(connector)
    raise McpConnectionError(f"不支持的连接器类型: {conn_type!r}（支持 stdio / sse）")


# ════════════════════════════════════════════════════════════
# JSON-RPC 会话
# ════════════════════════════════════════════════════════════

class JsonRpcSession:
    """JSON-RPC 2.0 会话：自增 id、pending Future 表、按 id 分发响应"""

    def __init__(self, transport: Transport):
        self._transport = transport
        self._next_id = 1
        self._pending: dict = {}
        self._listen_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._listen_task = asyncio.create_task(self._listen())

    async def _listen(self):
        while True:
            try:
                msg = await self._transport.recv()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"[JsonRpc] recv 异常: {e}")
                msg = None
            if msg is None:
                self._fail_pending(McpConnectionError("连接已断开"))
                break
            self._dispatch(msg)

    def _dispatch(self, msg: dict):
        mid = msg.get("id")
        if mid is None:
            return  # 通知消息：忽略
        fut = self._pending.pop(mid, None)
        if fut is None or fut.done():
            return
        if "error" in msg and msg["error"] is not None:
            err = msg["error"] if isinstance(msg["error"], dict) else {}
            fut.set_exception(JsonRpcError(err.get("code"), err.get("message")))
        else:
            fut.set_result(msg.get("result"))

    def _fail_pending(self, exc: Exception):
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

    async def request(self, method: str, params=None, timeout: float = 30.0):
        """发送请求并等待响应；超时抛 TimeoutError"""
        mid = self._next_id
        self._next_id += 1
        msg = {"jsonrpc": "2.0", "id": mid, "method": method}
        if params is not None:
            msg["params"] = params
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[mid] = fut
        try:
            await self._transport.send(msg)
            return await asyncio.wait_for(fut, timeout)
        finally:
            # 全路径清理 pending 表（发送失败/超时/取消）；
            # 成功路径分发时已 pop，此处 pop 幂等
            self._pending.pop(mid, None)

    async def notify(self, method: str, params=None) -> None:
        """发送通知（不带 id、不等待响应）"""
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await self._transport.send(msg)

    async def close(self) -> None:
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
        self._fail_pending(McpConnectionError("会话已关闭"))


# ════════════════════════════════════════════════════════════
# MCP 客户端
# ════════════════════════════════════════════════════════════

class McpClient:
    """面向单个连接器的 MCP 客户端。

    `transport` 参数用于测试注入（生产按连接器 type 自动创建）。
    """

    def __init__(self, connector: dict, transport: Optional[Transport] = None):
        self.connector = connector or {}
        self._transport = transport
        self._session: Optional[JsonRpcSession] = None
        self.connected = False

    @property
    def transport(self):
        return self._transport

    async def connect(self) -> None:
        if self._transport is None:
            self._transport = _create_transport(self.connector)
        await self._transport.start()
        self._session = JsonRpcSession(self._transport)
        await self._session.start()
        await self._session.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": dict(CLIENT_INFO),
        }, timeout=INITIALIZE_TIMEOUT)
        await self._session.notify("notifications/initialized")
        self.connected = True

    async def list_tools(self) -> list:
        result = await self._session.request("tools/list", {},
                                             timeout=LIST_TOOLS_TIMEOUT)
        result = result or {}
        return list(result.get("tools") or [])

    async def call_tool(self, name: str, arguments: Optional[dict] = None,
                        timeout: float = CALL_TOOL_TIMEOUT) -> str:
        result = await self._session.request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        }, timeout=timeout)
        result = result or {}
        texts = [str(c.get("text", ""))
                 for c in (result.get("content") or [])
                 if isinstance(c, dict) and c.get("type") == "text"]
        if not texts:
            return "（工具未返回内容）"
        text = "".join(texts)
        if result.get("isError"):
            text = f"工具执行错误: {text}"
        return text

    async def close(self) -> None:
        self.connected = False
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
        if self._transport is not None:
            try:
                await self._transport.close()
            except Exception:
                pass
