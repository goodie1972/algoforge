"""
LLM Provider 管理 — 支持多 Provider 配置
========================================
支持 OpenAI / DeepSeek / Ollama / 任意 OpenAI 兼容 API。

用法:
  from services.llm_provider import LLMProviderManager
  mgr = LLMProviderManager()
  providers = mgr.list_providers()
  active = mgr.get_active()
  result = mgr.chat("分析黄金走势", provider_id="xxx")
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           "data", "llm_providers.json")

DEFAULT_PROVIDERS = [
    {
        "id": "openai",
        "name": "OpenAI",
        "type": "openai",
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "selected_model": "gpt-4o-mini",
        "is_active": False,
        "created_at": "",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "type": "openai",
        "api_key": "",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "selected_model": "deepseek-chat",
        "is_active": False,
        "created_at": "",
    },
    {
        "id": "ollama",
        "name": "Ollama（本地）",
        "type": "ollama",
        "api_key": "",
        "base_url": "http://localhost:11434",
        "models": [],
        "selected_model": "",
        "is_active": False,
        "created_at": "",
    },
]


class LLMProviderManager:
    """LLM Provider 配置管理器"""

    def __init__(self):
        self._providers: list[dict] = []
        self._load()

    # ── 持久化 ──────────────────────────────────────

    def _load(self):
        """从 JSON 文件加载 Provider 列表"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self._providers = json.load(f)
            else:
                self._providers = DEFAULT_PROVIDERS
                self._save()
        except Exception as e:
            logger.warning(f"[LLMProvider] 加载失败: {e}")
            self._providers = DEFAULT_PROVIDERS

    def _save(self):
        """保存到 JSON 文件"""
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._providers, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[LLMProvider] 保存失败: {e}")

    # ── CRUD ────────────────────────────────────────

    def list_providers(self) -> list[dict]:
        """返回所有 Provider（隐藏 API Key）"""
        return [self._sanitize(p) for p in self._providers]

    def get_provider(self, provider_id: str) -> Optional[dict]:
        """获取单个 Provider"""
        for p in self._providers:
            if p["id"] == provider_id:
                return self._sanitize(p)
        return None

    def add_provider(self, data: dict) -> dict:
        """新增 Provider"""
        provider = {
            "id": data.get("id", uuid.uuid4().hex[:8]),
            "name": data.get("name", "New Provider"),
            "type": data.get("type", "openai"),
            "api_key": data.get("api_key", ""),
            "base_url": data.get("base_url", "https://api.openai.com/v1"),
            "models": data.get("models", []),
            "enabled_models": data.get("enabled_models", []),
            "selected_model": data.get("selected_model", ""),
            "is_active": data.get("is_active", False),
            "created_at": datetime.now().isoformat(),
        }
        self._providers.append(provider)
        self._save()
        return self._sanitize(provider)

    def update_provider(self, provider_id: str, data: dict) -> Optional[dict]:
        """更新 Provider 配置"""
        for p in self._providers:
            if p["id"] == provider_id:
                for key in ("name", "type", "api_key", "base_url", "models",
                            "enabled_models", "selected_model", "is_active"):
                    if key in data:
                        p[key] = data[key]
                self._save()
                return self._sanitize(p)
        return None

    def delete_provider(self, provider_id: str) -> bool:
        """删除 Provider"""
        before = len(self._providers)
        self._providers = [p for p in self._providers if p["id"] != provider_id]
        if len(self._providers) < before:
            self._save()
            return True
        return False

    def set_active(self, provider_id: str) -> Optional[dict]:
        """设置激活的 Provider（只有一个可激活）"""
        found = None
        for p in self._providers:
            p["is_active"] = (p["id"] == provider_id)
            if p["id"] == provider_id:
                found = p
        self._save()
        return self._sanitize(found) if found else None

    def get_active(self) -> Optional[dict]:
        """获取当前激活的 Provider"""
        for p in self._providers:
            if p["is_active"]:
                return self._sanitize(p)
        return None

    def get_active_raw(self) -> Optional[dict]:
        """获取完整信息（含 API Key，用于调用）"""
        for p in self._providers:
            if p["is_active"]:
                return p
        return None

    # ── 调用 ────────────────────────────────────────

    def chat(self, messages: list[dict],
             provider_id: Optional[str] = None,
             temperature: float = 0.3) -> Optional[str]:
        """
        调用 LLM 聊天接口。

        Args:
            messages: [{"role": "user", "content": "..."}]
            provider_id: 指定 Provider，None 则用激活的
            temperature: 温度

        Returns:
            LLM 回复文本，失败返回 None
        """
        provider = None
        if provider_id:
            for p in self._providers:
                if p["id"] == provider_id:
                    provider = p
                    break
        else:
            provider = self.get_active_raw()

        if not provider or not provider.get("api_key"):
            logger.warning("[LLMProvider] 无可用 Provider 或 API Key 未设置")
            return None

        model = provider.get("selected_model") or provider.get("models", [""])[0]
        if not model:
            logger.warning("[LLMProvider] 未选择模型")
            return None

        base_url = provider.get("base_url", "https://api.openai.com/v1").rstrip("/")
        if provider["type"] == "ollama":
            api_url = f"{base_url}/api/chat"
        else:
            api_url = f"{base_url}/chat/completions"

        try:
            import httpx
            headers = {"Content-Type": "application/json"}
            if provider["type"] != "ollama":
                headers["Authorization"] = f"Bearer {provider['api_key']}"

            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }

            if provider["type"] == "ollama":
                payload["stream"] = False

            resp = httpx.post(api_url, json=payload, headers=headers,
                              timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if provider["type"] == "ollama":
                return data.get("message", {}).get("content", "")
            else:
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")

        except Exception as e:
            logger.error(f"[LLMProvider] 调用失败: {e}")
            return None

    def test_connection(self, provider_id: str) -> dict:
        """测试连接"""
        provider = None
        for p in self._providers:
            if p["id"] == provider_id:
                provider = p
                break
        if not provider:
            return {"success": False, "error": "Provider 不存在"}
        if not provider.get("api_key") and provider["type"] != "ollama":
            return {"success": False, "error": "API Key 未设置"}

        try:
            import httpx
            base_url = provider["base_url"].rstrip("/")
            if provider["type"] == "ollama":
                resp = httpx.get(f"{base_url}/api/tags", timeout=10)
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
                # 更新模型列表
                provider["models"] = models
                if not provider["selected_model"] and models:
                    provider["selected_model"] = models[0]
                # 自动启用所有可用模型
                provider["enabled_models"] = models[:]
                self._save()
                return {"success": True, "models": models}
            else:
                resp = httpx.get(f"{base_url}/models",
                                 headers={"Authorization": f"Bearer {provider['api_key']}"},
                                 timeout=10)
                resp.raise_for_status()
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                if models:
                    provider["models"] = models
                    provider["enabled_models"] = models[:]
                    if not provider["selected_model"]:
                        provider["selected_model"] = models[0]
                    self._save()
                return {"success": True, "models": models}
        except Exception as e:
            # 即使 list models 失败，chat 接口可能仍可用
            return {"success": True, "warning": str(e),
                    "models": provider.get("models", [])}

    # ── 辅助 ────────────────────────────────────────

    @staticmethod
    def _sanitize(provider: dict) -> dict:
        """隐藏 API Key"""
        p = dict(provider)
        if p.get("api_key"):
            key = p["api_key"]
            p["api_key"] = key[:6] + "..." + key[-4:] if len(key) > 12 else "****"
        return p