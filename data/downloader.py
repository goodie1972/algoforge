"""
MT4 → SQLite 历史数据下载器
独立运行：python data/downloader.py
也可作为模块导入，由引擎启动时自动调用
"""
import logging
import os
import sys
import time
from datetime import datetime, timezone

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.bridge import create_bridge
from data.database import (
    init_db, get_latest_timestamp, insert_candles,
    get_db_stats, TIMEFRAMES,
)

logger = logging.getLogger("data.downloader")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
logger.addHandler(handler)

# 每个周期最多拉取多少根
MAX_CANDLES = {
    "M1": 10000, "M5": 10000, "M15": 5000, "M30": 5000,
    "H1": 3000, "H4": 2000, "D1": 1000, "W1": 500,
}

# 每个周期首次拉取的数量（数据库为空时使用）
INITIAL_COUNT = {
    "M1": 5000, "M5": 5000, "M15": 3000, "M30": 2000,
    "H1": 1000, "H4": 800, "D1": 500, "W1": 200,
}


def download_timeframe(bridge, timeframe: str, symbol: str = "XAUUSD") -> int:
    """下载单个周期数据，返回写入条数"""
    latest = get_latest_timestamp(timeframe)
    now_ts = int(time.time())

    if latest:
        # 增量更新：计算需要多少根覆盖从 latest 到现在
        tf_seconds = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                      "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}
        gap = now_ts - latest
        needed = max(10, min(MAX_CANDLES.get(timeframe, 1000), gap // tf_seconds.get(timeframe, 3600) + 5))
        logger.info(f"[{timeframe}] 已有数据到 {datetime.fromtimestamp(latest, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}，增量拉取 {needed} 根")
    else:
        needed = INITIAL_COUNT.get(timeframe, 1000)
        logger.info(f"[{timeframe}] 首次下载，拉取 {needed} 根")

    candles = bridge.get_candles(symbol, timeframe, needed)
    if not candles:
        logger.warning(f"[{timeframe}] 未获取到数据")
        return 0

    count_before = 0
    try:
        from data.database import get_candle_count
        count_before = get_candle_count(timeframe)
    except Exception:
        pass

    inserted = insert_candles(timeframe, candles)
    logger.info(f"[{timeframe}] 获取 {len(candles)} 根，写入 {inserted} 条（库中原有 {count_before} 条）")
    return inserted


def download_all(symbol: str = "XAUUSD", timeframes: list[str] | None = None) -> dict:
    """下载所有周期数据"""
    if timeframes is None:
        timeframes = TIMEFRAMES

    init_db()

    bridge = create_bridge()
    logger.info("连接 MT4...")
    if not bridge.connect():
        logger.error("无法连接 MT4，下载失败")
        return {"error": "MT4 未连接"}

    results = {}
    for tf in timeframes:
        try:
            n = download_timeframe(bridge, tf, symbol)
            results[tf] = n
        except Exception as e:
            logger.error(f"[{tf}] 下载失败: {e}")
            results[tf] = 0

    bridge.disconnect()

    logger.info("\n=== 下载完成 ===")
    stats = get_db_stats()
    for tf, info in stats.items():
        if info["count"] > 0:
            logger.info(f"  {tf}: {info['count']} 条 ({info['from']} ~ {info['to']})")

    return {"results": results, "stats": stats}


if __name__ == "__main__":
    download_all()
