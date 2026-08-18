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

# ── System Prompt ───────────────────────────────────────

SYSTEM_PROMPT = """你是「金探」，一位专业的 XAUUSD 黄金量化交易分析师，内置于 AlgoForge 交易系统中。

你的能力：
- 精通黄金微结构、流动性猎取、ICT 价格行为
- 熟悉本系统的三轨架构（DataFactory → 策略员 → 运动员）
- 能读取实时持仓、账户、信号、指标缓存、新闻方向
- 熟悉系统 18 个活跃策略的进出场逻辑

你的回答风格：
- 用中文回答，简洁专业，不废话
- 给观点时附带理由和依据（引用具体指标数值/持仓数据）
- 涉及风险时主动提示
- 不确定时说"不确定"，不编造数据
- 如果用户问的数据你没有，说明需要什么条件才能获取

你的限制：
- 不直接执行交易（平仓/开仓），只给建议
- 不预测精确价格点位，给的是区间和概率
- 严格遵守交易纪律提示
"""


def build_system_prompt() -> str:
    """构建 system prompt，包含人设 + 实时交易上下文"""
    context = _gather_trading_context()
    if context:
        return SYSTEM_PROMPT + "\n\n" + context
    return SYSTEM_PROMPT


def _gather_trading_context() -> str:
    """收集当前交易上下文，注入 system prompt"""
    from dashboard.backend.engine_runner import EngineRunner
    engine_runner = EngineRunner.get_instance()

    lines = ["\n【当前交易上下文】"]
    now = datetime.now(LOCAL_TZ)
    lines.append(f"时间: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC+8")

    # 引擎状态
    if engine_runner:
        try:
            status = engine_runner.get_status()
            lines.append(f"引擎: {status.get('status', '?')} (uptime {status.get('uptime_seconds', 0):.0f}s), 桥接: {'已连接' if status.get('bridge_connected') else '未连接'}")
        except Exception:
            pass

        # 账户快照
        try:
            acct = engine_runner._cached_account
            if acct:
                lines.append(f"账户: 余额 ${acct.get('balance', 0):.2f} | 净值 ${acct.get('equity', 0):.2f} | 浮盈 ${acct.get('floating_pnl', 0):+.2f} | 可用 ${acct.get('free_margin', 0):.2f}")
        except Exception:
            pass

        # 持仓
        try:
            positions = engine_runner._fresh_positions()
            if positions:
                lines.append("持仓:")
                for p in positions[:5]:
                    direction = p.get('type', p.get('order_type', '?'))
                    vol = p.get('volume', 0)
                    entry = p.get('open_price', p.get('entry_price', 0))
                    profit = p.get('profit', p.get('floating_pnl', 0))
                    sl = p.get('stop_loss', 0)
                    tp = p.get('take_profit', 0)
                    ticket = p.get('ticket', '?')
                    lines.append(f"  - #{ticket} {direction} {vol} XAUUSD @{entry} 浮盈${profit:+.2f} 止损{sl} 止盈{tp}")
            else:
                lines.append("持仓: 无")
        except Exception:
            pass

        # 当前价格
        try:
            price = engine_runner._cached_price
            if price:
                bid = price.get('bid', 0)
                ask = price.get('ask', 0)
                spread = round(ask - bid, 2)
                lines.append(f"价格: bid {bid} ask {ask} spread {spread}")
        except Exception:
            pass

        # 指标快照
        try:
            indicators = engine_runner._cached_indicators
            if indicators:
                lines.append("指标:")
                for tf in ('M30', 'H1', 'H4'):
                    tf_data = indicators.get(tf, {})
                    if tf_data:
                        rsi = tf_data.get('rsi', '?')
                        macd = tf_data.get('macd', {})
                        bb = tf_data.get('bb', {})
                        atr = tf_data.get('atr', '?')
                        adx = tf_data.get('adx', '?')
                        trend = tf_data.get('trend', '?')
                        ema9 = tf_data.get('ema_9', '?')
                        ema21 = tf_data.get('ema_21', '?')
                        macd_str = f"MACD={macd.get('macd','?')}/{macd.get('signal','?')}" if isinstance(macd, dict) else ""
                        bb_str = f"BB({bb.get('upper','?')}/{bb.get('mid','?')}/{bb.get('lower','?')})" if isinstance(bb, dict) else ""
                        lines.append(f"  {tf}: RSI={rsi} {macd_str} {bb_str} ATR={atr} ADX={adx} EMA9={ema9} EMA21={ema21} 趋势={trend}")
        except Exception:
            pass

        # 策略列表
        try:
            strats = engine_runner.get_active_strategies()
            if strats:
                names = [s.get('name', s) if isinstance(s, dict) else str(s) for s in strats]
                lines.append(f"策略: {len(names)}个活跃 - {', '.join(names[:8])}")
        except Exception:
            pass

    # 新闻方向
    try:
        news_lines = _get_latest_news(3)
        if news_lines:
            lines.append("新闻:")
            for n in news_lines:
                lines.append(f"  - [{n['direction']}] {n['content'][:60]}")
    except Exception:
        pass

    # 经济日历
    try:
        events = _get_today_calendar()
        if events:
            lines.append(f"经济日历: {events}")
    except Exception:
        pass

    return "\n".join(lines)


def _get_latest_news(limit=3):
    """获取最近 N 条黄金新闻方向"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT content, direction, direction_confidence, news_time FROM gold_news ORDER BY fetched_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_today_calendar():
    """获取今日经济日历"""
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT time, title, impact, forecast, previous FROM news_calendar WHERE date=? ORDER BY time",
            (today,)
        ).fetchall()
        if not rows:
            return ""
        return "; ".join(f"{r['time'] or ''} {r['title']}({r['impact'] or ''})" for r in rows[:5])
    finally:
        conn.close()


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
