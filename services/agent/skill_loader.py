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


class SkillLoader:
    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def scan(self, extra_dirs: list[str] = None) -> int:
        """扫描所有目录，加载 SKILL.md"""
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

    def _parse_skill(self, path: str) -> Optional[Skill]:
        """解析单 SKILL.md 文件"""
        try:
            content = open(path, encoding="utf-8").read()
        except Exception as e:
            logger.warning(f"[SkillLoader] read {path} failed: {e}")
            return None

        # 解析 YAML frontmatter
        name = os.path.splitext(os.path.basename(os.path.dirname(path)))[0]
        description = ""
        body = content

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                fm = parts[1]
                body = parts[2].strip()
                for line in fm.strip().split("\n"):
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("description:"):
                        description = line.split(":", 1)[1].strip().strip('"').strip("'")

        if not description:
            description = body.split("\n")[0][:100] if body else name

        return Skill(name=name, description=description, body=body, path=path)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list_skills(self) -> list[dict]:
        return [{"name": s.name, "description": s.description} for s in self._skills.values()]

    def get_all_context(self) -> str:
        """合并所有技能为上下文文本"""
        parts = []
        for s in self._skills.values():
            parts.append(s.to_context())
        return "\n\n".join(parts)


_loader = SkillLoader()

def get_loader() -> SkillLoader:
    return _loader