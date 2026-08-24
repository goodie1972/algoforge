"""
记忆自动积累器
==============
每轮对话结束后（由 routes/ai.py 的 stream() 尾部挂钩触发），
用 LLM 从最近对话中提取值得长期记住的用户偏好/决策要点，
追加写入 persona 的 memory.md（带 [MM-DD] 日期前缀，超 2000 字从头部裁剪）。

设计要点：
- 模块级 asyncio 单飞锁：已有提取任务在跑则跳过本次
- 任务引用存入模块级 set 防 GC
- 全流程 try/except，任何异常只记日志，绝不向上抛出
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from services.agent import agent_settings
from services.agent.persona_manager import MAX_PERSONA_CHARS, get_persona_manager

logger = logging.getLogger(__name__)

# 提取时取会话最近消息条数（含本轮）
RECENT_MESSAGES = 6

# 单飞锁：同一时刻最多一个提取任务在跑
_single_flight = asyncio.Lock()

# 运行中任务引用集合（防 GC）
_pending_tasks: set = set()

# 固定提取提示词
_EXTRACT_PROMPT = (
    "从以下对话中提取值得长期记住的用户偏好/决策要点，"
    "输出 1-3 条，每条≤50字，用中文。若无值得记录的，只输出 NONE。对话：\n"
)


async def accumulate(session_id: str, reply_text: str = "") -> None:
    """异步积累记忆入口：开关检查 + 单飞检查后调度后台任务，绝不抛异常"""
    try:
        if not agent_settings.get_setting("memory_auto_accumulate"):
            return
        if _single_flight.locked():
            logger.info("[MemoryAccumulate] 已有提取任务运行中，跳过本次")
            return
        task = asyncio.create_task(_run(session_id, reply_text))
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)
    except Exception as e:
        logger.warning(f"[MemoryAccumulate] schedule failed: {e}")


async def _run(session_id: str, reply_text: str) -> None:
    """实际提取流程（单飞锁内执行，异常全部吞掉只记日志）"""
    async with _single_flight:
        try:
            transcript = _build_transcript(session_id, reply_text)
            if not transcript:
                logger.info("[MemoryAccumulate] 无可提取的对话内容，跳过")
                return
            extraction = await _extract(transcript)
            if extraction is None:
                logger.warning("[MemoryAccumulate] LLM 无响应，跳过")
                return
            extraction = extraction.strip()
            if extraction.upper() == "NONE":
                return
            if not extraction:
                return
            _append_memory(extraction)
        except Exception as e:
            logger.warning(f"[MemoryAccumulate] accumulate failed: {e}")


def _build_transcript(session_id: str, reply_text: str = "") -> str:
    """取会话最近 RECENT_MESSAGES 条消息拼成「用户: ... / 助手: ...」文本"""
    from dashboard.backend.ai_service import get_messages

    msgs = (get_messages(session_id) or [])[-RECENT_MESSAGES:]
    role_labels = {"user": "用户", "assistant": "助手"}
    lines: list[str] = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        label = role_labels.get(m.get("role", ""))
        if label is None:
            continue
        content = str(m.get("content", "")).strip()
        if content:
            lines.append(f"{label}: {content}")
    # 兜底：DB 中尚无本轮助手回复时，用传入的 reply_text 补上
    if reply_text.strip() and not any(l.startswith("助手: ") for l in lines[-1:]):
        lines.append(f"助手: {reply_text.strip()}")
    return "\n".join(lines)


async def _extract(transcript: str) -> Optional[str]:
    """用 LLMProviderManager.chat 非流式调用提取记忆要点（同步方法用 to_thread 包裹）"""
    from services.llm_provider import LLMProviderManager

    mgr = LLMProviderManager()
    messages = [{"role": "user", "content": _EXTRACT_PROMPT + transcript}]
    return await asyncio.to_thread(lambda: mgr.chat(messages, temperature=0.2))


def _append_memory(extraction: str) -> None:
    """把提取结果以 `- [MM-DD] 内容` 形式追加到 memory.md，超限从头部逐行裁剪"""
    pm = get_persona_manager()
    current = pm.load_memory()

    stamp = datetime.now().strftime("%m-%d")
    new_lines = [ln.strip() for ln in extraction.splitlines() if ln.strip()]
    if not new_lines:
        return
    # 首行加日期前缀，后续行（若 LLM 输出多行）原样保留
    entry_lines = [f"- [{stamp}] {new_lines[0]}"] + new_lines[1:]
    entry = "\n".join(entry_lines)

    if current.strip():
        new_text = current.rstrip("\n") + "\n" + entry
    else:
        new_text = entry

    # 超过 2000 字：从头部逐行裁掉最旧条目（绝不裁本次新增行）
    lines = new_text.split("\n")
    protected = len(entry_lines)
    while len(new_text) > MAX_PERSONA_CHARS and len(lines) > protected:
        lines.pop(0)
        new_text = "\n".join(lines)
    # 兜底：单条超长新条目经头部裁剪后仍超限时，字符级尾部截断
    # （此时剩余内容必为受保护的新条目，截其尾部可接受）
    if len(new_text) > MAX_PERSONA_CHARS:
        new_text = new_text[:MAX_PERSONA_CHARS]

    pm.save_memory(new_text)
    logger.info(f"[MemoryAccumulate] memory.md 追加 {len(entry)} 字（总计 {len(new_text)} 字）")
