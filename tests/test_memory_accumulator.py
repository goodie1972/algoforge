"""
记忆自动积累器单元测试
覆盖 services/agent/memory_accumulator.py：
  ① 正常提取 → memory.md 追加含 [MM-DD] 日期前缀与内容
  ② LLM 返回 NONE → memory.md 无变化
  ③ 追加后超 2000 字 → 头部裁剪后 ≤2000 且保留最新行
  ④ 开关关闭 → 直接返回，不调 LLM
  ⑤ LLM 抛异常 → 静默无异常且文件不脏
  ⑥ 单飞锁 → 并发两个 accumulate 只执行一个

隔离方式（零真实网络）：
- persona_manager 的 PERSONA_DIR / MEMORY_PATH monkeypatch 到 tmp_path
- agent_settings 的 SETTINGS_FILE monkeypatch 到 tmp_path
- dashboard.backend.ai_service 用 sys.modules 注入假模块（固定对话）
- services.llm_provider.LLMProviderManager monkeypatch 为假实现
"""

import asyncio
import os
import re
import sys
import threading
import types
from datetime import datetime

import pytest

# 确保项目根目录在 sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import services.agent.agent_settings as settings_mod
import services.agent.memory_accumulator as ma_mod
import services.agent.persona_manager as pm_mod
import services.llm_provider as llm_mod

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mem_env(tmp_path, monkeypatch):
    """把人设存储路径与设置文件全部切到临时目录"""
    monkeypatch.setattr(pm_mod, "PERSONA_DIR", str(tmp_path))
    monkeypatch.setattr(pm_mod, "MEMORY_PATH", str(tmp_path / "memory.md"))
    monkeypatch.setattr(settings_mod, "SETTINGS_FILE", str(tmp_path / "agent_settings.json"))
    return tmp_path


def _install_fake_messages(monkeypatch, messages):
    """注入假的 dashboard.backend.ai_service 模块，get_messages 返回固定对话"""
    calls = []
    fake = types.ModuleType("dashboard.backend.ai_service")

    def get_messages(session_id):
        calls.append(session_id)
        return messages

    fake.get_messages = get_messages
    monkeypatch.setitem(sys.modules, "dashboard.backend.ai_service", fake)
    return calls


def _install_fake_llm(monkeypatch, response="用户偏好简洁回答", raise_exc=None):
    """monkeypatch LLMProviderManager 为假实现，返回调用记录列表"""
    calls = []

    class FakeLLM:
        def __init__(self):
            pass

        def chat(self, messages, provider_id=None, temperature=0.3):
            calls.append(messages)
            if raise_exc is not None:
                raise raise_exc
            return response

    monkeypatch.setattr(llm_mod, "LLMProviderManager", FakeLLM)
    return calls


async def _drain():
    """等待所有已调度的积累任务完成"""
    while ma_mod._pending_tasks:
        await asyncio.gather(*list(ma_mod._pending_tasks), return_exceptions=True)


def _read_memory(tmp_path):
    p = tmp_path / "memory.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


FIXED_CONVERSATION = [
    {"id": 1, "role": "user", "content": "帮我分析黄金走势"},
    {"id": 2, "role": "assistant", "content": "当前黄金处于震荡区间。"},
    {"id": 3, "role": "user", "content": "以后回答简洁一点"},
    {"id": 4, "role": "assistant", "content": "好的，我会简洁回答。"},
]


# ════════════════════════════════════════════════════════════
# ① 正常提取 → 追加含日期前缀与内容
# ════════════════════════════════════════════════════════════

