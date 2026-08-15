"""
pytest 配置 — 确保 tests/ 下的测试能 import 项目模块
"""
import os
import sys

# 将项目根目录加入 sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
