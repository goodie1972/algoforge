"""
/api/config 路由 - 运行时配置管理
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

router = APIRouter(prefix="/api/config", tags=["config"])

config_service = None


class ConfigUpdate(BaseModel):
    updates: dict[str, Any]


@router.get("")
async def get_config():
    """获取完整运行时配置"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    return config_service.get_all()


@router.get("/{key}")
async def get_config_key(key: str):
    """获取单个配置项"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    value = config_service.get(key)
    if value is None:
        raise HTTPException(404, f"未知配置项: {key}")
    return {"key": key, "value": value}


@router.post("")
async def update_config(req: ConfigUpdate):
    """更新配置项"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    try:
        updated = config_service.set_many(req.updates)
        return {"message": "配置已更新", "updated": updated}
    except Exception as e:
        raise HTTPException(422, f"配置更新失败: {e}")


@router.get("/strategy-pool")
async def get_strategy_pool():
    """获取策略池配置"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    return config_service.get_strategy_pool()


class StrategyPoolUpdate(BaseModel):
    pool: dict[str, dict]


@router.post("/strategy-pool")
async def update_strategy_pool(req: StrategyPoolUpdate):
    """更新策略池配置"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    try:
        updated = config_service.set_strategy_pool(req.pool)
        return {"message": "策略池已更新", "pool": updated}
    except Exception as e:
        raise HTTPException(422, f"策略池更新失败: {e}")


@router.post("/reset")
async def reset_config(key: Optional[str] = None):
    """重置配置（指定 key 或全部）"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    config_service.reset(key)
    if key:
        return {"message": f"配置项 {key} 已重置"}
    return {"message": "所有配置已重置"}
