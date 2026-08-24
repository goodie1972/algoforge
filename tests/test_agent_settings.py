"""
Agent 设置管理单元测试
覆盖 services/agent/agent_settings.py：
  - 默认值与缺字段补齐
  - update 往返持久化
  - 未知键过滤
  - 损坏文件回退默认值（不抛异常）
  - mask_key 各分支
  - smithery_api_key 清除语义

隔离方式：SETTINGS_FILE 为模块级常量且在函数调用时动态查找，
用 monkeypatch 替换到临时文件，绝不触碰真实 data/agent_settings.json。
"""

import json
import os
import sys

import pytest

# 确保项目根目录在 sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import services.agent.agent_settings as settings_mod
from services.agent.agent_settings import (
    DEFAULT_SETTINGS,
    get_all,
    get_setting,
    mask_key,
    update,
)


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """把 SETTINGS_FILE 切到临时文件，返回文件路径"""
    cfg = tmp_path / "agent_settings.json"
    monkeypatch.setattr(settings_mod, "SETTINGS_FILE", str(cfg))
    return cfg


# ════════════════════════════════════════════════════════════
# 1. 默认值
# ════════════════════════════════════════════════════════════

class TestDefaults:

    def test_defaults_when_file_missing(self, settings_file):
        """文件不存在时返回完整默认值"""
        assert get_all() == {
            "tools_enabled": True,
            "memory_auto_accumulate": True,
            "smithery_api_key": "",
        }

    def test_default_settings_constant(self):
        """DEFAULT_SETTINGS 常量与需求一致"""
        assert DEFAULT_SETTINGS["tools_enabled"] is True
        assert DEFAULT_SETTINGS["memory_auto_accumulate"] is True
        assert DEFAULT_SETTINGS["smithery_api_key"] == ""

    def test_missing_fields_filled_with_defaults(self, settings_file):
        """文件只含部分字段时，缺字段补默认值"""
        settings_file.write_text(json.dumps({"tools_enabled": False}), encoding="utf-8")
        merged = get_all()
        assert merged["tools_enabled"] is False
        assert merged["memory_auto_accumulate"] is True
        assert merged["smithery_api_key"] == ""

    def test_get_setting_known_and_unknown(self, settings_file):
        """get_setting：已知键返回值，未知键返回 default"""
        assert get_setting("tools_enabled") is True
        assert get_setting("no_such_key") is None
        assert get_setting("no_such_key", "fallback") == "fallback"


# ════════════════════════════════════════════════════════════
# 2. update 往返持久化
# ════════════════════════════════════════════════════════════

class TestUpdateRoundTrip:

    def test_update_persists_and_reads_back(self, settings_file):
        """update 后内存可读回，且磁盘文件确实写入"""
        update({"tools_enabled": False})
        assert get_setting("tools_enabled") is False
        on_disk = json.loads(settings_file.read_text(encoding="utf-8"))
        assert on_disk["tools_enabled"] is False
        # 未更新字段保留默认值
        assert on_disk["memory_auto_accumulate"] is True

    def test_update_merges_not_replaces(self, settings_file):
        """多次 update 是合并而非整体替换"""
        update({"tools_enabled": False})
        update({"smithery_api_key": "sk-abc123"})
        merged = get_all()
        assert merged["tools_enabled"] is False
        assert merged["smithery_api_key"] == "sk-abc123"
        assert merged["memory_auto_accumulate"] is True

    def test_update_returns_merged_settings(self, settings_file):
        """update 返回更新后的全部设置（含默认补齐）"""
        result = update({"memory_auto_accumulate": False})
        assert result["memory_auto_accumulate"] is False
        assert result["tools_enabled"] is True
        assert result["smithery_api_key"] == ""


# ════════════════════════════════════════════════════════════
# 3. 未知键过滤
# ════════════════════════════════════════════════════════════

