"""
/api/logs 路由 - 日志查询（优先 DB，回退内存）
"""
from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/api/logs", tags=["logs"])

log_handler = None


@router.get("")
async def get_logs(
    level: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=2000),
    since: Optional[str] = Query(default=None),
):
    """获取最近的日志记录（优先数据库查询）"""
    # 先尝试从数据库读取
    try:
        from data import database as db
        db_logs = db.get_logs(level=level, since=since, limit=limit)
        if db_logs:
            return {"total": len(db_logs), "logs": db_logs}
    except Exception:
        pass

    # 回退到内存环形缓冲区
    if not log_handler:
        return {"total": 0, "logs": []}
    records = log_handler.get_recent(level=level, limit=limit, since=since)
    return {"total": len(records), "logs": records}
