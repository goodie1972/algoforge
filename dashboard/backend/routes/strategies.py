"""
/api/strategies 路由 — 策略发现
"""
from fastapi import APIRouter, HTTPException
from dashboard.backend.strategy_registry import get_available_strategies
from dashboard.backend.strategy_logics import get_strategy_logics, get_strategy_logic

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("/available")
async def list_available():
    """返回所有可实盘交易的策略清单（含 backup 规范名、默认参数）"""
    return {"strategies": get_available_strategies()}


@router.get("/logics")
async def list_logics():
    """返回所有策略的进出场逻辑描述（供前端交易终端/策略中心展示）"""
    return {"logics": get_strategy_logics()}


@router.get("/{name}/logic")
async def get_strategy_logic_route(name: str):
    """返回单个策略的进出场逻辑（从 docs/strategies/ 读取）"""
    logic = get_strategy_logic(name)
    if logic is None:
        raise HTTPException(404, f"策略 {name} 的逻辑文档不存在")
    return {"logic": logic}
