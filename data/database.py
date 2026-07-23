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
    ticket TEXT PRIMARY KEY,
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
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
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
    ticket TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
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
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
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
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,
    name TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);

CREATE TABLE IF NOT EXISTS news_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_title TEXT NOT NULL,
    event_time TEXT NOT NULL,
    event_country TEXT DEFAULT 'USD',
    event_impact TEXT DEFAULT 'High',
    expected_bias TEXT NOT NULL,
    confidence TEXT DEFAULT 'low',
    reason TEXT DEFAULT '',
    pre_price REAL DEFAULT 0,
    post_price_15m REAL DEFAULT 0,
    post_price_1h REAL DEFAULT 0,
    actual_move_15m REAL DEFAULT 0,
    actual_move_1h REAL DEFAULT 0,
    direction_match TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_news_eval_time ON news_evaluations(event_time);

CREATE TABLE IF NOT EXISTS news_bias_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    news_items TEXT DEFAULT '[]',
    variable_scores TEXT DEFAULT '{}',
    market_context TEXT DEFAULT '{}',
    prediction TEXT DEFAULT '{}',
    entry_price REAL DEFAULT 0,
    verify_price REAL DEFAULT 0,
    verify_result TEXT DEFAULT '',
    verify_at TEXT DEFAULT '',
    popped_up INTEGER DEFAULT 0,
    summary TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_nbr_created ON news_bias_reports(created_at);

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
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sv_magic ON strategy_versions(magic);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT DEFAULT '',
    content TEXT NOT NULL,
    account_balance REAL DEFAULT 0,
    account_equity REAL DEFAULT 0,
    floating_pnl REAL DEFAULT 0,
    daily_pnl REAL DEFAULT 0,
    position_count INTEGER DEFAULT 0,
    snapshot_id INTEGER,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_reports_type_date ON reports(type, created_at);

CREATE TABLE IF NOT EXISTS tick_data (
    timestamp INTEGER NOT NULL PRIMARY KEY,
    bid REAL,
    ask REAL,
    spread REAL
);

CREATE TABLE IF NOT EXISTS indicator_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timeframe TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    indicators TEXT NOT NULL,
    UNIQUE(timeframe, timestamp)
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _migrate_ticket_to_text(conn):
    """检测旧 INTEGER ticket 表 → 重命名，让 SCHEMA 创建新 TEXT 表"""
    info = {r[1].upper(): r[2].upper() for r in conn.execute("PRAGMA table_info(trades)").fetchall()}
    if 'TICKET' in info and info['TICKET'] in ('INTEGER', 'INT', 'BIGINT'):
        conn.execute("ALTER TABLE trades RENAME TO trades_old_int")
        logger.info("[DB] trades.ticket INTEGER→TEXT 迁移：旧表已重命名")
    info2 = {r[1].upper(): r[2].upper() for r in conn.execute("PRAGMA table_info(signals)").fetchall()}
    if 'TICKET' in info2 and info2['TICKET'] in ('INTEGER', 'INT', 'BIGINT'):
        conn.execute("ALTER TABLE signals RENAME TO signals_old_int")
        logger.info("[DB] signals.ticket INTEGER→TEXT 迁移：旧表已重命名")


def _restore_old_ticket_data(conn):
    """从旧表恢复数据到新 TEXT 表"""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if 'trades_old_int' in tables:
        conn.execute("""INSERT INTO trades (ticket, symbol, order_type, volume, entry_price, exit_price,
            pnl, stop_loss, take_profit, swap, commission, magic, strategy,
            open_time, close_time, hold_seconds, exit_reason, indicator_snapshot, created_at)
            SELECT CAST(ticket AS TEXT), symbol, order_type, volume, entry_price, exit_price,
            pnl, stop_loss, take_profit, swap, commission, magic, strategy,
            open_time, close_time, hold_seconds, exit_reason, indicator_snapshot, created_at
            FROM trades_old_int""")
        conn.execute("DROP TABLE trades_old_int")
        logger.info("[DB] trades 旧数据恢复完成")
    if 'signals_old_int' in tables:
        conn.execute("""INSERT INTO signals (id, strategy, magic, timeframe, timestamp, signal,
            score_long, score_short, threshold, factors_long, factors_short,
            indicator_values, confidence, price_entry, ticket, created_at)
            SELECT id, strategy, magic, timeframe, timestamp, signal,
            score_long, score_short, threshold, factors_long, factors_short,
            indicator_values, confidence, price_entry, CAST(ticket AS TEXT), created_at
            FROM signals_old_int""")
        conn.execute("DROP TABLE signals_old_int")
        logger.info("[DB] signals 旧数据恢复完成")


