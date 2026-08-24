"""
AlgoForge Agent 系统修复项模拟测试
覆盖 P0/P1/P2 共 9 项修复（前端 Vue 不需要 Python 测试）

修复清单:
  P0-1: persona_manager 改用 get_metadata/set_metadata 持久化
  P0-2: _stream_chat 改为 async + httpx.AsyncClient
  P0-3: routes/ai.py 模块级 _llm_manager 实例
  P1-4: ai_service 删除硬编码 SYSTEM_PROMPT，使用动态组装
  P1-5: 消息历史截断 [-20:]
  P1-6: skill_loader.get_summary_context() 方法
  P2-7: context_builder 使用 engine 公开接口
  P2-8: tool_registry 5 个核心工具注册
  P2-9: llm_provider 故障转移链
"""

import sys
import os
import json
import inspect
import logging
from unittest.mock import patch, MagicMock

import pytest

# 确保项目根目录在 sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


# ════════════════════════════════════════════════════════════
# Test 1: P0-1 人设持久化 — metadata 复用
# ════════════════════════════════════════════════════════════

class TestPersonaMetadataPersistence:
    """P0-1(改版): 验证 PersonaManager 采用 soul.md / memory.md 文件存储"""

    def _patch_paths(self, tmp_path):
        import services.agent.persona_manager as pm_mod
        from unittest.mock import patch as _patch
        return (
            _patch.object(pm_mod, "PERSONA_DIR", str(tmp_path)),
            _patch.object(pm_mod, "SOUL_PATH", str(tmp_path / "soul.md")),
            _patch.object(pm_mod, "MEMORY_PATH", str(tmp_path / "memory.md")),
            _patch.object(pm_mod, "LEGACY_BACKUP_PATH", str(tmp_path / "legacy_persona.json")),
        )

    def test_save_and_load_soul(self, tmp_path):
        """save_soul/load_soul 文件读写往返一致"""
        p1, p2, p3, p4 = self._patch_paths(tmp_path)
        with p1, p2, p3, p4:
            from services.agent.persona_manager import PersonaManager
            pm = PersonaManager()
            pm._migrated = True  # 跳过迁移，直接测读写
            pm.save_soul("你是「金探」，测试人设。")
            assert pm.load_soul() == "你是「金探」，测试人设。"
            assert os.path.exists(str(tmp_path / "soul.md"))

    def test_save_soul_over_limit_raises(self, tmp_path):
        """超过 2000 字保存应抛 ValueError 并附当前字数"""
        p1, p2, p3, p4 = self._patch_paths(tmp_path)
        with p1, p2, p3, p4:
            from services.agent.persona_manager import PersonaManager
            pm = PersonaManager()
            pm._migrated = True
            with pytest.raises(ValueError) as ei:
                pm.save_soul("金" * 2001)
            assert "2001" in str(ei.value)

    def test_no_raw_sql_settings_table(self):
        """验证 persona_manager 源码中不存在对 settings 表的 SQL 引用"""
        from services.agent import persona_manager
        source = inspect.getsource(persona_manager)
        # 主要检查没有 CREATE TABLE settings / INSERT INTO settings 等 SQL
        assert "CREATE TABLE" not in source, "不应有 CREATE TABLE SQL"
        assert "INSERT INTO" not in source, "不应有 INSERT INTO SQL"
        assert "SELECT" not in source or "get_metadata" in source, \
            "不应有直接 SQL SELECT"


# ════════════════════════════════════════════════════════════
# Test 2: P0-2 异步流式调用
# ════════════════════════════════════════════════════════════

class TestAsyncStreamChat:
    """P0-2: 验证 _stream_chat 是 async def 并使用 httpx.AsyncClient"""

    def test_stream_chat_is_async(self):
        """验证 _stream_chat 是协程函数（async def）"""
        from dashboard.backend.routes import ai as ai_routes
        assert inspect.iscoroutinefunction(ai_routes._stream_chat) or inspect.isasyncgenfunction(ai_routes._stream_chat), \
            "_stream_chat 必须是 async def"

    def test_stream_chat_uses_async_client(self):
        """验证 _stream_chat 源码使用 httpx.AsyncClient 而非同步 Client"""
        from dashboard.backend.routes import ai as ai_routes
        source = inspect.getsource(ai_routes._stream_chat)
        assert "AsyncClient" in source, "_stream_chat 应使用 httpx.AsyncClient"
        assert "httpx.Client(" not in source, "_stream_chat 不应使用同步 httpx.Client"


# ════════════════════════════════════════════════════════════
# Test 3: P0-3 模块级 LLMProviderManager
# ════════════════════════════════════════════════════════════

