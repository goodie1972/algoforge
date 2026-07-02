"""
/api/supervisor 路由 — 监督者系统 API
"""
import json
import logging
from fastapi import APIRouter

router = APIRouter(prefix="/api/supervisor", tags=["supervisor"])

logger = logging.getLogger(__name__)

# 由 Dashboard backend 注入
engine_runner = None
supervisor = None


def _get_supervisor():
    """获取监督者实例（优先路由级，次选引擎级）"""
    global supervisor
    if supervisor is not None:
        return supervisor
    if engine_runner is not None:
        sv = getattr(engine_runner, 'supervisor', None)
        if sv is not None:
            supervisor = sv
            return sv
    return None


@router.get("/overview")
async def get_overview():
    """策略健康概览"""
    sv = _get_supervisor()
    if sv is None:
        return {"error": "supervisor not initialized", "initialized": False}
    try:
        data = sv.get_overview()
        data["initialized"] = True
        return data
    except Exception as e:
        logger.error(f"获取监督概览失败: {e}")
        return {"error": str(e), "initialized": False}


@router.get("/alerts")
async def get_alerts():
    """当前告警列表"""
    sv = _get_supervisor()
    if sv is None:
        return {"alerts": []}
    try:
        return {"alerts": sv.get_alerts()}
    except Exception as e:
        logger.error(f"获取告警失败: {e}")
        return {"alerts": []}


@router.get("/strategy/{name}")
async def get_strategy_detail(name: str):
    """单策略详细分析"""
    sv = _get_supervisor()
    if sv is None:
        return {"error": "supervisor not initialized"}
    try:
        return sv.analyze_strategy(name)
    except Exception as e:
        logger.error(f"分析策略 {name} 失败: {e}")
        return {"error": str(e)}


@router.get("/history")
async def get_history(limit: int = 100):
    """近期交易事件流"""
    sv = _get_supervisor()
    if sv is None:
        return {"events": []}
    try:
        events = list(sv.trade_events)
        events.reverse()
        return {"events": events[:limit]}
    except Exception as e:
        logger.error(f"获取交易事件失败: {e}")
        return {"events": []}


@router.post("/clear-alerts")
async def clear_alerts():
    """清除已读告警"""
    sv = _get_supervisor()
    if sv is None:
        return {"ok": False}
    try:
        sv.clear_alerts()
        return {"ok": True}
    except Exception as e:
        logger.error(f"清除告警失败: {e}")
        return {"ok": False}