def init_db():
    conn = get_conn()
    try:
        _migrate_ticket_to_text(conn)           # ① 旧表重命名
        conn.executescript(SCHEMA)               # ② 创建新 TEXT 表
        _restore_old_ticket_data(conn)           # ③ 恢复旧数据
        conn.commit()
        # 统计表数
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = [r["name"] for r in tables]
        logger.info(f"数据库初始化完成: {DB_PATH} ({len(names)} 张表: {', '.join(names)})")
        migrate_signals_lifecycle()
        migrate_risk_states_exit_timestamps()
        migrate_timezone_fix()
    finally:
        conn.close()


def migrate_signals_lifecycle():
    """为 signals 表添加生命周期字段（安全 ALTER TABLE）+ 回填旧数据"""
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
        # 回填旧信号：空status + 无ticket → voided
        conn.execute("UPDATE signals SET status='voided', void_reason='历史记录' WHERE (status IS NULL OR status = '') AND (ticket IS NULL OR ticket = '' OR ticket = '0')")
        # 回填旧信号：空status + 有ticket → opened
        conn.execute("UPDATE signals SET status='opened' WHERE (status IS NULL OR status = '') AND ticket IS NOT NULL AND ticket != '' AND ticket != '0'")
        conn.commit()
    finally:
        conn.close()


def migrate_risk_states_exit_timestamps():
    """为 risk_states 表添加 exit_timestamps 列（安全 ALTER TABLE）"""
    conn = get_conn()
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info('risk_states')").fetchall()}
        if 'exit_timestamps' not in existing:
            conn.execute("ALTER TABLE risk_states ADD COLUMN exit_timestamps TEXT DEFAULT '[]'")
            conn.commit()
            logger.info("迁移: risk_states 表添加 exit_timestamps 列成功")
    finally:
        conn.close()


def migrate_timezone_fix():
    """将表中已存在的 UTC created_at/updated_at 转为本地时 (UTC+8)。
    SQLite 的 datetime('now') 返回 UTC，此前所有表的默认值都用它。
    新数据已改为 datetime('now', 'localtime')，老数据用此迁移加 8 小时。

    只在首次启动时执行一次（通过 metadata 表标记），防止重复迁移造成数据损坏。"""
    conn = get_conn()
    try:
        # 检查是否已执行过
        done = conn.execute(
            "SELECT 1 FROM metadata WHERE key='timezone_migrated'"
        ).fetchone()
        if done:
            logger.debug("时区迁移: 已完成（metadata 标记），跳过")
            return

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        fixed = 0
        for (tbl,) in tables:
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info('{tbl}')").fetchall()}
            for time_col in ('created_at', 'updated_at'):
                if time_col not in cols:
                    continue
                rows = conn.execute(
                    f"SELECT rowid, {time_col} FROM {tbl} "
                    f"WHERE {time_col} IS NOT NULL AND {time_col} != ''"
                ).fetchall()
                for rowid, val in rows:
                    try:
                        dt = datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
                    except (ValueError, TypeError):
                        continue
                    # 加 8 小时（UTC → UTC+8）
                    local_dt = dt + timedelta(hours=8)
                    local_str = local_dt.strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute(
                        f"UPDATE {tbl} SET {time_col}=? WHERE rowid=?",
                        (local_str, rowid)
                    )
                    fixed += 1
        if fixed:
            conn.commit()
            logger.info(f"时区迁移: 已修正 {fixed} 条记录的 created_at/updated_at (UTC → UTC+8)")
        else:
            logger.info("时区迁移: 无需修正")
        # 写入迁移标记，防止下次启动重复执行
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("timezone_migrated", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"时区迁移异常: {e}")
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


