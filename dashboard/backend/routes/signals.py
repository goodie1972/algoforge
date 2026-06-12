"""
/api/signals 路由 - 策略信号历史查询
"""
import logging

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/signals", tags=["signals"])
logger = logging.getLogger(__name__)


@router.get("")
async def get_signals(strategy: str = "", status: str = "", limit: int = 50):
    """查询信号历史，可按 status 过滤"""
    try:
        from data import database as db
        if status:
            signals = db.get_signals_by_status(status, limit=min(limit, 200))
        else:
            signals = db.get_signals(strategy=strategy or None, limit=min(limit, 200))
        return signals
    except Exception as e:
        raise HTTPException(500, f"获取信号历史失败: {e}")


@router.get("/latest")
async def get_latest_signal(strategy: str = ""):
    """查询某策略最新信号及因子详情"""
    if not strategy:
        raise HTTPException(400, "请指定策略名")
    try:
        from data import database as db
        sig = db.get_latest_signal(strategy)
        if sig is None:
            raise HTTPException(404, f"未找到 {strategy} 的信号记录")
        return sig
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"获取最新信号失败: {e}")
