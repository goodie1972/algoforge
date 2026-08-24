"""
人设文件化（SOUL.md + MEMORY.md）单元测试
覆盖 services/agent/persona_manager.py：
  - soul/memory 读写往返一致
  - 2000 字硬限制（恰好 2000 字可保存、2001 字抛 ValueError，含中文与 emoji 计数）
  - 懒迁移无损性（旧 ai_persona 数据 → soul.md + legacy_persona.json 备份）
  - 迁移幂等（二次加载不重复迁移）
  - 双轨回退（soul 被清空/损坏时 build_system_prompt 回退默认模板）
  - build_system_prompt 组装顺序（soul 首位 / 【长期记忆】按需出现）

隔离方式：所有路径常量（PERSONA_DIR/SOUL_PATH/MEMORY_PATH/LEGACY_BACKUP_PATH）
均为模块级常量且在方法调用时动态查找，用 monkeypatch 替换到临时目录；
旧人设数据源 data.database.get_metadata 用 sys.modules 注入假模块隔离，
绝不触碰真实 data/ 目录与真实数据库。
"""

import json
import os
import sys
import types

import pytest

# 确保项目根目录在 sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import services.agent.persona_manager as pm_mod
from services.agent.persona_manager import (
    DEFAULT_PERSONA,
    MAX_PERSONA_CHARS,
    PersonaManager,
    _render_persona_template,
)


@pytest.fixture
def persona_env(tmp_path, monkeypatch):
    """把人设存储路径全部切到临时目录，返回路径字典"""
    paths = {
        "dir": tmp_path,
        "soul": tmp_path / "soul.md",
        "memory": tmp_path / "memory.md",
        "backup": tmp_path / "legacy_persona.json",
    }
    monkeypatch.setattr(pm_mod, "PERSONA_DIR", str(paths["dir"]))
    monkeypatch.setattr(pm_mod, "SOUL_PATH", str(paths["soul"]))
    monkeypatch.setattr(pm_mod, "MEMORY_PATH", str(paths["memory"]))
    monkeypatch.setattr(pm_mod, "LEGACY_BACKUP_PATH", str(paths["backup"]))
    return paths


def _fake_db(monkeypatch, raw_value, call_log=None):
    """注入假的 data.database 模块，get_metadata 返回 raw_value（None 表示无旧数据）"""
    fake = types.ModuleType("data.database")

    def _get_metadata(key):
        if call_log is not None:
            call_log.append(key)
        return raw_value

    fake.get_metadata = _get_metadata
    monkeypatch.setitem(sys.modules, "data.database", fake)
    return fake


# ════════════════════════════════════════════════════════════
# 1. soul / memory 读写往返一致
# ════════════════════════════════════════════════════════════

class TestReadWriteRoundTrip:

    def test_soul_roundtrip(self, persona_env):
        """save_soul → load_soul 往返一致（含中文/换行）"""
        pm = PersonaManager()
        pm._migrated = True  # 跳过迁移，直接测读写
        text = "你是「金探」，测试人设。\n风格：简洁专业。"
        pm.save_soul(text)
        assert pm.load_soul() == text
        assert persona_env["soul"].exists()

    def test_memory_roundtrip(self, persona_env):
        """save_memory → load_memory 往返一致"""
        pm = PersonaManager()
        text = "用户偏好 H1 周期，关注非农数据。📊"
        pm.save_memory(text)
        assert pm.load_memory() == text
        assert persona_env["memory"].exists()

    def test_load_memory_missing_file_returns_empty(self, persona_env):
        """memory.md 不存在时 load_memory 返回空串不报错"""
        pm = PersonaManager()
        assert pm.load_memory() == ""


# ════════════════════════════════════════════════════════════
# 2. 2000 字硬限制
# ════════════════════════════════════════════════════════════