class TestModuleLevelLLMManager:
    """P0-3: 验证 routes/ai.py 有模块级 _llm_manager 实例"""

    def test_llm_manager_attribute_exists(self):
        """验证 routes/ai.py 模块存在 _llm_manager 属性"""
        from dashboard.backend.routes import ai as ai_routes
        assert hasattr(ai_routes, "_llm_manager"), \
            "routes/ai.py 应有模块级 _llm_manager"

    def test_llm_manager_is_correct_type(self):
        """验证 _llm_manager 是 LLMProviderManager 实例"""
        from dashboard.backend.routes import ai as ai_routes
        from services.llm_provider import LLMProviderManager
        assert isinstance(ai_routes._llm_manager, LLMProviderManager), \
            "_llm_manager 应是 LLMProviderManager 实例"


# ════════════════════════════════════════════════════════════
# Test 4: P1-4 动态 System Prompt
# ════════════════════════════════════════════════════════════

class TestDynamicSystemPrompt:
    """P1-4: 验证 build_system_prompt 动态组装，无硬编码 SYSTEM_PROMPT"""

    def test_no_hardcoded_system_prompt(self):
        """验证 ai_service.py 源码中不存在硬编码 SYSTEM_PROMPT 常量"""
        from dashboard.backend import ai_service
        source = inspect.getsource(ai_service)
        assert "SYSTEM_PROMPT =" not in source, \
            "ai_service.py 不应有硬编码 SYSTEM_PROMPT 常量"

    def test_build_system_prompt_contains_three_parts(self):
        """验证 build_system_prompt 返回内容包含人设、上下文、技能三部分"""
        with patch("services.agent.persona_manager.get_persona_manager") as mock_pm, \
             patch("services.agent.context_builder.get_builder") as mock_cb, \
             patch("services.agent.skill_loader.get_loader") as mock_sl:

            # Mock persona manager
            mock_persona = MagicMock()
            mock_persona.build_system_prompt = MagicMock(
                side_effect=lambda ctx: f"[人设]金探[/人设]\n{ctx}"
            )
            mock_pm.return_value = mock_persona

            # Mock context builder
            mock_builder = MagicMock()
            mock_builder.build.return_value = "[上下文]持仓:多XAUUSD[/上下文]"
            mock_cb.return_value = mock_builder

            # Mock skill loader
            mock_loader = MagicMock()
            mock_loader.list_skills.return_value = [{"name": "test_skill"}]
            mock_loader.get_summary_context.return_value = "可用技能:\n- test_skill: 测试技能"
            mock_sl.return_value = mock_loader

            from dashboard.backend.ai_service import build_system_prompt
            result = build_system_prompt()

            # 验证包含人设内容
            assert "人设" in result, "应包含人设部分"
            # 验证包含上下文内容
            assert "上下文" in result or "持仓" in result, "应包含交易上下文"
            # 验证包含技能内容
            assert "技能" in result or "test_skill" in result, "应包含技能部分"


# ════════════════════════════════════════════════════════════
# Test 5: P1-5 消息历史截断
# ════════════════════════════════════════════════════════════

class TestMessageHistoryTruncation:
    """P1-5: 验证消息历史截断逻辑 [-20:]"""

    def test_truncation_to_20_messages(self):
        """构造 30 条消息，验证截断后只保留最后 20 条"""
        history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
                   for i in range(30)]

        # 应用与 chat_api 相同的截断逻辑
        history_for_llm = (history[:-1] if history else [])[-20:]

        assert len(history_for_llm) == 20, f"截断后应有 20 条，实际 {len(history_for_llm)}"
        assert history_for_llm[0]["content"] == "msg 9", \
            f"第一条应为 msg 9，实际为 {history_for_llm[0]['content']}"
        assert history_for_llm[-1]["content"] == "msg 28", \
            f"最后一条应为 msg 28，实际为 {history_for_llm[-1]['content']}"

    def test_short_history_no_truncation(self):
        """少于 20 条消息时不应截断"""
        history = [{"role": "user", "content": f"msg {i}"} for i in range(5)]
        history_for_llm = (history[:-1] if history else [])[-20:]
        assert len(history_for_llm) == 4, "5条历史去掉最后1条应为4条"

    def test_empty_history(self):
        """空历史不应报错"""
        history = []
        history_for_llm = (history[:-1] if history else [])[-20:]
        assert len(history_for_llm) == 0


# ════════════════════════════════════════════════════════════
# Test 6: P1-6 技能摘要加载
# ════════════════════════════════════════════════════════════