class TestNormalExtract:

    async def test_appends_entry_with_date_prefix(self, mem_env, monkeypatch):
        msg_calls = _install_fake_messages(monkeypatch, FIXED_CONVERSATION)
        llm_calls = _install_fake_llm(monkeypatch, response="用户偏好简洁回答")

        await ma_mod.accumulate("sess-1", "好的，我会简洁回答。")
        await _drain()

        memory = _read_memory(mem_env)
        stamp = datetime.now().strftime("%m-%d")
        assert f"- [{stamp}] 用户偏好简洁回答" in memory
        assert msg_calls == ["sess-1"]
        assert len(llm_calls) == 1

    async def test_appends_to_existing_memory(self, mem_env, monkeypatch):
        """已有记忆时追加在末尾，不覆盖旧内容"""
        (mem_env / "memory.md").write_text("- [01-01] 旧记忆条目", encoding="utf-8")
        _install_fake_messages(monkeypatch, FIXED_CONVERSATION)
        _install_fake_llm(monkeypatch, response="用户关注非农数据")

        await ma_mod.accumulate("sess-1", "")
        await _drain()

        memory = _read_memory(mem_env)
        assert memory.startswith("- [01-01] 旧记忆条目")
        assert "用户关注非农数据" in memory
        assert memory.index("旧记忆条目") < memory.index("用户关注非农数据")

    async def test_transcript_only_recent_6(self, mem_env, monkeypatch):
        """只取最近 6 条消息进入提示词"""
        many = [{"id": i, "role": "user" if i % 2 == 0 else "assistant",
                 "content": f"消息{i}"} for i in range(20)]
        _install_fake_messages(monkeypatch, many)
        llm_calls = _install_fake_llm(monkeypatch, response="要点")

        await ma_mod.accumulate("sess-1", "")
        await _drain()

        prompt = llm_calls[0][0]["content"]
        assert "消息19" in prompt  # 最新一条必在
        assert "消息14" in prompt  # 最近 6 条的边界（索引 14~19）
        assert "消息13" not in prompt  # 第 7 条之前的被截掉

    async def test_prompt_contains_fixed_instruction(self, mem_env, monkeypatch):
        """提示词为固定模板"""
        _install_fake_messages(monkeypatch, FIXED_CONVERSATION)
        llm_calls = _install_fake_llm(monkeypatch)

        await ma_mod.accumulate("sess-1", "")
        await _drain()

        prompt = llm_calls[0][0]["content"]
        assert "从以下对话中提取值得长期记住的用户偏好/决策要点" in prompt
        assert "若无值得记录的，只输出 NONE" in prompt
        assert "用户: 帮我分析黄金走势" in prompt
        assert "助手: 当前黄金处于震荡区间。" in prompt


# ════════════════════════════════════════════════════════════
# ② LLM 返回 NONE → 不写文件
# ════════════════════════════════════════════════════════════

class TestNoneResponse:

    async def test_none_no_write(self, mem_env, monkeypatch):
        _install_fake_messages(monkeypatch, FIXED_CONVERSATION)
        _install_fake_llm(monkeypatch, response="NONE")

        await ma_mod.accumulate("sess-1", "")
        await _drain()

        assert not (mem_env / "memory.md").exists()

    async def test_none_case_insensitive_and_stripped(self, mem_env, monkeypatch):
        """' none ' 去空白且大小写不敏感"""
        (mem_env / "memory.md").write_text("原有记忆", encoding="utf-8")
        _install_fake_messages(monkeypatch, FIXED_CONVERSATION)
        _install_fake_llm(monkeypatch, response="  none \n")

        await ma_mod.accumulate("sess-1", "")
        await _drain()

        assert _read_memory(mem_env) == "原有记忆"

    async def test_llm_returns_none_value(self, mem_env, monkeypatch):
        """LLM 返回 None（调用失败）→ 不写文件不抛错"""
        _install_fake_messages(monkeypatch, FIXED_CONVERSATION)
        _install_fake_llm(monkeypatch, response=None)

        await ma_mod.accumulate("sess-1", "")
        await _drain()

        assert not (mem_env / "memory.md").exists()


# ════════════════════════════════════════════════════════════
# ③ 超 2000 字 → 头部裁剪，保留最新行
# ════════════════════════════════════════════════════════════

class TestTrimOverLimit:

    async def test_trim_keeps_newest_within_limit(self, mem_env, monkeypatch):
        """预置 ~2000 字旧记忆，追加后触发头部裁剪：≤2000 且新条目保留、最旧条目被裁"""
        old_lines = [f"- [01-{i % 28 + 1:02d}] 旧条目{i:03d}" + "垫" * 40 for i in range(38)]
        old_text = "\n".join(old_lines)
        assert len(old_text) > 1900
        (mem_env / "memory.md").write_text(old_text, encoding="utf-8")

        _install_fake_messages(monkeypatch, FIXED_CONVERSATION)
        _install_fake_llm(monkeypatch, response="新增的最新记忆要点" + "新" * 30)

        await ma_mod.accumulate("sess-1", "")
        await _drain()

        memory = _read_memory(mem_env)
        assert len(memory) <= 2000, f"裁剪后应 ≤2000 字，实际 {len(memory)}"
        assert "新增的最新记忆要点" in memory, "新增行必须保留"
        assert "旧条目000" not in memory, "最旧条目应从头部被裁掉"
        stamp = datetime.now().strftime("%m-%d")
        assert re.search(rf"- \[{re.escape(stamp)}\] 新增的最新记忆要点", memory)

    async def test_no_trim_when_within_limit(self, mem_env, monkeypatch):
        """未超限时不裁剪"""
        (mem_env / "memory.md").write_text("- [01-01] 旧条目000", encoding="utf-8")
        _install_fake_messages(monkeypatch, FIXED_CONVERSATION)
        _install_fake_llm(monkeypatch, response="新要点")

        await ma_mod.accumulate("sess-1", "")
        await _drain()

        memory = _read_memory(mem_env)
        assert "旧条目000" in memory
        assert "新要点" in memory

    async def test_single_oversized_entry_char_truncated(self, mem_env, monkeypatch):
        """单条提取结果超 2000 字（单行）→ 字符级兜底截断后落盘 ≤2000 字"""
        _install_fake_messages(monkeypatch, FIXED_CONVERSATION)
        _install_fake_llm(monkeypatch, response="超长记忆要点" + "字" * 3000)

        await ma_mod.accumulate("sess-1", "")
        await _drain()

        memory = _read_memory(mem_env)
        assert 0 < len(memory) <= 2000, f"兜底截断后应 ≤2000 字，实际 {len(memory)}"
        assert memory.startswith("- ["), "截断后仍应保留日期前缀开头"


