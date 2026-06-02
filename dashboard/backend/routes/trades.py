"""
/api/trades 路由 - 历史成交记录查询
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/trades", tags=["trades"])

engine_runner = None


@router.get("/history")
async def get_trade_history(limit: int = 100):
    """获取最近 N 条已平仓记录"""
    if not engine_runner or not engine_runner._engine:
        return []
    try:
        trades = engine_runner._engine.closed_trades
        return trades[-limit:]
    except Exception as e:
        raise HTTPException(502, f"获取历史成交失败: {e}")
