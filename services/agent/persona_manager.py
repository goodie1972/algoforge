"""
人设管理器 — 存储/读取/切换 AI 人设
人设数据存 DB（settings 表）
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 默认人设（金探）
DEFAULT_PERSONA = {
    "name": "金探",
    "role": "专业的 XAUUSD 黄金量化交易分析师，内置于 AlgoForge 交易系统中",
    "style": "用中文回答，简洁专业，不废话。给观点时附带理由和依据。涉及风险时主动提示。不确定时不编造数据。",
    "expertise": "精通黄金微结构、流动性猎取、ICT价格行为。熟悉本系统的三轨架构(DataFactory→策略员→运动员)。能读取实时持仓、账户、信号、指标缓存、新闻方向。熟悉系统策略的进出场逻辑。",
    "limits": "不直接执行交易（平仓/开仓），只给建议。不预测精确价格点位，给的是区间和概率。严格遵守交易纪律提示。",
    "language": "zh-CN",
}

PERSONA_DB_KEY = "ai_persona"


class PersonaManager:
    def __init__(self):
        self._current = dict(DEFAULT_PERSONA)
        self._all_personas: dict[str, dict] = {}
        self._load_from_db()

    def _load_from_db(self):
        """从 DB 加载保存的人设"""
        try:
            from data.database import get_conn
            conn = get_conn()
            try:
                rows = conn.execute(
                    "SELECT value FROM settings WHERE key=?",
                    (PERSONA_DB_KEY,)
                ).fetchall()
                if rows:
                    data = json.loads(rows[0][0])
                    self._all_personas = data.get("personas", {})
                    current = data.get("current", "金探")
                    if current in self._all_personas:
                        self._current = self._all_personas[current]
                    else:
                        self._all_personas["金探"] = dict(DEFAULT_PERSONA)
                        self._current = dict(DEFAULT_PERSONA)
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[PersonaManager] load failed: {e}")
            self._all_personas = {"金探": dict(DEFAULT_PERSONA)}
            self._current = dict(DEFAULT_PERSONA)

    def _save_to_db(self):
        """持久化人设到 DB"""
        try:
            from data.database import get_conn
            conn = get_conn()
            try:
                current_name = self._current.get("name", "金探")
                data = json.dumps({"personas": self._all_personas, "current": current_name}, ensure_ascii=False)
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (PERSONA_DB_KEY, data)
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[PersonaManager] save failed: {e}")

    def get_current(self) -> dict:
        return dict(self._current)

    def get_list(self) -> list[dict]:
        return [{"name": p["name"], "role": p.get("role", "")[:50]} for p in self._all_personas.values()]

    def set_current(self, name: str) -> bool:
        if name in self._all_personas:
            self._current = dict(self._all_personas[name])
            self._save_to_db()
            return True
        return False

    def save_persona(self, persona: dict) -> None:
        name = persona.get("name", "自定义")
        self._all_personas[name] = persona
        self._current = persona
        self._save_to_db()
        logger.info(f"[PersonaManager] saved persona: {name}")

    def delete_persona(self, name: str) -> bool:
        if name == "金探":
            return False
        if name in self._all_personas:
            del self._all_personas[name]
            if self._current.get("name") == name:
                self._current = dict(DEFAULT_PERSONA)
                self._all_personas["金探"] = dict(DEFAULT_PERSONA)
            self._save_to_db()
            return True
        return False

    def build_system_prompt(self, context: str = "") -> str:
        """根据当前人设构建 system prompt"""
        p = self._current
        prompt = f"你是「{p.get('name', 'AI助手')}」，{p.get('role', '专业的交易分析师')}。\n\n"
        prompt += f"你的能力：\n{p.get('expertise', '')}\n\n"
        prompt += f"你的回答风格：\n{p.get('style', '')}\n\n"
        prompt += f"你的限制：\n{p.get('limits', '')}\n\n"
        if context:
            prompt += f"\n\n{context}"
        return prompt


_persona_mgr = PersonaManager()

def get_persona_manager() -> PersonaManager:
    return _persona_mgr