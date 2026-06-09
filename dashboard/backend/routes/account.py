"""
/api/account 路由 - 账户信息 + 历史快照
"""
import logging

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/account", tags=["account"])
logger = logging.getLogger(__name__)

engine_runner = None
run_bridge = None


@router.get("")
async def get_account():
    """获取 MT4 账户信息（从广播缓存读取，不直接走桥接避免抢锁）"""
    if not engine_runner:
        return None
    cached = engine_runner._cached_account
    if not cached:
        return None
    return cached


@router.get("/history")
async def get_account_history(limit: int = 100):
    """获取账户余额/净值历史"""
    try:
        from data import database as db
        snapshots = db.get_account_history(limit=min(limit, 500))
        return snapshots
    except Exception as e:
        raise HTTPException(500, f"获取账户历史失败: {e}")


@router.get("/latest")
async def get_latest_account():
    """获取最新账户快照"""
    try:
        from data import database as db
        snapshots = db.get_account_history(limit=1)
        if not snapshots:
            raise HTTPException(404, "暂无账户快照")
        return snapshots[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"获取最新账户快照失败: {e}")
