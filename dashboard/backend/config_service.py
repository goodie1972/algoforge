"""
运行时配置服务 - 从 settings.py 读取默认值，runtime_config.json 覆盖
Re-export from core.runtime_config for backward compatibility
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from core.runtime_config import RuntimeConfig
from core.runtime_config import CONFIG_FILE, _ENGINE_KEYS, _STRATEGY_KEYS
