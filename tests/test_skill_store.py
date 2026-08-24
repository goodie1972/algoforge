"""
技能商店 / 本地技能接入单元测试
覆盖 services/agent/skill_marketplace.py + services/agent/skill_config.py：
  - install_skill：合法 SKILL.md 安装成功、落盘、默认禁用、安装记录存在
  - 校验拒绝：超 200KB / 无 frontmatter / frontmatter 无 name
  - uninstall_skill：imported 技能可卸载且记录清理；内置技能拒绝卸载
  - SkillConfig：add_custom_dir 存在性校验、installed 记录增删往返

隔离方式：
  - skill_marketplace.IMPORTED_ROOT 为模块级常量（调用时动态查找）→ monkeypatch 到临时目录
  - skill_config.get_config 返回模块级单例 _config → monkeypatch 替换为指向临时文件的实例
  绝不触碰真实 skills/imported/ 与 data/skill_config.json。
"""

import json
import os
import sys

import pytest

# 确保项目根目录在 sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import services.agent.skill_marketplace as sm_mod
import services.agent.skill_config as sc_mod
from services.agent.skill_config import SkillConfig


def _make_config(tmp_path):
    """构造指向临时文件的 SkillConfig 实例（绕过 __init__ 中的真实路径）"""
    cfg = SkillConfig.__new__(SkillConfig)
    cfg._config_path = tmp_path / "skill_config.json"
    cfg._config = cfg._load()
    return cfg


@pytest.fixture
def skill_env(tmp_path, monkeypatch):
    """隔离技能落盘目录与技能配置文件"""
    imported_root = tmp_path / "imported"
    imported_root.mkdir()
    monkeypatch.setattr(sm_mod, "IMPORTED_ROOT", str(imported_root))
    cfg = _make_config(tmp_path)
    monkeypatch.setattr(sc_mod, "_config", cfg)
    return {"tmp": tmp_path, "imported_root": imported_root, "config": cfg}


def _skill_md(name="test_skill", description="测试技能描述", body="# 测试技能\n技能正文。"):
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"


# ════════════════════════════════════════════════════════════
# 1. install_skill
# ════════════════════════════════════════════════════════════

class TestInstallSkill:

    def test_install_success(self, skill_env):
        """合法 SKILL.md 安装成功：落盘 + 默认禁用 + 安装记录存在"""
        result = sm_mod.install_skill(
            "", _skill_md(), source="https://example.com/x", source_platform="paste")
        assert result["ok"] is True
        assert result["name"] == "test_skill"
        assert result["enabled"] is False  # 默认禁用

        # 落盘到隔离的 imported 目录
        skill_file = skill_env["imported_root"] / "test_skill" / "SKILL.md"
        assert skill_file.exists()
        assert "name: test_skill" in skill_file.read_text(encoding="utf-8")

        # 默认进禁用列表
        cfg = skill_env["config"]
        assert cfg.is_enabled("test_skill") is False
        assert "test_skill" in cfg.get_disabled_list()

        # 安装记录存在
        records = cfg.get_installed()
        assert len(records) == 1
        assert records[0]["name"] == "test_skill"
        assert records[0]["source_platform"] == "paste"
        assert records[0]["source_url"] == "https://example.com/x"

    def test_install_uses_frontmatter_name_when_name_empty(self, skill_env):
        """name 为空时以 frontmatter 解析结果为准"""
        result = sm_mod.install_skill("", _skill_md(name="fm_name"))
        assert result["name"] == "fm_name"

    def test_install_duplicate_rejected(self, skill_env):
        """同名技能重复安装被拒"""
        sm_mod.install_skill("", _skill_md())
        with pytest.raises(sm_mod.MarketplaceError) as ei:
            sm_mod.install_skill("", _skill_md())
        assert "已安装" in str(ei.value)

    def test_install_over_200kb_rejected(self, skill_env):
        """超 200KB 内容被拒"""
        big = "---\nname: big\ndescription: x\n---\n" + "a" * (200 * 1024 + 1)
        with pytest.raises(sm_mod.MarketplaceError) as ei:
            sm_mod.install_skill("", big)
        assert "200KB" in str(ei.value)
        assert not (skill_env["imported_root"] / "big").exists()

    def test_install_no_frontmatter_rejected(self, skill_env):
        """无 frontmatter 的内容被拒"""
        with pytest.raises(sm_mod.MarketplaceError) as ei:
            sm_mod.install_skill("", "这只是普通文本，没有 frontmatter")
        assert "frontmatter" in str(ei.value)

    def test_install_frontmatter_without_name_rejected(self, skill_env):
        """frontmatter 无 name 字段被拒"""
        content = "---\ndescription: 只有描述\n---\n\n正文\n"
        with pytest.raises(sm_mod.MarketplaceError) as ei:
            sm_mod.install_skill("", content)
        assert "name" in str(ei.value)

    def test_install_empty_content_rejected(self, skill_env):
        """空内容被拒"""
        with pytest.raises(sm_mod.MarketplaceError):
            sm_mod.install_skill("", "   ")

    def test_install_invalid_name_rejected(self, skill_env):
        """非法技能名（含空格/中文）被拒"""
        with pytest.raises(sm_mod.MarketplaceError) as ei:
            sm_mod.install_skill("bad name!", _skill_md())
        assert "不合法" in str(ei.value)


# ════════════════════════════════════════════════════════════
# 2. uninstall_skill
# ════════════════════════════════════════════════════════════

