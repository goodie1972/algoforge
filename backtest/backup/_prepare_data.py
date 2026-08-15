"""
准备各周期 CSV: 
- H4: 从 H1_merged.csv 重采样（有效）
- M15/M30: 从 market_data.db 导出（数据量有限但可试）
"""
import csv, os, sqlite3
from datetime import datetime, timezone

DEV_DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "xauusd-dev", "data")
os.makedirs(DEV_DATA, exist_ok=True)

def resample_h1_to_h4():
    """将 H1_merged.csv 重采样为 H4 CSV（OHLC标准聚合）"""
    src = os.path.join(DEV_DATA, "XAUUSD_H1_merged.csv")
    dst = os.path.join(DEV_DATA, "XAUUSD_H4_resampled.csv")

    if not os.path.exists(src):
        alt = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "XAUUSD_H1.csv")
        if os.path.exists(alt):
            src = alt
        else:
            print("ERROR: H1 data file not found")
            return 0

    with open(src) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    h4_candles = []
    for i in range(0, len(rows), 4):
        chunk = rows[i:i+4]
        if len(chunk) < 4:
            break
        o = float(chunk[0]["open"])
        h = max(float(r["high"]) for r in chunk)
        l = min(float(r["low"]) for r in chunk)
        c = float(chunk[-1]["close"])
        v = sum(float(r["volume"]) for r in chunk)
        t = chunk[0]["time"]
        h4_candles.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v})

    with open(dst, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["time","open","high","low","close","volume"])
        w.writeheader()
        w.writerows(h4_candles)

    print(f"H4 (resampled): {len(h4_candles)} candles  {h4_candles[0]['time']} ~ {h4_candles[-1]['time']} -> {dst}")
    return len(h4_candles)


def export_from_db(timeframe, count=None):
    """从 market_data.db 导出指定周期数据到 CSV"""
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "market_data.db")
    if not os.path.exists(db_path):
        print(f"ERROR: {db_path} not found")
        return 0

    dst = os.path.join(DEV_DATA, f"XAUUSD_{timeframe}.csv")
    conn = sqlite3.connect(db_path)

    query = f"""
        SELECT datetime(timestamp,'unixepoch'), open, high, low, close, volume
        FROM ohlcv WHERE timeframe = '{timeframe}'
        ORDER BY timestamp ASC
    """
    if count:
        query = query.replace(";", f" LIMIT {count};")

    rows = conn.execute(query).fetchall()
    conn.close()

    if not rows:
        print(f"  {timeframe}: no data in DB")
        return 0

    with open(dst, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time","open","high","low","close","volume"])
        w.writerows(rows)

    print(f"  {timeframe}: {len(rows)} candles  {rows[0][0]} ~ {rows[-1][0]} -> {dst}")
    return len(rows)


if __name__ == "__main__":
    print("=== 准备各周期回测数据 ===\n")

    print("1) H4 (resampled from H1_merged):")
    n = resample_h1_to_h4()

    print("\n2) M15 from market_data.db:")
    export_from_db("M15")

    print("\n3) M30 from market_data.db:")
    export_from_db("M30")

    print("\nDone!")
