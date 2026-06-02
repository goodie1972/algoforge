"""
SQLite 历史行情数据库
"""
import sqlite3
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, "market_data.db")

# 所有支持的周期
TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS ohlcv (
    timeframe TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (timeframe, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_tf_ts ON ohlcv(timeframe, timestamp);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        logger.info(f"数据库初始化完成: {DB_PATH}")
    finally:
        conn.close()


def get_latest_timestamp(timeframe: str) -> Optional[int]:
    """获取指定周期的最大时间戳"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT MAX(timestamp) AS ts FROM ohlcv WHERE timeframe = ?",
            (timeframe,),
        ).fetchone()
        return row["ts"] if row and row["ts"] else None
    finally:
        conn.close()


def insert_candles(timeframe: str, candles: list) -> int:
    """批量写入 K 线，跳过已存在的。返回写入条数"""
    conn = get_conn()
    inserted = 0
    try:
        for c in candles:
            ts = int(c.time)
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO ohlcv
                       (timeframe, timestamp, open, high, low, close, volume)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (timeframe, ts, c.open, c.high, c.low, c.close, c.volume),
                )
                if conn.total_changes > 0:
                    inserted += 1
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()
    return inserted


def get_candles(timeframe: str, start_ts: int = 0, end_ts: int = 0, limit: int = 5000) -> list[dict]:
    """读取 K 线，按时间升序"""
    conn = get_conn()
    try:
        query = "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe = ?"
        params: list = [timeframe]
        if start_ts > 0:
            query += " AND timestamp >= ?"
            params.append(start_ts)
        if end_ts > 0:
            query += " AND timestamp <= ?"
            params.append(end_ts)
        query += " ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [
            {
                "time": row["timestamp"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_candle_count(timeframe: str) -> int:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM ohlcv WHERE timeframe = ?",
            (timeframe,),
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def get_db_stats() -> dict:
    """返回各周期的数据统计"""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT timeframe, COUNT(*) AS count,
                      MIN(timestamp) AS min_ts, MAX(timestamp) AS max_ts
               FROM ohlcv GROUP BY timeframe ORDER BY timeframe"""
        ).fetchall()
        stats = {}
        for r in rows:
            stats[r["timeframe"]] = {
                "count": r["count"],
                "from": r["min_ts"],
                "to": r["max_ts"],
            }
        return stats
    finally:
        conn.close()
