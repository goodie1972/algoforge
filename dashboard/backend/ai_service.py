"""
AI 交易助理服务 — 上下文收集 + System Prompt 构建 + LLM 调用
"""
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from typing import Optional

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from config.settings import LOCAL_TZ, dt_local
from data.database import get_conn

logger = logging.getLogger("dashboard.backend.ai_service")

def build_system_prompt() -> str:
    """构建 system prompt，包含人设 + 实时交易上下文 + 技能"""
    from services.agent.context_builder import get_builder
    from services.agent.persona_manager import get_persona_manager
    from services.agent.skill_loader import get_loader

    # 确保技能已扫描（首次调用时加载）
    loader = get_loader()
    if not loader.all_skills():
        loader.rescan()

    # 上下文（含 K线/信号/成交/策略等增强）
    builder = get_builder()
    context = builder.build(["engine", "positions", "price", "indicators", "kline",
                             "signals", "trades", "strategies", "news", "calendar"])

    # 技能上下文
    skills_text = loader.get_summary_context()
    if skills_text:
        context += "\n\n【可用技能】\n" + skills_text

    # 人设组装
    prompt = get_persona_manager().build_system_prompt(context)
    return prompt


def _gather_trading_context() -> str:
    """保留兼容性，新代码请直接使用 build_system_prompt"""
    from services.agent.context_builder import get_builder
    return get_builder().build(["engine", "positions", "price", "indicators",
                                "signals", "trades", "strategies", "news", "calendar"])


# ── 会话管理 ────────────────────────────────────────────

def create_session(title: str = "新会话") -> dict:
    """创建新会话，返回 {id, title, created_at}"""
    session_id = str(uuid.uuid4())[:8]
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO chat_sessions (id, title) VALUES (?, ?)",
            (session_id, title)
        )
        conn.commit()
        return {"id": session_id, "title": title, "created_at": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")}
    finally:
        conn.close()


def list_sessions() -> list[dict]:
    """列出所有会话，按更新时间倒序"""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT s.id, s.title, s.created_at, s.updated_at,
                      (SELECT COUNT(*) FROM chat_messages WHERE session_id = s.id) as msg_count
               FROM chat_sessions s
               ORDER BY s.updated_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_messages(session_id: str) -> list[dict]:
    """获取会话所有消息"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, role, content, created_at FROM chat_messages WHERE session_id=? ORDER BY id",
            (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_message(session_id: str, role: str, content: str, context_snapshot: str = "") -> dict:
    """添加消息，返回 {id, role, content, created_at}"""
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, context_snapshot) VALUES (?, ?, ?, ?)",
            (session_id, role, content, context_snapshot)
        )
        # 更新会话 updated_at
        conn.execute(
            "UPDATE chat_sessions SET updated_at = datetime('now', 'localtime') WHERE id = ?",
            (session_id,)
        )
        conn.commit()
        msg_id = cur.lastrowid
        return {"id": msg_id, "role": role, "content": content,
                "created_at": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")}
    finally:
        conn.close()


def delete_session(session_id: str) -> bool:
    """删除会话及其所有消息"""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def update_session_title(session_id: str, title: str) -> bool:
    """更新会话标题"""
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE chat_sessions SET title=?, updated_at=datetime('now', 'localtime') WHERE id=?",
            (title, session_id)
        )
        conn.commit()
        return True
    finally:
        conn.close()


def auto_title(session_id: str, first_msg: str):
    """从第一条消息自动生成标题"""
    title = first_msg[:20].replace("\n", " ").strip()
    if len(first_msg) > 20:
        title += "..."
    update_session_title(session_id, title)