class TestCharLimit:

    def test_soul_exactly_2000_ok(self, persona_env):
        """恰好 2000 字可保存"""
        pm = PersonaManager()
        pm._migrated = True
        text = "金" * 2000
        pm.save_soul(text)
        assert pm.load_soul() == text
        assert MAX_PERSONA_CHARS == 2000

    def test_soul_2001_raises(self, persona_env):
        """2001 字抛 ValueError，消息含当前字数"""
        pm = PersonaManager()
        pm._migrated = True
        with pytest.raises(ValueError) as ei:
            pm.save_soul("金" * 2001)
        assert "2001" in str(ei.value)

    def test_memory_exactly_2000_ok(self, persona_env):
        """memory 恰好 2000 字可保存"""
        pm = PersonaManager()
        text = "记" * 2000
        pm.save_memory(text)
        assert pm.load_memory() == text

    def test_memory_2001_raises(self, persona_env):
        """memory 2001 字抛 ValueError"""
        pm = PersonaManager()
        with pytest.raises(ValueError) as ei:
            pm.save_memory("忆" * 2001)
        assert "2001" in str(ei.value)

    def test_chinese_emoji_count_exactly_2000(self, persona_env):
        """中文 + emoji 混合计数：1998 中文 + 2 个 emoji = 2000 字，可保存"""
        pm = PersonaManager()
        pm._migrated = True
        text = "金" * 1998 + "😀🎯"
        assert len(text) == 2000  # emoji 按码点计 1 字
        pm.save_soul(text)
        assert pm.load_soul() == text

    def test_chinese_emoji_count_2001_raises(self, persona_env):
        """中文 + emoji 混合计数：1998 中文 + 3 个 emoji = 2001 字，抛错且消息含 2001"""
        pm = PersonaManager()
        pm._migrated = True
        text = "金" * 1998 + "😀🎯📈"
        assert len(text) == 2001
        with pytest.raises(ValueError) as ei:
            pm.save_soul(text)
        assert "2001" in str(ei.value)

    def test_over_limit_not_written(self, persona_env):
        """超限保存失败时不应覆盖已有内容"""
        pm = PersonaManager()
        pm._migrated = True
        pm.save_soul("原始内容")
        with pytest.raises(ValueError):
            pm.save_soul("超" * 2001)
        assert pm.load_soul() == "原始内容"


# ════════════════════════════════════════════════════════════
# 3. 懒迁移无损性 + 幂等
# ════════════════════════════════════════════════════════════

class TestLazyMigration:

    LEGACY_PERSONA = {
        "name": "老金",
        "role": "旧版交易分析师",
        "style": "旧版风格：犀利直接",
        "expertise": "旧版专长：流动性猎取",
        "limits": "旧版限制：不给精确点位",
    }

    def _legacy_raw(self):
        return json.dumps(
            {"current": "p1", "personas": {"p1": self.LEGACY_PERSONA}},
            ensure_ascii=False,
        )

    def test_migration_lossless(self, persona_env, monkeypatch):
        """旧 ai_persona 迁移：soul.md 包含全部字段信息，备份内容与原数据一致"""
        raw = self._legacy_raw()
        _fake_db(monkeypatch, raw)

        pm = PersonaManager()  # 全新实例，_migrated=False
        soul = pm.load_soul()

        # soul.md 包含各字段信息
        for value in self.LEGACY_PERSONA.values():
            assert value in soul, f"soul.md 应包含旧人设字段值: {value}"

        # 备份存在且内容与原数据一致
        assert persona_env["backup"].exists(), "legacy_persona.json 备份应存在"
        backup_text = persona_env["backup"].read_text(encoding="utf-8")
        assert backup_text == raw
        assert json.loads(backup_text) == json.loads(raw)

    def test_migration_idempotent(self, persona_env, monkeypatch):
        """迁移幂等：二次加载不重复迁移，内容不变，get_metadata 只调用一次"""
        raw = self._legacy_raw()
        call_log = []
        _fake_db(monkeypatch, raw, call_log=call_log)

        pm = PersonaManager()
        first = pm.load_soul()
        backup_first = persona_env["backup"].read_text(encoding="utf-8")

        second = pm.load_soul()
        assert second == first, "二次加载内容应不变"
        assert persona_env["backup"].read_text(encoding="utf-8") == backup_first
        assert len(call_log) == 1, f"get_metadata 应只调用一次，实际 {len(call_log)} 次"

        # 新实例二次加载（模拟进程重启）：soul.md 已存在则不再读 DB
        pm2 = PersonaManager()
        third = pm2.load_soul()
        assert third == first
        assert len(call_log) == 1, "soul.md 已存在时不应再读取旧数据源"

    def test_migration_no_legacy_data_defaults(self, persona_env, monkeypatch):
        """无旧数据时初始化默认人设，不产生备份文件"""
        _fake_db(monkeypatch, None)
        pm = PersonaManager()
        soul = pm.load_soul()
        assert soul == _render_persona_template(DEFAULT_PERSONA)
        assert DEFAULT_PERSONA["name"] in soul
        assert not persona_env["backup"].exists()

    def test_migration_db_error_falls_back(self, persona_env, monkeypatch):
        """旧数据源内容损坏时回退默认人设，不中断"""
        _fake_db(monkeypatch, "{不是合法 JSON")
        pm = PersonaManager()
        soul = pm.load_soul()
        assert DEFAULT_PERSONA["name"] in soul


