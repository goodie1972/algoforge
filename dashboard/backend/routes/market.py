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
    count: int = Query(default=100, le=1000, ge=10),
):
    """获取 K 线数据"""
    if not engine_runner or not engine_runner.bridge:
        return []
    try:
        candles = await run_bridge(engine_runner.bridge.get_candles, settings.SYMBOL, timeframe, count)
        # MT4 返回最新在前，lightweight-charts 要求最旧在前
        candles = list(reversed(candles))
        return [
            {
                "time": int(c.time),
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
