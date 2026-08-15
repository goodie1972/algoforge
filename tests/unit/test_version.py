"""
版本检查单元测试 — 验证 core/version.py 逻辑
"""
import pytest
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def test_version_file_exists():
    """VERSION 文件存在"""
    version_path = os.path.join(_project_root, "VERSION")
    assert os.path.exists(version_path), "VERSION file should exist"


def test_version_format():
    """版本号格式正确 (x.y.z)"""
    from core.version import get_version
    v = get_version()
    parts = v.split(".")
    assert len(parts) == 3, f"Version should be x.y.z, got {v}"
    for p in parts:
        assert p.isdigit(), f"Version part '{p}' should be numeric"


def test_version_not_empty():
    """版本号不为空"""
    from core.version import get_version
    v = get_version()
    assert v is not None
    assert len(v) > 0


def test_check_remote_update_returns_none_or_dict():
    """远程更新检查返回 None 或 dict（不报错）"""
    from core.version import check_remote_update
    result = check_remote_update()
    # 网络不通时返回 None，通时返回 dict
    assert result is None or isinstance(result, dict)
