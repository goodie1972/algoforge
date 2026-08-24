"""
Agent 全局设置管理
==================
管理 AI Agent 的全局开关与密钥类设置，JSON 文件持久化
（模式与 services/agent/mcp_config.py 保持一致）。

用法:
  from services.agent.agent_settings import get_all, get_setting, update
  settings = get_all()
"""

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

# 配置文件路径：项目根目录 / data / agent_settings.json
# （路径计算方式与 mcp_config.CONFIG_FILE 一致，模块级常量便于测试 monkeypatch）
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                             "data", "agent_settings.json")

# 默认设置（未知键一律不持久化）
DEFAULT_SETTINGS = {
    "tools_enabled": True,
    "memory_auto_accumulate": True,
    "smithery_api_key": "",
}

# 写入锁：保护 读-改-写 的原子性
_lock = threading.Lock()


def _load() -> dict:
    """从 JSON 文件加载设置，文件缺失/损坏时记日志并返回空 dict（不抛异常）"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            logger.warning("[AgentSettings] config is not a JSON object, fallback to defaults")
    except Exception as e:
        logger.warning(f"[AgentSettings] load failed, fallback to defaults: {e}")
    return {}


def _save(data: dict) -> None:
    """保存到 JSON 文件"""
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[AgentSettings] save failed: {e}")


def get_all() -> dict:
    """返回全部设置（合并默认值：缺字段补默认，未知键不返回）"""
    merged = dict(DEFAULT_SETTINGS)
    stored = _load()
    for key in DEFAULT_SETTINGS:
        if key in stored:
            merged[key] = stored[key]
    return merged


def get_setting(key: str, default=None):
    """返回单个设置值，不存在时返回 default"""
    return get_all().get(key, default)


def update(partial: dict) -> dict:
    """合并写入设置（线程安全，写时过滤未知键），返回更新后的全部设置"""
    with _lock:
        # 以默认值为基底合并磁盘已有配置，保证落盘后字段完整（缺字段补默认）
        current = dict(DEFAULT_SETTINGS)
        stored = _load()
        for key in DEFAULT_SETTINGS:
            if key in stored:
                current[key] = stored[key]
        # 应用本次更新，未知键过滤不落盘
        for key, value in (partial or {}).items():
            if key in DEFAULT_SETTINGS:
                current[key] = value
            else:
                logger.debug(f"[AgentSettings] unknown setting key ignored: {key}")
        _save(current)
    return get_all()


def mask_key(key: str) -> str:
    """API Key 打码：空串原样返回；≤8 位全掩；否则首 4 尾 2 中间 ****"""
    key = str(key or "")
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}****{key[-2:]}"
