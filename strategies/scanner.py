"""
strategyauto扫描器 — 从 strategies/ 目录auto发现所有strategy类
不需要manual维护 STRATEGY_MAP  and 注册表
"""

import importlib
import os
import sys
import logging

logger = logging.getLogger(__name__)

_STRATEGIES_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_STRATEGIES_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_strategy_cache = None
_strategy_meta_cache = None

_EXCLUDED_FILES = {"__init__.py", "base.py", "scanner.py"}


def _module_doc_first_line(mod) -> str:
    doc = (mod.__doc__ or "").strip()
    if doc:
        first_line = doc.split("\n")[0].strip().strip("= ")
        return first_line
    return ""




def scan_strategies():
    """return {name: class} — 所有strategy类 映射"""
    global _strategy_cache
    if _strategy_cache is not None:
        return _strategy_cache

    from strategies.base import BaseStrategy
    result = {}

    for f in sorted(os.listdir(_STRATEGIES_DIR)):
        if not f.endswith(".py") or f in _EXCLUDED_FILES:
            continue
        mod_name = f"strategies.{f[:-3]}"
        try:
            mod = importlib.import_module(mod_name)
            importlib.reload(mod)
        except Exception as e:
            logger.warning(f"[Scan] load {mod_name} failed: {e}")
            continue

        for attr_name in dir(mod):
            cls = getattr(mod, attr_name)
            if (isinstance(cls, type) and issubclass(cls, BaseStrategy)
                    and cls is not BaseStrategy):
                name = getattr(cls, "name", None)
                if name:
                    result[name] = cls
                    break

    _strategy_cache = result
    return result


def scan_strategy_metadata():
    """return {name: dict} — 所有strategy 元data"""
    global _strategy_meta_cache
    if _strategy_meta_cache is not None:
        return _strategy_meta_cache

    from strategies.base import BaseStrategy
    result = {}

    for f in sorted(os.listdir(_STRATEGIES_DIR)):
        if not f.endswith(".py") or f in _EXCLUDED_FILES:
            continue
        mod_name = f"strategies.{f[:-3]}"
        try:
            mod = importlib.import_module(mod_name)
            importlib.reload(mod)
        except Exception:
            continue

        for attr_name in dir(mod):
            cls = getattr(mod, attr_name)
            if (isinstance(cls, type) and issubclass(cls, BaseStrategy)
                    and cls is not BaseStrategy):
                name = getattr(cls, "name", None)
                if not name:
                    continue

                module_magic = getattr(mod, "STRATEGY_MAGIC", None)
                display = _module_doc_first_line(mod)
                if not display:
                    display = (cls.__doc__ or name).strip()

                result[name] = {
                    "id": name,
                    "name": name,
                    "display": display,
                    "file": f,
                    "default_magic": module_magic,
                    "default_timeframe": getattr(cls, "default_timeframe", "M30"),
                    "module": mod_name,
                }
                break

    _strategy_meta_cache = result
    return result


def clear_cache():
    global _strategy_cache, _strategy_meta_cache
    _strategy_cache = None
    _strategy_meta_cache = None
