"""
/api/engine/* 路由 - 引擎启停、状态查询、动态策略管理
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/engine", tags=["engine"])

# 由 main.py 在启动时注入
engine_runner = None
# 由 main.py 注入 STRATEGY_MAP 的 name→label 信息
available_strategies: dict = {}


class AddStrategyRequest(BaseModel):
    name: str
    config: dict


class RemoveStrategyRequest(BaseModel):
    name: str
    close_positions: bool = True


@router.get("/status")
async def get_status():
    """获取引擎运行状态"""
    if not engine_runner:
        return {"status": "uninitialized", "uptime_seconds": 0}
    return engine_runner.get_status()


@router.post("/start")
async def start_engine():
    """启动交易引擎"""
    if not engine_runner:
        raise HTTPException(500, "引擎未初始化")
    if engine_runner.is_running:
        raise HTTPException(409, "引擎已在运行中")
    ok = engine_runner.start()
    if not ok:
        raise HTTPException(500, "引擎启动失败，请检查 MT4 连接")
    return {"message": "引擎启动成功"}


@router.post("/stop")
async def stop_engine():
    """停止交易引擎"""
    if not engine_runner:
        raise HTTPException(500, "引擎未初始化")
    if not engine_runner.is_running:
        raise HTTPException(409, "引擎未在运行")
    engine_runner.stop()
    return {"message": "引擎已停止"}


@router.get("/strategies")
async def list_strategies():
    """列出当前引擎中运行的策略"""
    if not engine_runner or not engine_runner._engine:
        return {"running": [], "available": list(available_strategies.keys())}
    with engine_runner._engine._strategies_lock:
        running = [
            {"name": s.name, "magic": s.magic, "timeframe": s.timeframe,
             "double_first": s.double_first, "max_positions": s.max_positions}
            for s in engine_runner._engine.strategies
        ]
    return {"running": running, "available": list(available_strategies.keys())}


@router.post("/strategies/add")
async def add_strategy(req: AddStrategyRequest):
    """动态添加策略（无需重启引擎）"""
    if not engine_runner:
        raise HTTPException(500, "引擎未初始化")
    if not engine_runner.is_running:
        raise HTTPException(409, "引擎未在运行，请先启动")
    ok = engine_runner.add_strategy(req.name, req.config)
    if not ok:
        raise HTTPException(400, f"策略 {req.name} 添加失败（可能已存在或 Magic 冲突）")
    return {"message": f"策略 {req.name} 已添加", "config": req.config}


@router.post("/strategies/remove")
async def remove_strategy(req: RemoveStrategyRequest):
    """动态移除策略（无需重启引擎）"""
    if not engine_runner:
        raise HTTPException(500, "引擎未初始化")
    if not engine_runner.is_running:
        raise HTTPException(409, "引擎未在运行")
    ok = engine_runner.remove_strategy(req.name, req.close_positions)
    if not ok:
        raise HTTPException(404, f"策略 {req.name} 不存在")
    return {"message": f"策略 {req.name} 已移除", "closed_positions": req.close_positions}
