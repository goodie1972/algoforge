"""
MT4 → SQLite 历史数据下载器
独立运行：python data/downloader.py
也可作为模块导入，由引擎启动时自动调用

架构说明：
  - download_timeframe() — 引擎用的增量同步，只拉最新缺口
  - download_timeframe_paged() — 全量分页回填，用 offset 逐页拉至 2024
  - download_all_paged() — 所有周期全量回填入口
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

# 每页最多拉取多少根
PAGE_SIZE = {
    "M1": 10000, "M5": 10000, "M15": 5000, "M30": 5000,
    "H1": 3000, "H4": 2000, "D1": 1600, "W1": 1600,
}

# 每个周期的秒数
TF_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800,
}

# 目标：回填到 2024-01-01 00:00:00 UTC
TARGET_TS = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())


def download_timeframe(bridge, timeframe: str, symbol: str = "XAUUSD") -> int:
    """增量同步（引擎用）：只拉最新缺口，不回溯历史"""
    latest = get_latest_timestamp(timeframe)
    now_ts = int(time.time())

    if latest:
        gap = now_ts - latest
        needed = max(10, min(PAGE_SIZE.get(timeframe, 1000), gap // TF_SECONDS.get(timeframe, 3600) + 5))
        logger.info(f"[{timeframe}] 增量同步: 已有 {datetime.fromtimestamp(latest, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}，拉取 {needed} 根")
    else:
        needed = PAGE_SIZE.get(timeframe, 1000)
        logger.info(f"[{timeframe}] 首次初始下载，拉取 {needed} 根")

    candles = bridge.get_candles(symbol, timeframe, needed)
    if not candles:
        logger.warning(f"[{timeframe}] 未获取到数据")
        return 0

    inserted = insert_candles(timeframe, candles)
    logger.info(f"[{timeframe}] 增量写完 {inserted} 条")
    return inserted


def download_timeframe_paged(bridge, timeframe: str, symbol: str = "XAUUSD",
                              target_ts: int = TARGET_TS,
                              page_size: int | None = None) -> int:
    """全量分页下载：从最新开始，逐页往前拉，直到覆盖到 target_ts"""
    page_size = page_size or PAGE_SIZE.get(timeframe, 5000)
    total_fetched = 0
    offset = 0
    max_pages = 200  # 安全上限
    earliest_ts = int(time.time())

    logger.info(f"[{timeframe}] 开始全量分页回填（目标: {datetime.fromtimestamp(target_ts, tz=timezone.utc).strftime('%Y-%m-%d')}）")

    for page in range(max_pages):
        candles = bridge.get_candles(symbol, timeframe, page_size, offset=offset)
        if not candles:
            logger.info(f"[{timeframe}] offset={offset} → 无数据，分页结束")
            break

        # 找本页最老的那根
        for c in candles:
            ts = int(c.time)
            if ts < earliest_ts:
                earliest_ts = ts

        total_fetched += len(candles)
        logger.info(f"[{timeframe}] 第{page+1}页 offset={offset} 获取 {len(candles)} 根 "
                    f"(最老: {datetime.fromtimestamp(earliest_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')})")

        # 如果最老的已经覆盖到目标时间，停止
        if earliest_ts <= target_ts:
            logger.info(f"[{timeframe}] 已覆盖到 {datetime.fromtimestamp(earliest_ts, tz=timezone.utc).strftime('%Y-%m-%d')}，完成回填")
            break

        # 下移 offset
        offset += len(candles)
        time.sleep(0.2)  # 不要打爆 EA

    if total_fetched == 0:
        logger.warning(f"[{timeframe}] 分页下载未获取到任何数据")
        return 0

    # 全部插入（INSERT OR IGNORE 去重）
    # 注意：要做一次全量重新获取，因为上面的循环只向后翻没存
    # 重新拉取所有数据并插入
    inserted = _fetch_and_insert_all_pages(bridge, timeframe, symbol, page_size, target_ts)
    logger.info(f"[{timeframe}] 全量回填完成: 总计获取 ~{total_fetched}+ 根，写入 {inserted} 条")
    return inserted


def _fetch_and_insert_all_pages(bridge, timeframe: str, symbol: str,
                                 page_size: int, target_ts: int) -> int:
    """从 offset=0 开始逐页拉取并插入，直到覆盖 target_ts"""
    offset = 0
    total_inserted = 0
    max_pages = 200

    for page in range(max_pages):
        candles = bridge.get_candles(symbol, timeframe, page_size, offset=offset)
        if not candles:
            break

        inserted = insert_candles(timeframe, candles)
        total_inserted += inserted

        earliest_ts = min(int(c.time) for c in candles)
        logger.info(f"[{timeframe}] 第{page+1}页 offset={offset} → 获取{len(candles)}根 "
                    f"写入{inserted}条 最老:{datetime.fromtimestamp(earliest_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}")

        if earliest_ts <= target_ts:
            break

        offset += len(candles)
        time.sleep(0.2)

    return total_inserted


def download_all(symbol: str = "XAUUSD", timeframes: list[str] | None = None) -> dict:
    """增量下载所有周期（引擎传统入口）"""
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


def download_all_paged(symbol: str = "XAUUSD",
                        timeframes: list[str] | None = None,
                        target_ts: int = TARGET_TS) -> dict:
    """全量分页下载所有周期（覆盖到 target_ts 的完整历史）"""
    if timeframes is None:
        # 默认只做回测需要的周期
        timeframes = ["M15", "M30", "H1", "H4", "D1"]

    init_db()
    bridge = create_bridge()
    logger.info("连接 MT4...")
    if not bridge.connect():
        logger.error("无法连接 MT4，下载失败（引擎可能正占用桥接）")
        return {"error": "MT4 未连接，请先停止引擎"}

    results = {}
    for tf in timeframes:
        try:
            n = download_timeframe_paged(bridge, tf, symbol, target_ts)
            results[tf] = n
        except Exception as e:
            logger.error(f"[{tf}] 分页下载失败: {e}")
            results[tf] = 0

    bridge.disconnect()

    logger.info("\n=== 全量回填完成 ===")
    stats = get_db_stats()
    for tf, info in stats.items():
        if info["count"] > 0:
            logger.info(f"  {tf}: {info['count']} 条 ({info['from']} ~ {info['to']})")

    return {"results": results, "stats": stats}


if __name__ == "__main__":
    download_all_paged()