def get_signal_by_ticket(ticket: int | str) -> Optional[dict]:
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
                    """INSERT OR REPLACE INTO ohlcv
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


# ── Signals ─────────────────────────────────────────────

def insert_signal(record: dict) -> int:
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO signals
               (strategy, magic, timeframe, timestamp, signal,
                score_long, score_short, threshold,
                factors_long, factors_short, indicator_values,
                confidence, price_entry, ticket, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.get("strategy", ""), record.get("magic", 0),
                record.get("timeframe", ""), record.get("timestamp", ""),
                record.get("signal"), record.get("score_long", 0),
                record.get("score_short", 0), record.get("threshold", 0),
                record.get("factors_long", "[]"), record.get("factors_short", "[]"),
                record.get("indicator_values", "{}"),
                record.get("confidence"), record.get("price_entry"),
                record.get("ticket"),
                record.get("status", "pending"),
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


# ── News Evaluations ────────────────────────────────────

def insert_news_evaluation(record: dict) -> int:
    """写入一条 news-bias 评估记录。返回 1 表示成功"""
    conn = get_conn()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO news_evaluations
               (event_title, event_time, event_country, event_impact,
                expected_bias, confidence, reason,
                pre_price, post_price_15m, post_price_1h,
                actual_move_15m, actual_move_1h, direction_match)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.get("event_title", ""), record.get("event_time", ""),
                record.get("event_country", "USD"), record.get("event_impact", "High"),
                record.get("expected_bias", "neutral"), record.get("confidence", "low"),
                record.get("reason", ""),
                record.get("pre_price", 0), record.get("post_price_15m", 0),
                record.get("post_price_1h", 0),
                record.get("actual_move_15m", 0), record.get("actual_move_1h", 0),
                record.get("direction_match"),
            ),
        )
        conn.commit()
        return 1
    except Exception as e:
        logger.warning(f"[DB] 写入 news-evaluation 失败: {e}")
        return 0
    finally:
        conn.close()


def get_news_evaluations(hours: int = 24) -> list[dict]:
    """获取最近 N 小时的 news-bias 评估记录"""
    conn = get_conn()
    try:
        cutoff = (datetime.now() - timedelta(hours=hours)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        rows = conn.execute(
            """SELECT * FROM news_evaluations
               WHERE created_at >= ? ORDER BY event_time DESC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── News-Bias 预测报告 ──────────────────────────────────

def insert_news_bias_report(record: dict) -> int:
    """写入一条 news-bias 预测报告，返回 id"""
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO news_bias_reports
               (title, created_at, news_items, variable_scores, market_context,
                prediction, entry_price, verify_price, verify_result,
                verify_at, popped_up, summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.get("title", ""),
                record.get("created_at", ""),
                record.get("news_items", "[]"),
                record.get("variable_scores", "{}"),
                record.get("market_context", "{}"),
                record.get("prediction", "{}"),
                record.get("entry_price", 0),
                record.get("verify_price", 0),
                record.get("verify_result", ""),
                record.get("verify_at", ""),
                int(record.get("popped_up", False)),
                record.get("summary", ""),
            ),
        )
        conn.commit()
        return cur.lastrowid or 0
    except Exception as e:
        logger.warning(f"[DB] 写入 news-bias 报告失败: {e}")
        return 0
    finally:
        conn.close()


