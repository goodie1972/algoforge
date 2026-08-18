"""
/api/account ��由 - ���户信息 + ��史快照
"""
import logging

from fastapi import APIRouter, HTTPException
from dashboard.backend.utils import _add_ts_fields

router = APIRouter(prefix="/api/account", tags=["account"])
logger = logging.getLogger(__name__)

engine_runner = None
run_bridge = None


@router.get("")
async def get_account():
    """获取 MT4 ���户信息（从广播��存读取，不直接走��接��免����）"""
    if not engine_runner:
        return None
    cached = engine_runner._cached_account
    if not cached:
        return None
    # ��加 _ts 后��的 Unix 时间��字段
    return _add_ts_fields(cached)


@router.get("/history")
async def get_account_history(limit: int = 100):
    """获取��户余��/��值历史"""
    try:
        from data import database as db
        snapshots = db.get_account_history(limit=min(limit, 500))
        return snapshots
    except Exception as e:
        raise HTTPException(500, f"获取��户历史失败: {e}")


@router.get("/latest")
async def get_latest_account():
    """获取最新��户快照"""
    try:
        from data import database as db
        snapshots = db.get_account_history(limit=1)
        if not snapshots:
            raise HTTPException(404, "��无��户快照")
        return snapshots[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"获取最新��户快照失败: {e}")