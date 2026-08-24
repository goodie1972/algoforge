"""
Skill 加载器 — 扫描 skills/ 目录，解析 SKILL.md
格式与 skillhub 生态兼容: YAML frontmatter + body
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SKILL_DIRS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "skills"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills"),
]


class Skill:
    def __init__(self, name: str, description: str, body: str, path: str = ""):
        self.name = name
        self.description = description
        self.body = body
        self.path = path

    def to_context(self) -> str:
        return f"[技能: {self.name}] {self.description}\n{self.body}"


def parse_skill_text(content: str, fallback_name: str = "") -> Optional[dict]:
    """解析 SKILL.md 文本（YAML frontmatter + body），返回 {name, description, body}

    与 SkillLoader._parse_skill 同一套解析逻辑，供技能商店/本地导入校验复用。
    无 frontmatter 且无 fallback_name 时返回 None。
    """
    name = fallback_name
    description = ""
    body = content
    has_frontmatter = False

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm = parts[1]
            body = parts[2].strip()
            has_frontmatter = True
            for line in fm.strip().split("\n"):
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"').strip("'")

    if not has_frontmatter and not name:
        return None

    if not description:
        description = body.split("\n")[0][:100] if body else name

    return {"name": name, "description": description, "body": body}


class SkillLoader:
    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def scan(self, extra_dirs: list[str] = None) -> int:
        """扫描所有目录，加载 SKILL.md（每次扫描前清空缓存，保证热重扫正确）"""
        self._skills.clear()
        dirs = list(SKILL_DIRS)
        if extra_dirs:
            dirs.extend(extra_dirs)

        count = 0
        for d in dirs:
            if not os.path.isdir(d):
                continue
            for root, dirs_inner, files in os.walk(d):
                for f in files:
                    if f.lower() == "skill.md" or f.endswith(".skill.md"):
                        path = os.path.join(root, f)
                        skill = self._parse_skill(path)
                        if skill:
                            self._skills[skill.name] = skill
                            count += 1
        logger.info(f"[SkillLoader] loaded {count} skills from {len(dirs)} dirs")
        return count

    def rescan(self) -> int:
        """重新扫描内置目录 + 已注册的自定义目录（热刷新统一入口）"""
        extra: list[str] = []
        try:
            from services.agent.skill_config import get_config
            extra = [d for d in get_config().get_custom_dirs() if os.path.isdir(d)]
        except Exception:
            pass
        return self.scan(extra_dirs=extra)

    def _parse_skill(self, path: str) -> Optional[Skill]:
        """解析单 SKILL.md 文件"""
        try:
            content = open(path, encoding="utf-8").read()
        except Exception as e:
            logger.warning(f"[SkillLoader] read {path} failed: {e}")
            return None

        fallback_name = os.path.splitext(os.path.basename(os.path.dirname(path)))[0]
        parsed = parse_skill_text(content, fallback_name=fallback_name)
        if not parsed:
            return None
        return Skill(name=parsed["name"], description=parsed["description"],
                     body=parsed["body"], path=path)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def _get_skill_config(self):
        """安全获取技能配置（不可用时返回 None，不影响原有逻辑）"""
        try:
            from services.agent.skill_config import get_config
            return get_config()
        except Exception:
            return None

    def list_skills(self) -> list[dict]:
        config = self._get_skill_config()
        return [{"name": s.name, "description": s.description}
                for s in self._skills.values()
                if not config or config.is_enabled(s.name)]

    def all_skills(self) -> list[Skill]:
        """返回全部已加载技能（含被禁用的）"""
        return list(self._skills.values())

    def get_all_context(self) -> str:
        """合并所有技能为上下文文本（跳过被禁用的技能）"""
        config = self._get_skill_config()
        parts = []
        for s in self._skills.values():
            if config and not config.is_enabled(s.name):
                continue
            parts.append(s.to_context())
        return "\n\n".join(parts)

    def get_summary_context(self) -> str:
        """返回技能摘要（名称+一句话描述），而非完整内容，节省 token"""
        if not self._skills:
            self.rescan()
        config = self._get_skill_config()
        parts = []
        for s in self._skills.values():
            if config and not config.is_enabled(s.name):
                continue
            desc = s.description or ""
            first_line = desc.split("\n")[0].strip()[:80] if desc else ""
            parts.append(f"- {s.name}: {first_line}")
        return "可用技能:\n" + "\n".join(parts) if parts else "无可用技能"


_loader = SkillLoader()

def get_loader() -> SkillLoader:
    return _loader
