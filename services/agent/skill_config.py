"""技能配置管理 — 启用/禁用、本地自定义目录、商店安装记录的持久化"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class SkillConfig:
    """技能配置：{disabled_skills: [], custom_dirs: [], installed: []}"""

    def __init__(self):
        self._config_path = Path(__file__).parent.parent.parent / "data" / "skill_config.json"
        self._config = self._load()

    def _load(self) -> dict:
        """加载配置文件，不存在或损坏时返回默认值"""
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"disabled_skills": [], "custom_dirs": [], "installed": []}

    def _save(self) -> None:
        """持久化配置到磁盘"""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存技能配置失败: {e}")

    # ── 启用/禁用 ────────────────────────────────────────

    def is_enabled(self, name: str) -> bool:
        """判断技能是否启用（不在禁用列表中即为启用）"""
        return name not in self._config.get("disabled_skills", [])

    def set_enabled(self, name: str, enabled: bool) -> None:
        """设置技能启用/禁用并保存"""
        disabled = self._config.setdefault("disabled_skills", [])
        if enabled and name in disabled:
            disabled.remove(name)
        elif not enabled and name not in disabled:
            disabled.append(name)
        self._save()

    def get_disabled_list(self) -> list:
        """返回禁用技能列表"""
        return self._config.get("disabled_skills", [])

    # ── 本地自定义目录 ───────────────────────────────────

    def add_custom_dir(self, path: str) -> None:
        """注册本地技能目录（校验存在性；去重）"""
        path = os.path.normpath(os.path.abspath(path))
        if not os.path.isdir(path):
            raise ValueError(f"目录不存在：{path}")
        dirs = self._config.setdefault("custom_dirs", [])
        if path not in dirs:
            dirs.append(path)
            self._save()

    def remove_custom_dir(self, path: str) -> bool:
        """取消注册本地技能目录，返回是否移除成功"""
        path = os.path.normpath(os.path.abspath(path))
        dirs = self._config.setdefault("custom_dirs", [])
        if path in dirs:
            dirs.remove(path)
            self._save()
            return True
        return False

    def get_custom_dirs(self) -> list:
        """返回已注册的本地技能目录列表"""
        return list(self._config.get("custom_dirs", []))

    # ── 商店安装记录 ─────────────────────────────────────

    def get_installed(self) -> list:
        """返回已安装技能记录列表 [{name, source_platform, source_url, installed_at}]"""
        return list(self._config.get("installed", []))

    def add_installed(self, record: dict) -> None:
        """追加安装记录（同名覆盖）"""
        installed = self._config.setdefault("installed", [])
        installed[:] = [r for r in installed if r.get("name") != record.get("name")]
        installed.append(record)
        self._save()

    def remove_installed(self, name: str) -> bool:
        """删除安装记录，返回是否删除成功"""
        installed = self._config.setdefault("installed", [])
        before = len(installed)
        installed[:] = [r for r in installed if r.get("name") != name]
        if len(installed) != before:
            self._save()
            return True
        return False


# 全局单例
_config = None


def get_config() -> SkillConfig:
    global _config
    if _config is None:
        _config = SkillConfig()
    return _config
