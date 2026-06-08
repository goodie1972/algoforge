"""Check DB data coverage for all timeframes"""
import sqlite3
from datetime import datetime, timezone
import os

db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "market_data.db")
conn = sqlite3.connect(db_path)

for tf in ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]:
    r = conn.execute("SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM ohlcv WHERE timeframe=?", (tf,)).fetchone()
    if r and r[0] > 0:
        t1 = datetime.fromtimestamp(r[1], tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if r[1] else "N/A"
        t2 = datetime.fromtimestamp(r[2], tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if r[2] else "N/A"
        print(f"  {tf:>4}: {r[0]:>6} candles, {t1} ~ {t2}")
    else:
        print(f"  {tf:>4}: no data")

conn.close()

# Also check CSV files
data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "xauusd-dev", "data")
print("\nCSV files:")
for f in sorted(os.listdir(data_dir)):
    if f.endswith(".csv"):
        import csv
        with open(os.path.join(data_dir, f)) as csvf:
            reader = csv.DictReader(csvf)
            rows = list(reader)
            if rows:
                print(f"  {f:<30} {len(rows):>6} rows, {rows[0]['time']} ~ {rows[-1]['time']}")
