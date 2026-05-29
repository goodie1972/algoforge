"""
/api/logs 路由 - 日志查询
"""
from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/api/logs", tags=["logs"])

# 由 main.py 注入的日志捕获处理器
log_handler = None


@router.get("")
async def get_logs(
    level: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=2000),
    since: Optional[str] = Query(default=None),
):
    """获取最近的日志记录"""
    if not log_handler:
        return {"total": 0, "logs": []}
    records = log_handler.get_recent(level=level, limit=limit, since=since)
    return {"total": len(records), "logs": records}
