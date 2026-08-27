"""
自动更新核心模块
================
管理整个热更新/冷更新生命周期：预下载 → 应用 → 健康检查 → 回滚

目录结构：
    updates/
        current/    → 当前运行版本的代码快照（每次 apply 前备份）
        backup/     → 上一个版本快照（回滚用）
        pending/    → 预下载的新版本（待确认应用）

状态机：
    idle → fetching → pending → applying → restarting → healthy | rolling_back → idle
"""
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UPDATES_DIR = BASE_DIR / "updates"
CURRENT_DIR = UPDATES_DIR / "current"
BACKUP_DIR = UPDATES_DIR / "backup"
PENDING_DIR = UPDATES_DIR / "pending"
STATE_FILE = UPDATES_DIR / "state.json"
AUTO_UPDATE_CONFIG_FILE = UPDATES_DIR / "config.json"

# 状态值
STATE_IDLE = "idle"
STATE_FETCHING = "fetching"
STATE_PENDING = "pending"
STATE_APPLYING = "applying"
STATE_RESTARTING = "restarting"
STATE_HEALTHY = "healthy"
STATE_ROLLING_BACK = "rolling_back"

# 默认配置
DEFAULT_CONFIG = {
    "auto_update_enabled": True,
    "update_interval_hours": 1,
    "health_check_timeout_seconds": 60,
}


