"""
/api/market 路由 - 行情数据
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from config import settings

router = APIRouter(prefix="/api/market", tags=["market"])

engine_runner = None
run_bridge = None


@router.get("/price")
async def get_price():
    """获取当前买卖价（从广播缓存读取）"""
    if not engine_runner:
        return {"bid": 0, "ask": 0, "spread": 0, "symbol": settings.SYMBOL}
    cached = engine_runner._cached_price
    if cached:
        return {
            "bid": cached["bid"],
            "ask": cached["ask"],
            "spread": round(cached["ask"] - cached["bid"], 2),
            "symbol": settings.SYMBOL,
        }
    return {"bid": 0, "ask": 0, "spread": 0, "symbol": settings.SYMBOL}


@router.get("/candles")
async def get_candles(
    timeframe: str = Query(default=settings.TIMEFRAME),
    count: int = Query(default=100, le=1000, ge=3),
):
    """获取 K 线数据（从引擎实时缓存读取，最后一根已用现价扩展）"""
    if not engine_runner:
        return []
    # 优先从缓存读取（更快，且包含实时价格扩展）
    cached = engine_runner.get_cached_candles(timeframe, count)
    if cached is not None:
        return cached
    # 缓存未就绪 → 回退到桥接直接获取
    if not engine_runner.bridge:
        return []
    try:
        candles = await run_bridge(engine_runner.bridge.get_candles, settings.SYMBOL, timeframe, count)
        candles = list(reversed(candles))
        offset = int(engine_runner.mt4_offset)
        return [
            {
                "time": int(c.time) - offset,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
    except Exception as e:
        raise HTTPException(502, f"获取 K 线失败: {e}")
