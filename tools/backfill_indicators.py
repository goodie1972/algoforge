"""
tools/backfill_indicators.py — 一次性回填 indicator_snapshots 表

目的：现有 DB 中只有 30% 的 K 线有完整 46 键指标，剩下要么键不全、要么根本没存。
     MT4 历史数据保留期短，自存是回测的硬需求。
     这个脚本从 ohlcv 读 K 线，调用 _ta_only_indicators 计算全套 46 键，UPSERT 到 indicator_snapshots。

用法：
    # 回填所有时间周期（默认跳过 MN 因为 DataFactory 不收；默认含 GC_* 清理）
    python tools/backfill_indicators.py

    # 指定周期
    python tools/backfill_indicators.py --timeframes M15,H1,D1

    # 不清理 GC_* 残留
    python tools/backfill_indicators.py --keep-gc

    # 只清理 GC_*
    python tools/backfill_indicators.py --clean-gc-only

    # 干跑（仅统计，不写库）
    python tools/backfill_indicators.py --dry-run

    # 仅回填缺失键的行（保留已有 45+ 键的数据以提速）
    python tools/backfill_indicators.py --only-incomplete

预计耗时：~30-90s（M5 19K 行最慢，全部 43K 行 ~2min）。
"""
import argparse
import logging
import sys
import time
from pathlib import Path

# 把项目根加入路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data import database as db
from services.data_factory import _ta_only_indicators

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("backfill")

DEFAULT_TIMEFRAMES = ["M5", "M15", "M30", "H1", "H4", "D1", "W1"]
STALE_PREFIX = "GC_"  # 历史黄金合约残留


def fetch_candles(timeframe: str) -> list:
    """从 ohlcv 读全部 K 线，转 Candle-like 对象供 _ta_only_indicators"""
    from core.bridge import Candle
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
            "WHERE timeframe=? ORDER BY timestamp ASC",
            (timeframe,),
        ).fetchall()
    finally:
        conn.close()
    return [Candle(int(r["timestamp"]), float(r["open"]), float(r["high"]),
                   float(r["low"]), float(r["close"]), float(r["volume"]))
            for r in rows]


def count_existing_keys(timeframe: str) -> dict:
    """返回 {(tf, ts): key_count} — 仅查询指定 tf 的现有键数"""
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT timestamp, indicators FROM indicator_snapshots WHERE timeframe=?",
            (timeframe,),
        ).fetchall()
    finally:
        conn.close()
    import json as _json
    return {r["timestamp"]: len(_json.loads(r["indicators"])) for r in rows}


def clean_stale_gc() -> int:
    """清理 ohlcv 表中 GC_* 残留（历史黄金合约数据，2024-06 后停更）"""
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM ohlcv WHERE timeframe LIKE ?", (f"{STALE_PREFIX}%",)
        ).fetchone()[0]
        if cur == 0:
            log.info("[GC] no stale GC_* rows")
            return 0
        conn.execute("DELETE FROM ohlcv WHERE timeframe LIKE ?", (f"{STALE_PREFIX}%",))
        conn.commit()
        log.info(f"[GC] removed {cur} stale rows")
        return cur
    finally:
        conn.close()


def backfill_one(timeframe: str, only_incomplete: bool, dry_run: bool) -> tuple:
    """回填单个时间周期。返回 (回填数, 已跳过数)

    性能：使用单连接 + executemany 批量写入（每 1000 行 commit 一次）。
    之前每行一个连接 + 单独 commit，15K 行需要 30+ 分钟。
    """
    log.info(f"[{timeframe}] reading candles from ohlcv...")
    candles = fetch_candles(timeframe)
    if not candles:
        log.warning(f"[{timeframe}] no candles in ohlcv, skip")
        return 0, 0

    log.info(f"[{timeframe}] computing TA-Lib indicators for {len(candles)} bars...")
    t0 = time.time()
    ta = _ta_only_indicators(candles, timeframe)
    log.info(f"[{timeframe}] TA-Lib done in {time.time()-t0:.1f}s, "
             f"covered {len(ta)}/{len(candles)} bars (need >=30 for warmup)")

    if not ta:
        log.warning(f"[{timeframe}] TA-Lib returned empty (insufficient warmup?), skip")
        return 0, 0

    # 决定哪些 timestamp 需要回填
    if only_incomplete:
        existing = count_existing_keys(timeframe)
        targets = [(ts, ind) for ts, ind in ta.items()
                   if existing.get(ts, 0) < 40]  # < 40 键视为不完整
        skipped = sum(1 for ts in ta if existing.get(ts, 0) >= 40)
    else:
        targets = list(ta.items())
        skipped = 0

    log.info(f"[{timeframe}] will upsert {len(targets)} bars, skip {skipped} complete")

    if dry_run:
        return len(targets), skipped

    # 单连接 + executemany 批量写入
    import json as _json
    rows = [(timeframe, ts, _json.dumps(ind, ensure_ascii=False, default=float))
            for ts, ind in targets]
    conn = db.get_conn()
    try:
        BATCH = 1000
        written = 0
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i+BATCH]
            conn.executemany(
                "INSERT OR REPLACE INTO indicator_snapshots "
                "(timeframe, timestamp, indicators) VALUES (?, ?, ?)",
                batch,
            )
            conn.commit()
            written += len(batch)
            if (i // BATCH) % 2 == 0:
                log.info(f"[{timeframe}] progress: {written}/{len(rows)} "
                         f"({100*written/len(rows):.0f}%)")
        log.info(f"[{timeframe}] done: wrote={written} skipped={skipped}")
        return written, skipped
    except Exception as e:
        conn.rollback()
        log.error(f"[{timeframe}] write failed: {e}")
        return 0, skipped
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES),
                   help="comma-separated timeframe list (default: M5,M15,M30,H1,H4,D1,W1)")
    p.add_argument("--keep-gc", action="store_true",
                   help="保留 GC_* 残留数据（默认会清理）")
    p.add_argument("--clean-gc-only", action="store_true",
                   help="仅清理 GC_* 残留，不做回填")
    p.add_argument("--dry-run", action="store_true",
                   help="干跑，仅统计不写库")
    p.add_argument("--only-incomplete", action="store_true",
                   help="仅回填 < 40 键的行（保留已有的 45+ 键数据）")
    args = p.parse_args()

    log.info(f"=== backfill_indicators start ===")
    log.info(f"DB: {db.DB_PATH}")
    log.info(f"target timeframes: {args.timeframes}")

    # 1. 清理 GC_*（默认开）
    if not args.keep_gc:
        if args.dry_run:
            log.info("[GC] --dry-run: would clean GC_* rows")
        else:
            clean_stale_gc()

    if args.clean_gc_only:
        log.info("=== done (GC clean only) ===")
        return

    # 2. 回填各周期
    total_written = 0
    total_skipped = 0
    for tf in args.timeframes.split(","):
        tf = tf.strip()
        if not tf:
            continue
        w, s = backfill_one(tf, args.only_incomplete, args.dry_run)
        total_written += w
        total_skipped += s

    log.info(f"=== summary: wrote={total_written} skipped={total_skipped} "
             f"dry_run={args.dry_run} ===")


if __name__ == "__main__":
    main()