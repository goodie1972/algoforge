"""
版本信息读取
================
- 从项目根的 VERSION 文件读取 semver
- 从 git 命令获取当前 commit hash 和分支
- 提供统一的 get_version() / get_version_info() 供后端 API、start.py、Dashboard 共用
"""
import subprocess
import threading
import time
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


# 远程更新检查缓存（避免同步 fetch 导致前端/启动阻塞）
_remote_update_cache: dict | None = None
_remote_update_cache_time: float = 0
_REMOTE_CACHE_TTL = 300  # 5分钟缓存


def check_remote_update() -> dict:
    """检查远程是否有新版本（带缓存，避免网络阻塞）。

    首次调用若无缓存，立即返回"无更新"（不 fetch），
    由 start_background_update_check() 在后台线程填充真实结果。
    """
    global _remote_update_cache, _remote_update_cache_time
    now = time.time()

    if _remote_update_cache and (now - _remote_update_cache_time) < _REMOTE_CACHE_TTL:
        return _remote_update_cache

    # 无缓存：先返回"无更新"，避免阻塞 API / 启动
    return {"has_update": False, "behind_count": 0}


def _fetch_remote_update() -> dict:
    """真正执行 git fetch 并计算落后 commit 数（后台线程调用）"""
    global _remote_update_cache, _remote_update_cache_time
    try:
        subprocess.run(
            ["git", "-C", str(BASE_DIR), "fetch", "origin", "--quiet"],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass  # 忽略网络错误，使用已有的 refs

    behind = _git("rev-list", "--count", "HEAD..origin/main")
    count = int(behind) if behind.isdigit() else 0

    _remote_update_cache = {
        "has_update": count > 0,
        "behind_count": count,
    }
    _remote_update_cache_time = time.time()
    return _remote_update_cache


def start_background_update_check(delay: float = 15.0) -> threading.Thread:
    """启动后台线程延迟执行远程更新检查，避免阻塞后端启动和首屏 API。

    Args:
        delay: 启动后多少秒再执行首次检查（默认 15s，等系统稳定）
    """
    def _worker():
        time.sleep(delay)
        if _remote_update_cache:
            return  # 已有缓存（其他路径触发过），跳过
        try:
            _fetch_remote_update()
        except Exception:
            pass

    t = threading.Thread(target=_worker, daemon=True, name="remote_update_check")
    t.start()
    return t


def get_version_info() -> dict:
    """返回 Dashboard / start.py 需要的完整版本信息（不阻塞：不在此处 fetch）"""
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