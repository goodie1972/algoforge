"""
工具注册表 — 注册/查找/调用工具
每个工具: {name, description, parameters(dict), handler(callable)}
"""
import logging
import inspect
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, dict] = {}

    def register(self, name: str, description: str, handler: Callable,
                 parameters: Optional[dict] = None, category: str = "builtin") -> None:
        """注册工具"""
        if parameters is None:
            sig = inspect.signature(handler)
            params = {}
            for p_name, p_param in sig.parameters.items():
                if p_name == "self" or p_name == "kwargs":
                    continue
                param_type = "string"
                if p_param.annotation is not inspect.Parameter.empty:
                    if p_param.annotation is int:
                        param_type = "integer"
                    elif p_param.annotation is float:
                        param_type = "number"
                    elif p_param.annotation is bool:
                        param_type = "boolean"
                params[p_name] = {"type": param_type, "description": ""}
            parameters = {"type": "object", "properties": params}

        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "handler": handler,
            "category": category,
        }
        logger.info(f"[ToolRegistry] registered: {name} ({category})")

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[dict]:
        return self._tools.get(name)

    def list_tools(self, category: Optional[str] = None) -> list[dict]:
        tools = self._tools.values()
        if category:
            tools = [t for t in tools if t["category"] == category]
        return [{"name": t["name"], "description": t["description"],
                 "parameters": t["parameters"]} for t in tools]

    def call(self, name: str, **kwargs) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return f"错误: 工具 '{name}' 不存在"
        try:
            return tool["handler"](**kwargs)
        except Exception as e:
            logger.error(f"[ToolRegistry] call {name} failed: {e}")
            return f"调用失败: {e}"

    def to_openai_tools(self, category: Optional[str] = None) -> list[dict]:
        """转为 OpenAI function calling 格式"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                }
            }
            for t in self._tools.values()
            if category is None or t["category"] == category
        ]


# 全局单例
_registry = ToolRegistry()

def get_registry() -> ToolRegistry:
    return _registry