# ════════════════════════════════════════════════════════════
# ④ 开关关闭 → 直接返回，不调 LLM
# ════════════════════════════════════════════════════════════

class TestSwitchOff:

    async def test_disabled_skips_llm(self, mem_env, monkeypatch):
        monkeypatch.setattr(
            settings_mod, "get_setting",
            lambda key, default=None: False if key == "memory_auto_accumulate" else default)
        msg_calls = _install_fake_messages(monkeypatch, FIXED_CONVERSATION)
        llm_calls = _install_fake_llm(monkeypatch)

        await ma_mod.accumulate("sess-1", "回复")
        await _drain()

        assert llm_calls == [], "开关关闭时不应调用 LLM"
        assert msg_calls == [], "开关关闭时不应读取会话消息"
        assert not (mem_env / "memory.md").exists()
        assert not ma_mod._pending_tasks


# ════════════════════════════════════════════════════════════
# ⑤ LLM 抛异常 → 静默无异常且文件不脏
# ════════════════════════════════════════════════════════════

class TestLLMError:

    async def test_llm_exception_swallowed(self, mem_env, monkeypatch):
        (mem_env / "memory.md").write_text("原有记忆", encoding="utf-8")
        _install_fake_messages(monkeypatch, FIXED_CONVERSATION)
        _install_fake_llm(monkeypatch, raise_exc=RuntimeError("network down"))

        # 不抛异常
        await ma_mod.accumulate("sess-1", "")
        await _drain()

        assert _read_memory(mem_env) == "原有记忆", "异常时文件不应被污染"

    async def test_db_exception_swallowed(self, mem_env, monkeypatch):
        """get_messages 抛异常同样静默"""
        fake = types.ModuleType("dashboard.backend.ai_service")

        def get_messages(session_id):
            raise RuntimeError("db down")

        fake.get_messages = get_messages
        monkeypatch.setitem(sys.modules, "dashboard.backend.ai_service", fake)
        llm_calls = _install_fake_llm(monkeypatch)

        await ma_mod.accumulate("sess-1", "")
        await _drain()

        assert llm_calls == [], "取消息失败时不应调用 LLM"
        assert not (mem_env / "memory.md").exists()


# ════════════════════════════════════════════════════════════
# ⑥ 单飞锁 → 并发两个 accumulate 只执行一个
# ════════════════════════════════════════════════════════════

class TestSingleFlight:

    async def test_concurrent_accumulate_runs_once(self, mem_env, monkeypatch):
        """第一次积累在跑时，第二次直接跳过；LLM 仅被调用一次"""
        _install_fake_messages(monkeypatch, FIXED_CONVERSATION)

        started = threading.Event()
        release = threading.Event()
        calls = []

        class SlowLLM:
            def __init__(self):
                pass

            def chat(self, messages, provider_id=None, temperature=0.3):
                calls.append(messages)
                started.set()
                release.wait(5)  # 阻塞，模拟慢 LLM 调用
                return "慢要点"

        monkeypatch.setattr(llm_mod, "LLMProviderManager", SlowLLM)

        t1 = asyncio.create_task(ma_mod.accumulate("sess-1", ""))
        await t1
        # 等第一个任务真正进入执行（持有单飞锁）
        for _ in range(200):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set(), "第一个积累任务应已开始执行"

        # 第二个并发请求应被单飞锁跳过
        await ma_mod.accumulate("sess-2", "")
        await asyncio.sleep(0.05)

        release.set()
        await _drain()

        assert len(calls) == 1, f"单飞锁下 LLM 只应调用一次，实际 {len(calls)} 次"
        memory = _read_memory(mem_env)
        assert "慢要点" in memory
