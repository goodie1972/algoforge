"""
版本信息读取
================
- 从项目根的 VERSION 文件读取 semver
- 从 git 命令获取当前 commit hash 和分支
- 提供统一的 get_version() / get_version_info() 供后端 API、start.py、Dashboard 共用
"""
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = BASE_DIR / "VERSION"


def get_version() -> str:
    """读取 VERSION 文件，返回 '0.5.0' 这样的 semver 字符串"""
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "0.0.0"


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(BASE_DIR), *args],
            capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def get_commit_hash() -> str:
    h = _git("rev-parse", "--short", "HEAD")
    return h or "unknown"


def get_branch() -> str:
    b = _git("rev-parse", "--abbrev-ref", "HEAD")
    return b or "unknown"


def get_dirty() -> bool:
    """工作区是否有未提交修改"""
    return bool(_git("status", "--porcelain"))


def get_version_info() -> dict:
    """返回 Dashboard / start.py 需要的完整版本信息"""
    return {
        "version": get_version(),
        "commit": get_commit_hash(),
        "branch": get_branch(),
        "dirty": get_dirty(),
        "display": f"v{get_version()} ({get_commit_hash()}{'*' if get_dirty() else ''})",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(get_version_info(), indent=2, ensure_ascii=False))