class TestUninstallSkill:

    def test_uninstall_imported_skill(self, skill_env):
        """imported 技能卸载：目录删除 + 安装记录清理 + 禁用列表清理"""
        sm_mod.install_skill("", _skill_md())
        cfg = skill_env["config"]
        assert "test_skill" in cfg.get_disabled_list()

        result = sm_mod.uninstall_skill("test_skill")
        assert result["ok"] is True

        assert not (skill_env["imported_root"] / "test_skill").exists()
        assert cfg.get_installed() == []
        assert "test_skill" not in cfg.get_disabled_list()

    def test_uninstall_builtin_rejected(self, skill_env):
        """内置技能（market_analysis）卸载被拒"""
        with pytest.raises(sm_mod.MarketplaceError) as ei:
            sm_mod.uninstall_skill("market_analysis")
        assert "内置技能" in str(ei.value)

    def test_uninstall_nonexistent_rejected(self, skill_env):
        """未安装的技能卸载被拒"""
        with pytest.raises(sm_mod.MarketplaceError) as ei:
            sm_mod.uninstall_skill("ghost_skill")
        assert "未找到" in str(ei.value)

    def test_uninstall_empty_name_rejected(self, skill_env):
        """空技能名被拒"""
        with pytest.raises(sm_mod.MarketplaceError):
            sm_mod.uninstall_skill("  ")

    def test_uninstall_path_traversal_rejected(self, skill_env):
        """路径穿越类非法技能名被拒"""
        with pytest.raises(sm_mod.MarketplaceError):
            sm_mod.uninstall_skill("../../evil")


# ════════════════════════════════════════════════════════════
# 3. SkillConfig
# ════════════════════════════════════════════════════════════

class TestSkillConfig:

    def test_add_custom_dir_rejects_nonexistent(self, skill_env):
        """add_custom_dir：不存在的路径拒绝（抛 ValueError）"""
        cfg = skill_env["config"]
        fake_dir = str(skill_env["tmp"] / "not_exist_dir")
        with pytest.raises(ValueError) as ei:
            cfg.add_custom_dir(fake_dir)
        assert "不存在" in str(ei.value)
        assert cfg.get_custom_dirs() == []

    def test_add_custom_dir_roundtrip_and_dedup(self, skill_env):
        """add_custom_dir：存在的目录注册成功、去重、可移除"""
        cfg = skill_env["config"]
        d = skill_env["tmp"] / "my_skills"
        d.mkdir()
        cfg.add_custom_dir(str(d))
        cfg.add_custom_dir(str(d))  # 重复注册应去重
        dirs = cfg.get_custom_dirs()
        assert len(dirs) == 1
        assert dirs[0] == os.path.normpath(os.path.abspath(str(d)))

        assert cfg.remove_custom_dir(str(d)) is True
        assert cfg.get_custom_dirs() == []
        assert cfg.remove_custom_dir(str(d)) is False  # 已移除，再次移除返回 False

    def test_installed_records_roundtrip(self, skill_env):
        """get_installed/add_installed/remove_installed 往返"""
        cfg = skill_env["config"]
        assert cfg.get_installed() == []

        cfg.add_installed({"name": "alpha", "source_platform": "paste",
                           "source_url": "", "installed_at": "2026-08-23T00:00:00"})
        cfg.add_installed({"name": "beta", "source_platform": "skillsh",
                           "source_url": "u", "installed_at": "2026-08-23T00:00:01"})
        names = [r["name"] for r in cfg.get_installed()]
        assert names == ["alpha", "beta"]

        # 同名记录覆盖而非追加
        cfg.add_installed({"name": "alpha", "source_platform": "skillsmp",
                           "source_url": "u2", "installed_at": "2026-08-23T00:00:02"})
        records = cfg.get_installed()
        assert len(records) == 2
        alpha = next(r for r in records if r["name"] == "alpha")
        assert alpha["source_platform"] == "skillsmp"

        assert cfg.remove_installed("alpha") is True
        assert [r["name"] for r in cfg.get_installed()] == ["beta"]
        assert cfg.remove_installed("alpha") is False  # 已删除

    def test_config_persists_to_disk(self, skill_env):
        """配置变更持久化到临时文件，新实例可加载"""
        cfg = skill_env["config"]
        cfg.set_enabled("some_skill", False)
        cfg.add_installed({"name": "some_skill", "source_platform": "paste",
                           "source_url": "", "installed_at": ""})

        cfg_path = skill_env["tmp"] / "skill_config.json"
        assert cfg_path.exists()
        saved = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert "some_skill" in saved["disabled_skills"]
        assert saved["installed"][0]["name"] == "some_skill"

        # 新实例从同一文件加载（同样绕过真实路径）
        cfg2 = SkillConfig.__new__(SkillConfig)
        cfg2._config_path = cfg_path
        cfg2._config = cfg2._load()
        assert cfg2.is_enabled("some_skill") is False
        assert cfg2.get_installed()[0]["name"] == "some_skill"

    def test_corrupted_config_file_falls_back_defaults(self, skill_env):
        """配置文件损坏时回退默认值不报错"""
        cfg_path = skill_env["tmp"] / "skill_config.json"
        cfg_path.write_text("{损坏的 JSON", encoding="utf-8")
        cfg = SkillConfig.__new__(SkillConfig)
        cfg._config_path = cfg_path
        cfg._config = cfg._load()
        assert cfg.get_disabled_list() == []
        assert cfg.get_custom_dirs() == []
        assert cfg.get_installed() == []

    def test_set_enabled_toggle(self, skill_env):
        """set_enabled 启用/禁用切换"""
        cfg = skill_env["config"]
        assert cfg.is_enabled("x") is True  # 默认启用
        cfg.set_enabled("x", False)
        assert cfg.is_enabled("x") is False
        cfg.set_enabled("x", False)  # 重复禁用不重复入列
        assert cfg.get_disabled_list().count("x") == 1
        cfg.set_enabled("x", True)
        assert cfg.is_enabled("x") is True
