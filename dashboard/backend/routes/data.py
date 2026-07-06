"""
/api/data 路由 - 历史数据下载与管理
"""
import logging

from fastapi import APIRouter, Query

from data import database as db

router = APIRouter(prefix="/api/data", tags=["data"])
logger = logging.getLogger(__name__)

engine_runner = None
run_bridge = None


@router.get("/status")
async def data_status():
    """查询数据库状态"""
    return {
        "initialized": True,
        "db_path": db.DB_PATH,
        "stats": db.get_db_stats(),
    }


@router.post("/download")
async def trigger_download(
    timeframe: str = Query(default="", description="周期，为空则下载所有"),
    symbol: str = Query(default="XAUUSD"),
):
    """从 MT4 下载历史数据到 SQLite"""
    if not engine_runner or not engine_runner.bridge:
        return {"error": "引擎未运行或桥接未连接"}
    if not engine_runner.is_running:
        return {"error": "引擎未运行"}

    db.init_db()

    timeframes = [timeframe] if timeframe else db.TIMEFRAMES
    results = {}

    for tf in timeframes:
        try:
            latest = db.get_latest_timestamp(tf)

            # 计算需要的数量
            import time
            now_ts = int(time.time())
            max_count = {
                "M1": 10000, "M5": 10000, "M15": 5000, "M30": 5000,
                "H1": 3000, "H4": 2000, "D1": 1000, "W1": 500,
            }
            initial_count = {
                "M1": 5000, "M5": 5000, "M15": 3000, "M30": 2000,
                "H1": 1000, "H4": 800, "D1": 500, "W1": 200,
            }

            if latest:
                tf_sec = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                          "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}
                gap = now_ts - latest
                needed = max(10, min(max_count.get(tf, 1000), gap // tf_sec.get(tf, 3600) + 5))
            else:
                needed = initial_count.get(tf, 1000)

            candles = await run_bridge(engine_runner.bridge.get_candles, symbol, tf, needed)
            if not candles:
                results[tf] = {"status": "no_data", "inserted": 0}
                continue

            inserted = db.insert_candles(tf, candles)
            count = db.get_candle_count(tf)
            results[tf] = {
                "status": "ok",
                "fetched": len(candles),
                "inserted": inserted,
                "total": count,
            }
        except Exception as e:
            logger.exception(f"[{tf}] 下载失败")
            results[tf] = {"status": "error", "error": str(e)}

    return {
        "symbol": symbol,
        "results": results,
        "stats": db.get_db_stats(),
    }


@router.get("/candles")
async def get_candles(
    timeframe: str = Query(default="H1"),
    limit: int = Query(default=500, le=5000),
    start_ts: int = Query(default=0),
    end_ts: int = Query(default=0),
):
    """从 SQLite 读取 K 线"""
    return db.get_candles(timeframe, start_ts, end_ts, limit)


@router.get("/indicators")
async def get_data_factory_indicators(
    timeframe: str = Query(default="M30"),
):
    """返回数据工厂缓存中该周期的全部预计算指标（TA-Lib 统一计算）"""
    try:
        from services.data_factory import get_cache
        cache = get_cache(timeframe)
        if not cache:
            return {"error": f"周期 {timeframe} 缓存未就绪"}
        # 去掉 candles（太大），只返回指标
        result = {k: v for k, v in cache.items() if k != "candles"}
        return result
    except Exception as e:
        return {"error": str(e)}