def get_news_bias_reports(date: str = "", page: int = 1, page_size: int = 50) -> list[dict]:
    """获取预测报告列表"""
    conn = get_conn()
    try:
        query = "SELECT id, title, prediction, entry_price, verify_price, verify_result, summary, created_at FROM news_bias_reports"
        params: list = []
        if date:
            query += " WHERE created_at LIKE ?"
            params.append(f"{date}%")
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([page_size, (page - 1) * page_size])
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_news_bias_report(report_id: int) -> dict | None:
    """获取单条预测报告完整内容"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM news_bias_reports WHERE id=?", (report_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_news_bias_report(report_id: int, updates: dict) -> bool:
    """更新预测报告（验证回填）"""
    allowed = {"verify_price", "verify_result", "verify_at", "popped_up"}
    sets = {k: v for k, v in updates.items() if k in allowed}
    if not sets:
        return False
    conn = get_conn()
    try:
        conn.execute(
            f"UPDATE news_bias_reports SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
            [*sets.values(), report_id],
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_unverified_reports() -> list[dict]:
    """获取超过 12 小时仍未验证的报告"""
    conn = get_conn()
    try:
        cutoff = (datetime.now() - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            """SELECT * FROM news_bias_reports
               WHERE verify_result='' AND created_at <= ?""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_latest_news_bias_report() -> dict | None:
    """获取最新一条预测报告"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM news_bias_reports ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
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

# ── Reports ────────────────────────────────────────────

def insert_report(record: dict) -> int:
    """写入一条报告记录。返回 id"""
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO reports
               (type, title, summary, content, account_balance, account_equity,
                floating_pnl, daily_pnl, position_count, snapshot_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.get("type", "daily"),
                record.get("title", ""),
                record.get("summary", ""),
                record.get("content", "{}"),
                record.get("account_balance", 0),
                record.get("account_equity", 0),
                record.get("floating_pnl", 0),
                record.get("daily_pnl", 0),
                record.get("position_count", 0),
                record.get("snapshot_id"),
                record.get("created_at"),
            ),
        )
        conn.commit()
        return cur.lastrowid or 0
    except Exception as e:
        logger.warning(f"[DB] 写入报告失败: {e}")
        return 0
    finally:
        conn.close()


def get_reports(type: str = "daily", date_from: str = "",
                date_to: str = "", page: int = 1,
                page_size: int = 50) -> list[dict]:
    """获取报告列表，按 id 倒序（created_at 曾被旧 bug 写乱，不可靠）"""
    conn = get_conn()
    try:
        query = "SELECT id, type, title, summary, account_balance, account_equity, floating_pnl, daily_pnl, position_count, created_at FROM reports WHERE type=?"
        params: list = [type]
        if date_from:
            query += " AND created_at >= ?"
            params.append(date_from)
        if date_to:
            query += " AND created_at <= ?"
            params.append(date_to)
        query += " ORDER BY id DESC"
        offset = (page - 1) * page_size
        query += " LIMIT ? OFFSET ?"
        params.extend([page_size, offset])
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_report(report_id: int) -> dict | None:
    """获取单条报告的完整内容"""
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_report_timeline(date: str, type: str = "daily") -> list[dict]:
    """获取指定日期的时间轴列表（只含 id, title, summary, created_at）"""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT id, type, title, summary, account_balance, account_equity,
                      floating_pnl, daily_pnl, position_count, created_at
               FROM reports WHERE type=? AND created_at LIKE ?
               ORDER BY id DESC LIMIT 200""",
            (type, f"{date}%"),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_old_reports(keep_days: int = 90) -> int:
    """删除超过 keep_days 天的旧报告"""
    conn = get_conn()
    try:
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn.execute("DELETE FROM reports WHERE created_at < ?", (cutoff,))
        conn.commit()
        return conn.total_changes
    finally:
        conn.close()


def migrate_from_jsonl() -> int:
    """将 logs/closed_trades.jsonl 中未导入的交易写入 trades 表"""
    import config.settings as settings
    jsonl_path = os.path.join(settings.LOG_DIR, "closed_trades.jsonl")
    if not os.path.exists(jsonl_path):
        return 0

    # 已导入的 ticket
    conn = get_conn()
    existing: set[int | str] = set()
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
