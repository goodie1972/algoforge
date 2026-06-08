"""Check market_data.db per timeframe"""
import sqlite3, os
from datetime import datetime, timezone

db_path = "data/market_data.db"
print(f"DB: {db_path} ({os.path.getsize(db_path)} bytes)\n")

conn = sqlite3.connect(db_path)
rows = conn.execute("""
    SELECT timeframe, COUNT(*),
           datetime(MIN(timestamp),'unixepoch'),
           datetime(MAX(timestamp),'unixepoch')
    FROM ohlcv
    GROUP BY timeframe
    ORDER BY
        CASE timeframe
            WHEN 'M1' THEN 1 WHEN 'M5' THEN 2
            WHEN 'M15' THEN 3 WHEN 'M30' THEN 4
            WHEN 'H1' THEN 5 WHEN 'H4' THEN 6
            WHEN 'D1' THEN 7 WHEN 'W1' THEN 8
            ELSE 9 END
""").fetchall()

print(f"{'TF':>5} {'数量':>8} {'起始':>22} {'截止':>22}")
print("-"*60)
for r in rows:
    print(f"{r[0]:>5} {r[1]:>8} {r[2]:>22} {r[3]:>22}")
conn.close()
