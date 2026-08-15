"""
版本信息路由
============
GET /api/version        — 返回项目版本、git commit、分支、构建时间
GET /api/version/changelog — 返回最近 20 条 commit 简述（自动从 git log 解析）
"""
import subprocess
from pathlib import Path

from fastapi import APIRouter

from core.version import get_version_info

router = APIRouter(prefix="/api/version", tags=["version"])

BASE_DIR = Path(__file__).resolve().parents[2]


@router.get("")
async def get_version():
    return get_version_info()


@router.get("/changelog")
async def get_changelog(limit: int = 20):
    """从 git log 自动生成最近 N 条 commit 简述"""
    try:
        # encoding='utf-8' + errors='replace' 避免 Windows GBK 在中文 commit 上抛异常
        out = subprocess.run(
            ["git", "-C", str(BASE_DIR), "log",
             f"-{limit}", "--pretty=format:%h|%ai|%s"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        if out.returncode != 0:
            return {"commits": [], "error": out.stderr.strip()}
        commits = []
        for line in out.stdout.splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            commits.append({
                "hash": parts[0],
                "date": parts[1],
                "subject": parts[2],
            })
        return {"commits": commits}
    except Exception as e:
        return {"commits": [], "error": str(e)}


@router.get("/remote-changelog")
async def get_remote_changelog(limit: int = 20):
    """获取远程有但本地没有的 commit 列表"""
    from core.version import get_remote_changelog as _remote_log
    return {"commits": _remote_log(limit)}


@router.post("/update")
async def update_version():
    """触发更新应用（当前页面自动关闭后生效）"""
    from dashboard.backend.auto_update import apply_update
    return apply_update()


@router.post("/rollback")
async def rollback_version():
    """回滚到上一个版本"""
    from dashboard.backend.auto_update import rollback
    return rollback()


@router.get("/update-config")
async def get_update_config():
    """获取/设置自动更新配置"""
    from dashboard.backend.auto_update import get_config
    return get_config()


@router.post("/update-config")
async def set_update_config(data: dict):
    """更新自动更新配置（前端拨动键写入）"""
    from dashboard.backend.auto_update import save_config, get_config
    config = get_config()
    for k in ("auto_update_enabled", "update_interval_hours"):
        if k in data:
            config[k] = data[k]
    save_config(config)
    return config


@router.get("/update-state")
async def get_update_state():
    """获取当前更新状态"""
    from dashboard.backend.auto_update import get_state
    return get_state()


@router.post("/update/health")
async def run_health_check():
    """手动触发一次健康检查"""
    from dashboard.backend.auto_update import health_check
    return {"healthy": health_check()}


@router.get("/bias-state")
async def get_bias_state():
    """返回当前引擎缓存的最新 news-bias 方向（用于 Dashboard 显示 + 调试）"""
    from core import bias_state
    return bias_state.get_full()


@router.post("/bias-state/refresh")
async def force_refresh_bias():
    """手动触发一次 DB 刷新（用于测试 / 报告刚生成后立即生效）"""
    from core import bias_state
    new_dir = bias_state.refresh_from_db()
    return {"direction": new_dir, "full": bias_state.get_full()}
