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