# ════════════════════════════════════════════════════════════
# 4. 双轨回退：soul 被清空/损坏时 build_system_prompt 不抛错
# ════════════════════════════════════════════════════════════

class TestDualTrackFallback:

    def test_empty_soul_fallback(self, persona_env):
        """soul.md 被清空 → 回退默认模板"""
        persona_env["dir"].mkdir(parents=True, exist_ok=True)
        persona_env["soul"].write_text("", encoding="utf-8")
        pm = PersonaManager()
        pm._migrated = True
        prompt = pm.build_system_prompt()
        assert prompt == _render_persona_template(DEFAULT_PERSONA)
        assert DEFAULT_PERSONA["name"] in prompt

    def test_corrupted_soul_fallback(self, persona_env):
        """soul.md 内容损坏（非法 UTF-8）→ 回退默认模板不抛错"""
        persona_env["dir"].mkdir(parents=True, exist_ok=True)
        persona_env["soul"].write_bytes(b"\xff\xfe\x00\x81broken")
        pm = PersonaManager()
        pm._migrated = True
        prompt = pm.build_system_prompt()
        assert DEFAULT_PERSONA["name"] in prompt
        assert len(prompt) > 0


# ════════════════════════════════════════════════════════════
# 5. build_system_prompt 组装顺序
# ════════════════════════════════════════════════════════════

class TestBuildSystemPrompt:

    def test_soul_at_first_position(self, persona_env):
        """soul 全文在 prompt 首位"""
        pm = PersonaManager()
        pm._migrated = True
        pm.save_soul("灵魂开头：我是金探。")
        pm.save_memory("记忆内容。")
        prompt = pm.build_system_prompt(context="实时上下文")
        assert prompt.startswith("灵魂开头：我是金探。")

    def test_memory_section_appears_when_nonempty(self, persona_env):
        """memory 非空时出现【长期记忆】段，且位于 soul 之后"""
        pm = PersonaManager()
        pm._migrated = True
        pm.save_soul("人设正文")
        pm.save_memory("用户喜欢简洁回答。")
        prompt = pm.build_system_prompt()
        assert "【长期记忆】" in prompt
        assert prompt.index("人设正文") < prompt.index("【长期记忆】")
        assert "用户喜欢简洁回答。" in prompt

    def test_memory_section_absent_when_empty(self, persona_env):
        """memory 为空时不出现【长期记忆】段"""
        pm = PersonaManager()
        pm._migrated = True
        pm.save_soul("人设正文")
        # 不写 memory（文件不存在）
        prompt = pm.build_system_prompt()
        assert "【长期记忆】" not in prompt

    def test_memory_whitespace_only_treated_empty(self, persona_env):
        """memory 仅空白字符时视同为空，不出现【长期记忆】段"""
        pm = PersonaManager()
        pm._migrated = True
        pm.save_soul("人设正文")
        pm.save_memory("   \n  ")
        prompt = pm.build_system_prompt()
        assert "【长期记忆】" not in prompt

    def test_context_appended_at_end(self, persona_env):
        """context 追加在末尾（顺序：soul → 长期记忆 → context）"""
        pm = PersonaManager()
        pm._migrated = True
        pm.save_soul("SOUL")
        pm.save_memory("MEM")
        prompt = pm.build_system_prompt(context="CTX")
        assert prompt.index("SOUL") < prompt.index("MEM") < prompt.index("CTX")
