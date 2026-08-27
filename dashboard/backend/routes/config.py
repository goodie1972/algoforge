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


class StrategyPoolUpdate(BaseModel):
    pool: dict[str, dict]


class CoordinatorUpdate(BaseModel):
    config: dict


class PaperConfigUpdate(BaseModel):
    config: dict


@router.get("/strategy-pool")
async def get_strategy_pool():
    """获取策略池配置（在 /{key} 之前注册，避免被捕获）"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    return config_service.get_strategy_pool()


@router.get("/coordinator")
async def get_coordinator():
    """获取协调器配置"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    return config_service.get_coordinator_config()


@router.post("/coordinator")
async def update_coordinator(req: CoordinatorUpdate):
    """更新协调器配置"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    try:
        updated = config_service.set_coordinator_config(req.config)
        return {"message": "协调器已更新", "config": updated}
    except Exception as e:
        raise HTTPException(422, f"协调器更新失败: {e}")


@router.get("")
async def get_config():
    """获取完整运行时配置"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    return config_service.get_all()


@router.get("/paper")
async def get_paper_config():
    """获取纸面交易配置"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    return config_service.get_paper_config()


def _sanitize_paper_config(cfg: dict) -> dict:
    """对纸面配置的数值字段做强制转换与校验

    前端 n-select 带 tag 允许自定义输入，可能产生字符串值（如 "0.03"）；
    落盘后引擎下单/浮盈计算依赖数值类型，必须在入口拦截，否则纸面交易瘫痪。
    enabled / ignore_gates 等其余字段原样透传。
    """
    cfg = dict(cfg)
    if "lot_size" in cfg:
        try:
            lot = float(cfg["lot_size"])
        except (TypeError, ValueError):
            raise HTTPException(422, f"lot_size 必须是数值: {cfg['lot_size']!r}")
        if lot != lot or lot <= 0:
            raise HTTPException(422, f"lot_size 必须大于 0: {cfg['lot_size']!r}")
        cfg["lot_size"] = lot
    for key in ("initial_balance", "max_positions", "total_max_positions"):
        if key not in cfg:
            continue
        raw = cfg[key]
        try:
            num = float(raw)
        except (TypeError, ValueError):
            raise HTTPException(422, f"{key} 必须是数值: {raw!r}")
        if num != num or num < 0:
            raise HTTPException(422, f"{key} 必须 >= 0: {raw!r}")
        cfg[key] = int(num) if num == int(num) else num
    return cfg


@router.post("/paper")
async def update_paper_config(req: PaperConfigUpdate):
    """更新纸面交易配置

    若 paper_trading.enabled 发生翻转（保存前后对比），响应中附带
    mode_switch=true 与提示 message，通知前端提示用户确认重启；
    前端确认后调用 POST /api/engine/restart 完成重启。本接口不自动重启。
    """
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    # 数值字段强制转换/校验放在 try 外，保留清晰的 422 错误信息
    cfg = _sanitize_paper_config(req.config)
    try:
        enabled_before = bool(config_service.get_paper_config().get("enabled", False))
        updated = config_service.set_paper_config(cfg)
        enabled_after = bool(updated.get("enabled", False))
        resp = {"message": "纸面配置已更新", "config": updated}
        if enabled_after != enabled_before:
            # 引擎执行模式（纸面/实盘桥接）在启动时一次性构建，模式切换必须重启引擎
            resp["mode_switch"] = True
            resp["message"] = "切换模式将重启引擎"
        return resp
    except Exception as e:
        raise HTTPException(422, f"纸面配置更新失败: {e}")


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
        updated = config_service.update(req.updates)
        # 语言切换时清除日志缓存
        if 'language' in req.updates:
            try:
                from services.log_messages import clear_lang_cache
                clear_lang_cache()
            except ImportError:
                pass
        return {"message": "配置已更新", "updated": updated}
    except Exception as e:
        raise HTTPException(422, f"配置更新失败: {e}")


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


@router.get("/active")
async def get_active_config():
    """返回引擎当前实际使用的配置（合并 defaults + overrides）"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    return config_service.get_active()


@router.post("/reset")
async def reset_config(key: Optional[str] = None):
    """重置配置（指定 key 或全部）"""
    if not config_service:
        raise HTTPException(500, "配置服务未初始化")
    config_service.reset(key)
    if key:
        return {"message": f"配置项 {key} 已重置"}
    return {"message": "所有配置已重置"}
