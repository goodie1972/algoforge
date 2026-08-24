"""
人设管理器 — Hermes Agent 模式：SOUL.md + MEMORY.md 双文件人设模型

- SOUL（基础设定）：身份/能力/风格/限制，占 system prompt 第 1 槽位
- MEMORY（日常记忆）：使用过程中的记忆沉淀，会话时冻结注入

存储：纯文件，位于 data/persona/ 目录：
- soul.md      基础设定（≤2000 字硬校验）
- memory.md    日常记忆（≤2000 字硬校验）
- legacy_persona.json  旧 DB 人设的一次性迁移备份（自动生成）
"""
import json
import logging
import os
import threading

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
MAX_PERSONA_CHARS = 2000

# data/ 目录与本模块同处项目根目录下（services/agent/persona_manager.py → ../../data）
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
_DATA_DIR = os.path.abspath(_DATA_DIR)
PERSONA_DIR = os.path.join(_DATA_DIR, "persona")
SOUL_PATH = os.path.join(PERSONA_DIR, "soul.md")
MEMORY_PATH = os.path.join(PERSONA_DIR, "memory.md")
LEGACY_BACKUP_PATH = os.path.join(PERSONA_DIR, "legacy_persona.json")


def _render_persona_template(p: dict) -> str:
    """把 name/role/expertise/style/limits 字段渲染为自然语言 soul 文本"""
    return (
        f"你是「{p.get('name', 'AI助手')}」，{p.get('role', '专业的交易分析师')}。\n"
        f"\n"
        f"你的能力：\n{p.get('expertise', '')}\n"
        f"\n"
        f"你的回答风格：\n{p.get('style', '')}\n"
        f"\n"
        f"你的限制：\n{p.get('limits', '')}"
    )


def _validate_limit(text: str, label: str) -> None:
    """字符数硬校验，超限抛 ValueError 并附当前字数"""
    n = len(text)
    if n > MAX_PERSONA_CHARS:
        raise ValueError(f"{label}超过 {MAX_PERSONA_CHARS} 字限制（当前 {n} 字）")


class PersonaManager:
    """soul.md + memory.md 双文件人设管理器（Hermes Agent 模式）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._migrated = False

    # ── 存储路径 ────────────────────────────────────────

    def _ensure_dir(self):
        os.makedirs(PERSONA_DIR, exist_ok=True)

    # ── Soul（基础设定）────────────────────────────────

    def load_soul(self) -> str:
        """读取 soul.md；文件不存在时执行懒迁移/默认初始化"""
        self._ensure_migration()
        with self._lock:
            with open(SOUL_PATH, "r", encoding="utf-8") as f:
                return f.read()

    def save_soul(self, text: str) -> None:
        """保存 soul.md（≤2000 字硬校验，超限抛 ValueError）"""
        _validate_limit(text, "人设")
        self._ensure_dir()
        with self._lock:
            with open(SOUL_PATH, "w", encoding="utf-8") as f:
                f.write(text)
            self._migrated = True
        logger.info(f"[PersonaManager] soul.md saved ({len(text)} chars)")

    # ── Memory（日常记忆）──────────────────────────────

    def load_memory(self) -> str:
        """读取 memory.md；文件不存在返回空串"""
        try:
            with open(MEMORY_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""
        except Exception as e:
            logger.warning(f"[PersonaManager] load memory failed: {e}")
            return ""

    def save_memory(self, text: str) -> None:
        """保存 memory.md（≤2000 字硬校验，超限抛 ValueError）"""
        _validate_limit(text, "日常记忆")
        self._ensure_dir()
        with self._lock:
            with open(MEMORY_PATH, "w", encoding="utf-8") as f:
                f.write(text)
        logger.info(f"[PersonaManager] memory.md saved ({len(text)} chars)")

    # ── 一次性懒迁移（幂等）─────────────────────────────

    def _ensure_migration(self):
        """首次加载时：若 soul.md 不存在，从 DB 旧人设迁移（或直接初始化默认值）"""
        if self._migrated or os.path.exists(SOUL_PATH):
            self._migrated = True
            return
        with self._lock:
            if os.path.exists(SOUL_PATH):
                self._migrated = True
                return
            self._ensure_dir()
            soul_text = None
            try:
                from data.database import get_metadata
                raw = get_metadata(PERSONA_DB_KEY)
                if raw:
                    data = json.loads(raw)
                    current_name = data.get("current", "")
                    persona = (data.get("personas") or {}).get(current_name) or {}
                    if persona:
                        # 备份原始 JSON
                        with open(LEGACY_BACKUP_PATH, "w", encoding="utf-8") as f:
                            f.write(raw)
                        soul_text = _render_persona_template(persona)
                        logger.info(f"[PersonaManager] migrated legacy persona '{current_name}' → soul.md")
            except Exception as e:
                logger.warning(f"[PersonaManager] legacy migration failed: {e}")
            if soul_text is None:
                soul_text = _render_persona_template(DEFAULT_PERSONA)
                logger.info("[PersonaManager] initialized soul.md with DEFAULT_PERSONA")
            with open(SOUL_PATH, "w", encoding="utf-8") as f:
                f.write(soul_text)
            self._migrated = True

    # ── System Prompt 组装（Hermes 式）──────────────────

    def build_system_prompt(self, context: str = "") -> str:
        """Hermes 式组装：[1] soul 全文 → [2] 长期记忆 → [3] 实时上下文（含技能摘要）

        双轨兼容：soul.md 读取失败/为空时回退 DEFAULT_PERSONA 字段模板，保证聊天不中断。
        技能摘要由 ai_service.build_system_prompt 层拼接进 context，此处保持兼容。
        """
        try:
            soul = self.load_soul().strip()
        except Exception as e:
            logger.warning(f"[PersonaManager] load soul failed, fallback to default template: {e}")
            soul = ""
        if not soul:
            soul = _render_persona_template(DEFAULT_PERSONA)

        prompt = soul

        memory = ""
        try:
            memory = self.load_memory().strip()
        except Exception:
            memory = ""
        if memory:
            prompt += f"\n\n【长期记忆】\n{memory}"

        if context:
            prompt += f"\n\n{context}"
        return prompt


_persona_mgr = PersonaManager()

def get_persona_manager() -> PersonaManager:
    return _persona_mgr