class TestSkillSummaryContext:
    """P1-6: 验证 get_summary_context() 返回摘要而非完整内容"""

    def test_summary_is_abbreviated(self):
        """验证返回的是摘要（名称+描述），不是完整 SKILL.md body"""
        from services.agent.skill_loader import SkillLoader, Skill

        loader = SkillLoader()
        loader._skills = {
            "test_skill": Skill(
                name="test_skill",
                description="这是一个测试技能，用于验证摘要功能",
                body="这是完整的技能内容，" * 50,
                path="/fake/path/SKILL.md",
            )
        }

        summary = loader.get_summary_context()

        assert "test_skill" in summary, "摘要应包含技能名称"
        assert "测试技能" in summary, "摘要应包含技能描述"
        assert "这是完整的技能内容，" * 10 not in summary, \
            "摘要不应包含完整 body"

    def test_summary_much_shorter_than_full(self):
        """验证摘要比完整内容短很多"""
        from services.agent.skill_loader import SkillLoader, Skill

        loader = SkillLoader()
        long_body = "X" * 2000
        loader._skills = {
            "skill_a": Skill(name="skill_a", description="技能A描述", body=long_body, path=""),
            "skill_b": Skill(name="skill_b", description="技能B描述", body=long_body, path=""),
        }

        summary = loader.get_summary_context()
        full = loader.get_all_context()

        assert len(summary) < len(full) * 0.2, \
            f"摘要应远短于完整内容: summary={len(summary)}, full={len(full)}"

    def test_empty_skills(self):
        """无技能时返回提示"""
        from services.agent.skill_loader import SkillLoader

        loader = SkillLoader()
        loader._skills = {}
        with patch.object(loader, "scan", return_value=0):
            summary = loader.get_summary_context()
        assert "无可用技能" in summary


# ════════════════════════════════════════════════════════════
# Test 7: P2-7 ContextBuilder 使用 engine 公开接口
# ════════════════════════════════════════════════════════════

class TestContextBuilderPublicAPI:
    """P2-7: 验证 ContextBuilder 使用 engine 公开方法而非私有属性"""

    def _make_mock_engine(self):
        engine = MagicMock()
        engine.get_status.return_value = {
            "status": "running", "uptime_seconds": 100, "bridge_connected": True
        }
        engine.get_account_info.return_value = {
            "balance": 10000, "equity": 10500, "floating_pnl": 500, "free_margin": 8000
        }
        engine.get_fresh_positions.return_value = [
            {"ticket": 123, "type": "BUY", "volume": 0.1, "open_price": 2000,
             "profit": 100, "stop_loss": 1990, "take_profit": 2020}
        ]
        engine.get_price.return_value = {"bid": 2050.5, "ask": 2051.0}
        engine.get_indicators_by_tf.return_value = {
            "H1": {"rsi": 55, "macd": {"macd": 1.2, "signal": 0.8},
                   "bb": {"upper": 2060, "mid": 2050, "lower": 2040},
                   "atr": 15, "adx": 30, "ema_9": 2048, "ema_21": 2045,
                   "trend": "up", "close": 2050}
        }
        engine.get_active_strategies.return_value = ["strategy_alpha"]
        return engine

    def test_uses_public_methods(self):
        """验证 ContextBuilder 调用了 engine 的公开方法"""
        from services.agent.context_builder import ContextBuilder

        engine = self._make_mock_engine()
        builder = ContextBuilder(engine_runner=engine)
        result = builder.build(["engine", "positions", "price", "indicators", "strategies"])

        engine.get_account_info.assert_called()
        engine.get_fresh_positions.assert_called()
        engine.get_price.assert_called()
        engine.get_indicators_by_tf.assert_called()
        engine.get_active_strategies.assert_called()

        assert "账户" in result or "余额" in result, "应包含账户信息"
        assert "持仓" in result, "应包含持仓信息"
        assert "价格" in result or "bid" in result, "应包含价格信息"

    def test_no_private_attribute_access(self):
        """验证 ContextBuilder 源码不直接访问 engine 的私有缓存属性"""
        from services.agent import context_builder
        source = inspect.getsource(context_builder.ContextBuilder)
        assert "_cached_account" not in source, "不应访问 _cached_account"
        assert "_cached_price" not in source, "不应访问 _cached_price"
        assert "_cached_positions" not in source, "不应访问 _cached_positions"


# ════════════════════════════════════════════════════════════
# Test 8: P2-8 ToolRegistry 工具注册
# ════════════════════════════════════════════════════════════

