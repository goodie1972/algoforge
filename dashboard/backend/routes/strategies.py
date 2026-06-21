"""
/api/strategies 路由 — 策略发现
"""
from fastapi import APIRouter
from dashboard.backend.strategy_registry import get_available_strategies

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("/available")
async def list_available():
    """返回所有可实盘交易的策略清单（含 backup 规范名、默认参数）"""
    return {"strategies": get_available_strategies()}
