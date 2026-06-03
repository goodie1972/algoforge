"""
/api/account 路由 - 账户信息
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/account", tags=["account"])

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