def _ensure_dirs():
    for d in [UPDATES_DIR, CURRENT_DIR, BACKUP_DIR, PENDING_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def get_config() -> dict:
    _ensure_dirs()
    if AUTO_UPDATE_CONFIG_FILE.exists():
        try:
            return json.loads(AUTO_UPDATE_CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    config = dict(DEFAULT_CONFIG)
    save_config(config)
    return config


def save_config(config: dict):
    _ensure_dirs()
    AUTO_UPDATE_CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_state() -> dict:
    _ensure_dirs()
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            # 始终从 VERSION 文件刷新 current_version，避免缓存过期
            state["current_version"] = _get_local_version()
            return state
        except (json.JSONDecodeError, OSError):
            pass
    state = {
        "state": STATE_IDLE,
        "current_version": _get_local_version(),
        "remote_version": None,
        "remote_commit": None,
        "remote_ahead": 0,
        "last_check_at": None,
        "pending_path": None,
        "message": None,
        "error": None,
    }
    save_state(state)
    return state


def save_state(state: dict):
    _ensure_dirs()
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_local_version() -> str:
    from core.version import get_version
    return get_version()


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(BASE_DIR), *args],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _copy_repo(dst: Path):
    """把当前 repo 完整拷贝到 dst（排除 .git/.DS_Store/__pycache__）"""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    skip_dirs = {'.git', '__pycache__', 'node_modules', '.pytest_cache', 'dist', '.env'}
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        rel = os.path.relpath(root, BASE_DIR)
        if rel == '.':
            continue
        dest = dst / rel
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            src = Path(root) / f
            dest_file = dest / f
            shutil.copy2(src, dest_file)


def fetch_remote() -> dict:
    """后台预下载：git fetch → 拷贝到 pending → 更新状态"""
    config = get_config()
    state = get_state()
    state["state"] = STATE_FETCHING
    state["error"] = None
    save_state(state)

    try:
        # 1. git fetch
        fetch_out = subprocess.run(
            ["git", "-C", str(BASE_DIR), "fetch", "origin", "--quiet"],
            capture_output=True, text=True, timeout=30,
        )
        if fetch_out.returncode != 0:
            raise RuntimeError(f"git fetch failed: {fetch_out.stderr.strip()}")

        # 2. 比较版本
        behind = _git("rev-list", "--count", "HEAD..origin/main")
        ahead_count = int(behind) if behind.isdigit() else 0

        if ahead_count == 0:
            state["state"] = STATE_IDLE
            state["message"] = "已是最新版本"
            save_state(state)
            return state

        remote_version = _git("show", "-s", "--format=%cs", "origin/main")
        remote_commit = _git("rev-parse", "--short", "origin/main")

        # 3. 预下载到 pending
        state["state"] = STATE_FETCHING
        state["remote_version"] = remote_version
        state["remote_commit"] = remote_commit
        state["remote_ahead"] = ahead_count
        save_state(state)

        _copy_repo(PENDING_DIR)
        # 在 pending 里执行 git checkout origin/main 以获得最新代码
        subprocess.run(
            ["git", "checkout", "-f", "origin/main"],
            capture_output=True, text=True, timeout=10,
            cwd=str(PENDING_DIR),
        )

        state["state"] = STATE_PENDING
        state["pending_path"] = str(PENDING_DIR)
        state["message"] = f"新版本 v{remote_version} 已预下载（{ahead_count} 个 commit）"
        state["last_check_at"] = datetime.now(timezone.utc).isoformat()
        save_state(state)

        return state

    except Exception as e:
        state["state"] = STATE_IDLE
        state["error"] = str(e)
        save_state(state)
        return state


def apply_update() -> dict:
    """应用更新：backup ← current, current ← pending, 标记重启"""
    state = get_state()
    if state.get("state") != STATE_PENDING:
        return {"success": False, "message": "没有待应用的更新"}

    state["state"] = STATE_APPLYING
    save_state(state)

    try:
        # 1. 备份当前版本
        if CURRENT_DIR.exists():
            shutil.rmtree(BACKUP_DIR)
        shutil.copytree(CURRENT_DIR, BACKUP_DIR)

        # 2. 应用新版本
        if CURRENT_DIR.exists():
            shutil.rmtree(CURRENT_DIR)
        shutil.copytree(PENDING_DIR, CURRENT_DIR)

        # 3. 清除 pending
        shutil.rmtree(PENDING_DIR, ignore_errors=True)

        # 4. 标记重启
        state["state"] = STATE_RESTARTING
        state["message"] = "更新已应用，正在重启"
        save_state(state)

        return {"success": True, "state": state}

    except Exception as e:
        state["state"] = STATE_IDLE
        state["error"] = str(e)
        save_state(state)
        return {"success": False, "message": f"更新失败: {e}"}


def rollback() -> dict:
    """回滚到上一个版本"""
    state = get_state()
    state["state"] = STATE_ROLLING_BACK
    save_state(state)

    try:
        if not BACKUP_DIR.exists():
            raise RuntimeError("没有可回滚的备份")

        if CURRENT_DIR.exists():
            shutil.rmtree(CURRENT_DIR)
        shutil.copytree(BACKUP_DIR, CURRENT_DIR)

        state["state"] = STATE_RESTARTING
        state["message"] = "已回滚到上一个版本，正在重启"
        save_state(state)

        return {"success": True, "state": state}

    except Exception as e:
        state["state"] = STATE_IDLE
        state["error"] = str(e)
        save_state(state)
        return {"success": False, "message": f"回滚失败: {e}"}


def check_cold_update() -> dict | None:
    """冷启动时检查是否有预下载的更新需要自动应用"""
    state = get_state()
    if PENDING_DIR.exists():
        # 自动应用
        result = apply_update()
        if result.get("success"):
            return result
    return None


def health_check() -> bool:
    """健康检查：确认更新后系统正常运行"""
    # 简化版：检查 backend API 是否可达
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://127.0.0.1:1783/api/engine/status", timeout=5)
        data = json.loads(resp.read())
        return data.get("status") == "running" and data.get("bridge_connected")
    except Exception:
        return False


def health_check_loop():
    """后台健康检查循环，更新后自动判断是否需要回滚"""
    config = get_config()
    timeout = config.get("health_check_timeout_seconds", 60)
    start = time.time()

    while time.time() - start < timeout:
        time.sleep(5)
        if health_check():
            state = get_state()
            state["state"] = STATE_HEALTHY
            state["message"] = "更新成功，系统健康"
            save_state(state)
            return True

    # 超时未恢复 → 自动回滚
    rollback()
    return False
