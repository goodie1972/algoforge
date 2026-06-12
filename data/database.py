"""
SQLite 数据库 — 存储 K线、交易、信号、账户快照、风控状态、系统日志
"""
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, "market_data.db")

TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]

# ── Schema ──────────────────────────────────────────────

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

CREATE TABLE IF NOT EXISTS trades (
    ticket INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL DEFAULT 'XAUUSD',
    order_type TEXT NOT NULL,
    volume REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    pnl REAL NOT NULL,
    stop_loss REAL,
    take_profit REAL,
    swap REAL DEFAULT 0,
    commission REAL DEFAULT 0,
    magic INTEGER NOT NULL,
    strategy TEXT NOT NULL,
    open_time TEXT NOT NULL,
    close_time TEXT NOT NULL,
    hold_seconds INTEGER DEFAULT 0,
    exit_reason TEXT DEFAULT '',
    indicator_snapshot TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_trades_close_time ON trades(close_time);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    magic INTEGER NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    signal TEXT,
    score_long INTEGER DEFAULT 0,
    score_short INTEGER DEFAULT 0,
    threshold INTEGER DEFAULT 0,
    factors_long TEXT DEFAULT '',
    factors_short TEXT DEFAULT '',
    indicator_values TEXT DEFAULT '',
    confidence REAL,
    price_entry REAL,
    ticket INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_signals_strategy_ts ON signals(strategy, timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_ticket ON signals(ticket);

CREATE TABLE IF NOT EXISTS account_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    balance REAL NOT NULL,
    equity REAL NOT NULL,
    margin REAL DEFAULT 0,
    free_margin REAL DEFAULT 0,
    leverage INTEGER DEFAULT 0,
    floating_pnl REAL DEFAULT 0,
    daily_pnl REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_account_ts ON account_snapshots(timestamp);

CREATE TABLE IF NOT EXISTS risk_states (
    magic INTEGER PRIMARY KEY,
    strategy TEXT NOT NULL,
    realized_pnl REAL DEFAULT 0,
    consecutive_losses INTEGER DEFAULT 0,
    exit_timestamps TEXT DEFAULT '[]',
    realized_loss_blocked INTEGER DEFAULT 0,
    floating_loss_blocked INTEGER DEFAULT 0,
    rapid_exit_blocked INTEGER DEFAULT 0,
    realized_loss_amount_blocked INTEGER DEFAULT 0,
    consecutive_loss_blocked INTEGER DEFAULT 0,
    blocked_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    name TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);

CREATE TABLE IF NOT EXISTS news_calendar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    time TEXT DEFAULT '',
    title TEXT NOT NULL,
    country TEXT DEFAULT '',
    impact TEXT DEFAULT '',
    forecast TEXT DEFAULT '',
    previous TEXT DEFAULT '',
    fetched_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_country ON news_calendar(country);
CREATE INDEX IF NOT EXISTS idx_news_impact ON news_calendar(impact);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    magic INTEGER NOT NULL,
    version TEXT NOT NULL,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sv_magic ON strategy_versions(magic);
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
        # 统计表数
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = [r["name"] for r in tables]
        logger.info(f"数据库初始化完成: {DB_PATH} ({len(names)} 张表: {', '.join(names)})")
        migrate_signals_lifecycle()
    finally:
        conn.close()


def migrate_signals_lifecycle():
    """为 signals 表添加生命周期字段（安全 ALTER TABLE）"""
    conn = get_conn()
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info('signals')").fetchall()}
        additions = {
            'status': "TEXT DEFAULT ''",
            'void_reason': "TEXT DEFAULT ''",
            'exit_reason': "TEXT DEFAULT ''",
            'exit_pnl': "REAL DEFAULT 0",
            'exit_price': "REAL DEFAULT 0",
            'close_time': "TEXT DEFAULT ''",
        }
        for col, dtype in additions.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {col} {dtype}")
        conn.commit()
    finally:
        conn.close()


def update_signal_status(signal_id: int, updates: dict) -> bool:
    allowed = {'status', 'void_reason', 'exit_reason', 'exit_pnl', 'exit_price', 'close_time', 'ticket'}
    sets = {k: v for k, v in updates.items() if k in allowed}
    if not sets:
        return False
    conn = get_conn()
    try:
        conn.execute(
            f"UPDATE signals SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
            [*sets.values(), signal_id]
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_signal_by_ticket(ticket: int) -> Optional[dict]:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM signals WHERE ticket=?", (ticket,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_signals_by_status(status: str, limit: int = 100) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM signals WHERE status=? ORDER BY id DESC LIMIT ?",
            (status, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── OHLCV (已有，保持不变) ───────────────────────────────

def get_latest_timestamp(timeframe: str) -> Optional[int]:
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


def get_candles(timeframe: str, start_ts: int = 0, end_ts: int = 0,
                limit: int = 5000) -> list[dict]:
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
            {"time": row["timestamp"], "open": row["open"], "high": row["high"],
             "low": row["low"], "close": row["close"], "volume": row["volume"]}
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
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT timeframe, COUNT(*) AS count,
                      MIN(timestamp) AS min_ts, MAX(timestamp) AS max_ts
               FROM ohlcv GROUP BY timeframe ORDER BY timeframe"""
        ).fetchall()
        return {r["timeframe"]: {"count": r["count"], "from": r["min_ts"], "to": r["max_ts"]}
                for r in rows}
    finally:
        conn.close()


# ── Trades ──────────────────────────────────────────────

def insert_trade(record: dict) -> int:
    """INSERT OR REPLACE 单笔交易。返回受影响行数"""
    conn = get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO trades
               (ticket, symbol, order_type, volume, entry_price, exit_price,
                pnl, stop_loss, take_profit, swap, commission, magic, strategy,
                open_time, close_time, hold_seconds, exit_reason, indicator_snapshot)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.get("ticket"), record.get("symbol", "XAUUSD"),
                record.get("order_type"), record.get("volume"),
                record.get("entry_price"), record.get("exit_price"),
                record.get("pnl"), record.get("stop_loss"), record.get("take_profit"),
                record.get("swap", 0), record.get("commission", 0),
                record.get("magic"), record.get("strategy", ""),
                record.get("open_time"), record.get("close_time"),
                record.get("hold_seconds", 0), record.get("exit_reason", ""),
                record.get("indicator_snapshot", ""),
            ),
        )
        conn.commit()
        return 1
    except Exception as e:
        logger.warning(f"[DB] 写入交易失败 ticket={record.get('ticket')}: {e}")
        return 0
    finally:
        conn.close()


def insert_trades_batch(records: list[dict]) -> int:
    conn = get_conn()
    inserted = 0
    try:
        for r in records:
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO trades
                       (ticket, symbol, order_type, volume, entry_price, exit_price,
                        pnl, stop_loss, take_profit, swap, commission, magic, strategy,
                        open_time, close_time, hold_seconds, exit_reason)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        r.get("ticket"), r.get("symbol", "XAUUSD"),
                        r.get("order_type"), r.get("volume"),
                        r.get("entry_price"), r.get("exit_price"),
                        r.get("pnl"), r.get("stop_loss"), r.get("take_profit"),
                        r.get("swap", 0), r.get("commission", 0),
                        r.get("magic"), r.get("strategy", ""),
                        r.get("open_time"), r.get("close_time"),
                        r.get("hold_seconds", 0), r.get("exit_reason", ""),
                    ),
                )
                inserted += 1
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()
    return inserted


def get_trades(strategy: str = None, limit: int = 100, offset: int = 0) -> list[dict]:
    conn = get_conn()
    try:
        query = "SELECT * FROM trades"
        params: list = []
        if strategy:
            query += " WHERE strategy = ?"
            params.append(strategy)
        query += " ORDER BY close_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def get_trade_stats(strategy: str = None, from_date: str = "",
                    to_date: str = "") -> dict:
    """简单的统计摘要，详细统计由 routes 层计算"""
    conn = get_conn()
    try:
        query = "SELECT COUNT(*) AS total, SUM(pnl) AS net, SUM(commission) AS comm, SUM(swap) AS swap FROM trades"
        params: list = []
        conditions = []
        if strategy:
            conditions.append("strategy = ?")
            params.append(strategy)
        if from_date:
            conditions.append("close_time >= ?")
            params.append(from_date)
        if to_date:
            conditions.append("close_time <= ?")
            params.append(to_date)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def get_trades(limit: int = 100) -> list[dict]:
    """获取最近 N 条成交记录（按平仓时间倒序）"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY close_time DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Signals ─────────────────────────────────────────────

def insert_signal(record: dict) -> int:
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO signals
               (strategy, magic, timeframe, timestamp, signal,
                score_long, score_short, threshold,
                factors_long, factors_short, indicator_values,
                confidence, price_entry, ticket)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.get("strategy", ""), record.get("magic", 0),
                record.get("timeframe", ""), record.get("timestamp", ""),
                record.get("signal"), record.get("score_long", 0),
                record.get("score_short", 0), record.get("threshold", 0),
                record.get("factors_long", "[]"), record.get("factors_short", "[]"),
                record.get("indicator_values", "{}"),
                record.get("confidence"), record.get("price_entry"),
                record.get("ticket"),
            ),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except Exception as e:
        logger.warning(f"[DB] 写入信号失败 {record.get('strategy')}: {e}")
        return 0
    finally:
        conn.close()


def get_signals(strategy: str = None, limit: int = 50) -> list[dict]:
    conn = get_conn()
    try:
        query = "SELECT * FROM signals"
        params: list = []
        if strategy:
            query += " WHERE strategy = ?"
            params.append(strategy)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


def get_latest_signal(strategy: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM signals WHERE strategy = ? ORDER BY id DESC LIMIT 1",
            (strategy,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── Account Snapshots ───────────────────────────────────

def insert_account_snapshot(record: dict) -> int:
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO account_snapshots
               (timestamp, balance, equity, margin, free_margin, leverage,
                floating_pnl, daily_pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                record.get("balance", 0), record.get("equity", 0),
                record.get("margin", 0), record.get("free_margin", 0),
                record.get("leverage", 0), record.get("floating_pnl", 0),
                record.get("daily_pnl", 0),
            ),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except Exception as e:
        logger.warning(f"[DB] 写入账户快照失败: {e}")
        return 0
    finally:
        conn.close()


def get_account_history(limit: int = 100) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM account_snapshots ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return list(reversed([dict(r) for r in rows]))
    finally:
        conn.close()


# ── Risk States ─────────────────────────────────────────

def save_risk_state(magic: int, strategy: str, state: dict) -> int:
    conn = get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO risk_states
               (magic, strategy, realized_pnl, consecutive_losses, exit_timestamps,
                realized_loss_blocked, floating_loss_blocked, rapid_exit_blocked,
                realized_loss_amount_blocked, consecutive_loss_blocked, blocked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                magic, strategy,
                state.get("realized_pnl", 0), state.get("consecutive_losses", 0),
                state.get("exit_timestamps", "[]"),
                int(state.get("realized_loss_blocked", False)),
                int(state.get("floating_loss_blocked", False)),
                int(state.get("rapid_exit_blocked", False)),
                int(state.get("realized_loss_amount_blocked", False)),
                int(state.get("consecutive_loss_blocked", False)),
                state.get("blocked_at", ""),
            ),
        )
        conn.commit()
        return 1
    except Exception as e:
        logger.warning(f"[DB] 保存风控状态失败 {strategy}: {e}")
        return 0
    finally:
        conn.close()


def load_risk_states() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM risk_states").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Logs ────────────────────────────────────────────────

def insert_log(timestamp: str, level: str, name: str, message: str) -> int:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO logs (timestamp, level, name, message) VALUES (?, ?, ?, ?)",
            (timestamp, level, name, message),
        )
        conn.commit()
        return 1
    except Exception:
        return 0
    finally:
        conn.close()


def get_logs(level: str = None, since: str = None, limit: int = 100) -> list[dict]:
    conn = get_conn()
    try:
        query = "SELECT id, timestamp, level, name, message FROM logs"
        params: list = []
        conditions = []
        if level:
            levels_map = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
            min_level = levels_map.get(level.upper(), 0)
            query = (
                "SELECT id, timestamp, level, name, message FROM logs "
                "WHERE CASE level "
                "WHEN 'DEBUG' THEN 10 WHEN 'INFO' THEN 20 "
                "WHEN 'WARNING' THEN 30 WHEN 'ERROR' THEN 40 ELSE 0 END >= ?"
            )
            params.append(min_level)
        if since:
            if "WHERE" in query:
                query += " AND timestamp >= ?"
            else:
                query += " WHERE timestamp >= ?"
            params.append(since)
        if "WHERE" not in query:
            query = query.replace("FROM logs", "FROM logs")
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return list(reversed([dict(r) for r in rows]))
    finally:
        conn.close()


def prune_logs(max_rows: int = 100000, max_days: int = 7) -> int:
    """清理旧日志，返回删除条数"""
    conn = get_conn()
    try:
        # 按条数清理
        row = conn.execute("SELECT COUNT(*) AS cnt FROM logs").fetchone()
        total = row["cnt"] if row else 0
        deleted = 0
        if total > max_rows:
            excess = total - max_rows
            conn.execute(
                "DELETE FROM logs WHERE id IN (SELECT id FROM logs ORDER BY id ASC LIMIT ?)",
                (excess,),
            )
            deleted += excess
        # 按天数清理
        cutoff = (datetime.now() - timedelta(days=max_days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn.execute("DELETE FROM logs WHERE timestamp < ?", (cutoff,))
        deleted += conn.total_changes
        if deleted:
            conn.commit()
        return deleted
    finally:
        conn.close()


# ── News Calendar ───────────────────────────────────────

def clear_news_calendar():
    """清空新闻日历表（每次拉取后全量替换）"""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM news_calendar")
        conn.commit()
    finally:
        conn.close()


def insert_news_events(events: list[dict], fetched_at: float) -> int:
    """批量插入新闻事件。返回插入条数"""
    conn = get_conn()
    inserted = 0
    try:
        for evt in events:
            conn.execute(
                """INSERT INTO news_calendar
                   (date, time, title, country, impact, forecast, previous, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evt.get("date", ""), evt.get("time", ""),
                    evt.get("title", "Unknown"),
                    (evt.get("country") or "").upper(),
                    (evt.get("impact") or "").strip(),
                    evt.get("forecast", ""), evt.get("previous", ""),
                    fetched_at,
                ),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()
    return inserted


def load_news_events() -> list[dict]:
    """加载所有新闻日历事件"""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM news_calendar ORDER BY date, time").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Metadata (key-value) ────────────────────────────────

def get_metadata(key: str) -> str | None:
    """读取元数据"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def set_metadata(key: str, value: str) -> int:
    """写入或更新元数据"""
    conn = get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        return 1
    except Exception:
        return 0
    finally:
        conn.close()


# ── Strategy Versions ───────────────────────────────────

def upsert_strategy_version(magic: int, strategy_name: str, version: str,
                             date: str, description: str) -> int:
    """写入或更新策略版本记录（以 magic 为唯一键）"""
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO strategy_versions (strategy_name, magic, version, date, description)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(magic) DO UPDATE SET
                 strategy_name=excluded.strategy_name,
                 version=excluded.version,
                 date=excluded.date,
                 description=excluded.description""",
            (strategy_name, magic, version, date, description),
        )
        conn.commit()
        return 1
    except Exception as e:
        logger.warning(f"[DB] 写入策略版本失败 magic={magic}: {e}")
        return 0
    finally:
        conn.close()


def get_strategy_versions(strategy_name: str = None) -> list[dict]:
    """获取策略版本历史记录"""
    conn = get_conn()
    try:
        if strategy_name:
            rows = conn.execute(
                "SELECT * FROM strategy_versions WHERE strategy_name=? ORDER BY magic",
                (strategy_name,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM strategy_versions ORDER BY strategy_name, magic"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Migration ───────────────────────────────────────────

def migrate_from_jsonl() -> int:
    """将 logs/closed_trades.jsonl 中未导入的交易写入 trades 表"""
    import config.settings as settings
    jsonl_path = os.path.join(settings.LOG_DIR, "closed_trades.jsonl")
    if not os.path.exists(jsonl_path):
        return 0

    # 已导入的 ticket
    conn = get_conn()
    existing: set[int] = set()
    try:
        rows = conn.execute("SELECT ticket FROM trades").fetchall()
        existing = {r["ticket"] for r in rows}
    finally:
        conn.close()

    records = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if r.get("ticket") and r["ticket"] not in existing:
                        records.append(r)
                        existing.add(r["ticket"])
                except json.JSONDecodeError:
                    pass
    except OSError as e:
        logger.warning(f"[DB] 读取 JSONL 失败: {e}")
        return 0

    if records:
        n = insert_trades_batch(records)
        logger.info(f"[DB] 从 JSONL 导入 {n} 条历史交易")
        return n
    return 0
