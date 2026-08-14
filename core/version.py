"""
版本信息读取
================
- 从项目根的 VERSION 文件读取 semver
- 从 git ���令获取当前 commit hash 和分支
- 提供统一的 get_version() / get_version_info() 供后端 API、start.py、Dashboard 共用
"""
import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = BASE_DIR / "VERSION"


def get_version() -> str:
    """读取 VERSION 文件，返回 '0.5.0' 这样的 semver 字符��"""
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


# 远程更新��查��存（��免���� fetch 导致��塞）
_remote_update_cache: dict | None = None
_remote_update_cache_time: float = 0
_REMOTE_CACHE_TTL = 300  # 5分钟��存


def check_remote_update() -> dict:
    """��查远程是否有新版本（带��存，��免��塞）"""
    global _remote_update_cache, _remote_update_cache_time
    now = time.time()

    # ��存有效则直接返回
    if _remote_update_cache and (now - _remote_update_cache_time) < 300:
        return _remote_update_cache

    # 非��塞��试 fetch，设置极短超时
    try:
        subprocess.run(
            ["git", "-C", str(BASE_DIR), "fetch", "origin", "--quiet"],
            capture_output=True, timeout=3,
        )
    except Exception:
        pass  # ���略网��错误，使用已有的 refs

    behind = _git("rev-list", "--count", "HEAD..origin/main")
    count = int(behind) if behind.isdigit() else 0

    _remote_update_cache = {
        "has_update": count > 0,
        "behind_count": count,
    }
    _remote_update_cache_time = now
    return _remote_update_cache


def get_remote_changelog(limit: int = 20) -> list[dict]:
    """获取远程有但本地没有的 commit 列表"""
    try:
        out = subprocess.run(
            ["git", "-C", str(BASE_DIR), "log",
             f"-{limit}", "--pretty=format:%h|%ai|%s", "HEAD..origin/main"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        commits = []
        for line in out.stdout.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({"hash": parts[0], "date": parts[1], "subject": parts[2]})
        return commits
    except Exception:
        return []


def do_update() -> dict:
    """��行 git pull 更新代码（仅 dirty=False 时��许）"""
    if get_dirty():
        return {"success": False, "message": "工作区有未提交修改，请先提交或��存"}
    try:
        out = subprocess.run(
            ["git", "-C", str(BASE_DIR), "pull", "--ff-only"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if out.returncode != 0:
            return {"success": False, "message": out.stderr.strip() or out.stdout.strip()}
        return {"success": True, "message": out.stdout.strip(), "version": get_version_info()}
    except Exception as e:
        return {"success": False, "message": str(e)}


def get_version_info() -> dict:
    """返回 Dashboard / start.py ���要的完整版本信息"""
    remote = check_remote_update()
    return {
        "version": get_version(),
        "commit": get_commit_hash(),
        "branch": get_branch(),
        "dirty": get_dirty(),
        "display": f"v{get_version()} ({get_commit_hash()}{'*' if get_dirty() else ''})",
        "has_update": remote["has_update"],
        "behind_count": remote["behind_count"],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(get_version_info(), indent=2, ensure_ascii=False))