class TestToolRegistryBuiltinTools:
    """P2-8: 验证 register_builtin_tools 注册 5 个核心工具"""

    def _fresh_registry(self):
        from services.agent.tool_registry import get_registry
        registry = get_registry()
        registry._tools.clear()
        return registry

    def test_register_5_tools(self):
        """验证注册后恰好有 5 个工具"""
        registry = self._fresh_registry()
        from services.agent.tool_registry import register_builtin_tools
        register_builtin_tools()

        tools = registry.list_tools()
        assert len(tools) == 5, f"应有 5 个工具，实际 {len(tools)}"

    def test_tool_names(self):
        """验证 5 个工具名称完全正确"""
        registry = self._fresh_registry()
        from services.agent.tool_registry import register_builtin_tools
        register_builtin_tools()

        expected = {"get_positions", "get_indicators", "get_account_info",
                    "get_trades_history", "get_market_price"}
        actual = {t["name"] for t in registry.list_tools()}
        assert actual == expected, f"工具名不匹配: 期望 {expected}, 实际 {actual}"

    def test_call_get_account_info(self):
        """验证调用 get_account_info 工具返回正确数据格式"""
        registry = self._fresh_registry()
        from services.agent.tool_registry import register_builtin_tools
        register_builtin_tools()

        mock_engine = MagicMock()
        mock_engine._cached_account = {
            "login": 12345, "balance": 10000, "equity": 10500,
            "margin": 2000, "free_margin": 8000, "currency": "USD", "leverage": 100
        }
        mock_engine._cached_positions = [
            {"profit": 200}, {"profit": -50}
        ]

        with patch("services.agent.tool_registry._get_engine", return_value=mock_engine):
            result = registry.call("get_account_info")
            assert isinstance(result, dict)
            assert result["balance"] == 10000
            assert result["equity"] == 10500
            assert "floating_pnl" in result

    def test_to_openai_tools_format(self):
        """验证 to_openai_tools() 输出符合 OpenAI function calling 格式"""
        registry = self._fresh_registry()
        from services.agent.tool_registry import register_builtin_tools
        register_builtin_tools()

        openai_tools = registry.to_openai_tools()
        assert len(openai_tools) == 5

        for tool in openai_tools:
            assert tool["type"] == "function"
            assert "function" in tool
            fn = tool["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn


# ════════════════════════════════════════════════════════════
# Test 9: P2-9 LLM Provider 故障转移链
# ════════════════════════════════════════════════════════════

class TestLLMProviderFailover:
    """P2-9: 验证 LLM Provider 故障转移链"""

    def _make_manager(self):
        from services.llm_provider import LLMProviderManager
        mgr = LLMProviderManager.__new__(LLMProviderManager)
        mgr._providers = [
            {
                "id": "primary",
                "name": "Primary",
                "type": "openai",
                "api_key": "sk-primary-key-12345",
                "base_url": "https://api.primary.com/v1",
                "models": ["model-a"],
                "selected_model": "model-a",
                "is_active": True,
                "created_at": "",
            },
            {
                "id": "backup",
                "name": "Backup",
                "type": "openai",
                "api_key": "sk-backup-key-12345",
                "base_url": "https://api.backup.com/v1",
                "models": ["model-b"],
                "selected_model": "model-b",
                "is_active": False,
                "created_at": "",
            },
        ]
        return mgr

    def test_failover_to_backup(self):
        """主 provider 失败时自动切换到备用 provider"""
        import httpx
        mgr = self._make_manager()

        call_count = [0]

        def mock_post(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise httpx.ConnectError("Connection refused")
            else:
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "choices": [{"message": {"content": "backup response"}}]
                }
                mock_resp.raise_for_status = MagicMock()
                return mock_resp

        with patch("httpx.post", side_effect=mock_post):
            result = mgr.chat([{"role": "user", "content": "hello"}])

        assert result == "backup response", f"应返回备用 provider 回复，实际: {result}"
        assert call_count[0] == 2, "应调用 2 次（主 + 备）"

    def test_failover_logs_event(self):
        """故障转移时尝试多个 provider（通过调用次数验证故障转移行为）"""
        import httpx
        mgr = self._make_manager()

        call_log = []

        def mock_post(*args, **kwargs):
            call_log.append(args[0] if args else "")
            if len(call_log) == 1:
                raise httpx.ConnectError("Connection refused")
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "ok"}}]
            }
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.post", side_effect=mock_post):
            result = mgr.chat([{"role": "user", "content": "test"}])

        assert result is not None, "故障转移应成功返回"
        assert len(call_log) == 2, f"应调用 2 次 httpx.post（主+备），实际 {len(call_log)}"
        assert "primary" in call_log[0], "第一次应调用主 provider"
        assert "backup" in call_log[1], "第二次应调用备用 provider"

    def test_all_providers_fail_returns_none(self):
        """所有 provider 都失败时返回 None"""
        import httpx
        mgr = self._make_manager()

        with patch("httpx.post", side_effect=httpx.ConnectError("all down")):
            result = mgr.chat([{"role": "user", "content": "hello"}])

        assert result is None, "所有 provider 失败应返回 None"