class TestUnknownKeyFilter:

    def test_unknown_keys_not_persisted(self, settings_file):
        """update 中的未知键被过滤，不落盘"""
        update({"tools_enabled": False, "hacker_key": "evil", "another": 1})
        on_disk = json.loads(settings_file.read_text(encoding="utf-8"))
        assert "hacker_key" not in on_disk
        assert "another" not in on_disk
        assert on_disk["tools_enabled"] is False

    def test_unknown_keys_not_returned(self, settings_file):
        """get_all 不返回未知键（即使文件中被手工写入）"""
        settings_file.write_text(
            json.dumps({"tools_enabled": True, "ghost": "boo"}), encoding="utf-8")
        assert "ghost" not in get_all()


# ════════════════════════════════════════════════════════════
# 4. 损坏文件回退
# ════════════════════════════════════════════════════════════

class TestCorruptedFile:

    def test_corrupted_json_falls_back_to_defaults(self, settings_file):
        """非法 JSON → 回退默认值，不抛异常"""
        settings_file.write_text("{这不是合法 JSON", encoding="utf-8")
        assert get_all() == DEFAULT_SETTINGS

    def test_non_object_json_falls_back(self, settings_file):
        """JSON 不是对象（如数组）→ 回退默认值"""
        settings_file.write_text("[1, 2, 3]", encoding="utf-8")
        assert get_all() == DEFAULT_SETTINGS

    def test_corrupted_file_update_recovers(self, settings_file):
        """损坏文件上执行 update → 重建为合法配置"""
        settings_file.write_text("garbage", encoding="utf-8")
        update({"tools_enabled": False})
        on_disk = json.loads(settings_file.read_text(encoding="utf-8"))
        assert on_disk["tools_enabled"] is False
        assert on_disk["memory_auto_accumulate"] is True


# ════════════════════════════════════════════════════════════
# 5. mask_key 各分支
# ════════════════════════════════════════════════════════════

class TestMaskKey:

    def test_empty_key(self):
        assert mask_key("") == ""

    def test_none_key(self):
        assert mask_key(None) == ""

    def test_short_key_fully_masked(self):
        """≤8 位全掩"""
        assert mask_key("abc") == "***"
        assert mask_key("12345678") == "********"

    def test_long_key_first4_last2(self):
        """>8 位：首 4 尾 2，中间 ****"""
        assert mask_key("sk-abcdefghij") == "sk-a****ij"
        assert mask_key("123456789") == "1234****89"


# ════════════════════════════════════════════════════════════
# 6. smithery_api_key 清除语义
# ════════════════════════════════════════════════════════════

class TestSmitheryKeySemantics:

    def test_set_then_clear(self, settings_file):
        """先写入再清空：清空后读到空串"""
        update({"smithery_api_key": "sk-real-key-123"})
        assert get_setting("smithery_api_key") == "sk-real-key-123"
        update({"smithery_api_key": ""})
        assert get_setting("smithery_api_key") == ""
        on_disk = json.loads(settings_file.read_text(encoding="utf-8"))
        assert on_disk["smithery_api_key"] == ""

    def test_update_without_key_keeps_existing(self, settings_file):
        """不传 smithery_api_key 的 update 不影响已存的 key"""
        update({"smithery_api_key": "sk-keep-me"})
        update({"tools_enabled": False})
        assert get_setting("smithery_api_key") == "sk-keep-me"


# ════════════════════════════════════════════════════════════
# 7. Smithery Key 环境变量优先级（mcp_marketplace._smithery_key）
# ════════════════════════════════════════════════════════════

class TestSmitheryKeyPriority:

    def test_env_overrides_settings_file(self, settings_file, monkeypatch):
        """环境变量优先：SMITHERY_API_KEY 覆盖设置文件持久化值"""
        import services.agent.mcp_marketplace as mp_mod
        settings_file.write_text(
            json.dumps({"smithery_api_key": "sk-from-file"}), encoding="utf-8")
        monkeypatch.setenv("SMITHERY_API_KEY", "sk-from-env")
        assert mp_mod._smithery_key() == "sk-from-env"

    def test_falls_back_to_settings_file_without_env(self, settings_file, monkeypatch):
        """无环境变量时回退设置文件持久化值"""
        import services.agent.mcp_marketplace as mp_mod
        settings_file.write_text(
            json.dumps({"smithery_api_key": "sk-from-file"}), encoding="utf-8")
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        assert mp_mod._smithery_key() == "sk-from-file"
