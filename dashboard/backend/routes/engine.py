"""
/api/engine/* 路由 - 引擎启停和状态查询
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/engine", tags=["engine"])

# 由 main.py 在启动时注入
engine_runner = None


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
