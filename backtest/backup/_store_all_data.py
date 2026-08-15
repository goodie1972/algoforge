"""
【数据存储总管线】
确保所有周期的 OHLC 数据完整存入 market_data.db + 导出 CSV

存储原则:
  1. DB 是主存储（market_data.db）— 所有数据统一入库
  2. CSV 是回测用导出（xauusd-dev/data/）— 从 DB 导出
  3. 已存在的 H1 CSV 2024 数据 → 先导入 DB，再统一导出

覆盖目标:
  M15: 2026-04 ~ 2026-06 (MT4已有最大值)
  M30: 2026-03 ~ 2026-06 (MT4已有最大值)
  H1:  2024-01 ~ 2026-06 (CSV合并文件已有)
  H4:  2024-01 ~ 2026-06 (从H1重采样)
  D1:  2020-03 ~ 2026-06 (MT4已有)
  W1:  2022-07 ~ 2026-05 (MT4已有)
"""
import os
import sys
import csv
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.database import init_db, insert_candles, get_db_stats
from data.database import get_conn, get_candle_count


def import_h1_csv_to_db():
    """将 XAUUSD_H1.csv (2024) 和 H1_2026 合并后导入 DB
    同时从 xauusd/data/ 和 xauusd-dev/data/ 读取
    """
    # 查找可用的 H1 数据源
    candidates = []
    for base in [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "xauusd-dev", "data"),
    ]:
        for fname in ["XAUUSD_H1_merged.csv", "XAUUSD_H1.csv", "XAUUSD_H1_2026.csv"]:
            fp = os.path.join(base, fname)
            if os.path.exists(fp):
                candidates.append(fp)

    if not candidates:
        print("[H1] 未找到 H1 CSV 文件")
        return 0

    rows = []
    seen = set()  # 去重
    for fp in sorted(candidates):
        with open(fp, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                ts = int(datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp())
                if ts in seen:
                    continue
                seen.add(ts)
                rows.append((ts, float(r["open"]), float(r["high"]),
                             float(r["low"]), float(r["close"]), float(r["volume"])))
        print(f"  [H1] 从 {os.path.basename(fp)} 读取 {len(seen)} 根（累计去重后）")

    rows.sort(key=lambda x: x[0])  # 按时间排序

    # 写入 DB
    conn = get_conn()
    inserted = 0
    try:
        for ts, o, h, l, c, v in rows:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO ohlcv
                       (timeframe, timestamp, open, high, low, close, volume)
                       VALUES ('H1', ?, ?, ?, ?, ?, ?)""",
                    (ts, o, h, l, c, v),
                )
                if conn.total_changes > 0:
                    inserted += 1
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()

    print(f"  [H1] 写入 DB {inserted} 条（总去重后 {len(rows)} 根）")
    return inserted


def export_all_csv():
    """从 DB 导出所有周期 CSVs"""
    parent = os.path.dirname(os.path.dirname(__file__))
    dev_data = os.path.join(parent, "..", "xauusd-dev", "data")
    os.makedirs(dev_data, exist_ok=True)

    db_path = os.path.join(parent, "data", "market_data.db")
    if not os.path.exists(db_path):
        print(f"  [ERROR] {db_path} not found")
        return

    conn = get_conn()
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"]

    for tf in timeframes:
        rows = conn.execute("""
            SELECT datetime(timestamp,'unixepoch'), open, high, low, close, volume
            FROM ohlcv WHERE timeframe = ?
            ORDER BY timestamp ASC
        """, (tf,)).fetchall()

        if not rows:
            print(f"  {tf}: 无数据，跳过")
            continue

        dst = os.path.join(dev_data, f"XAUUSD_{tf}.csv")
        with open(dst, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "open", "high", "low", "close", "volume"])
            w.writerows(rows)

        print(f"  {tf}: {len(rows)} candles  {rows[0][0]} ~ {rows[-1][0]}")

    conn.close()


def print_summary():
    """打印最终数据摘要"""
    stats = get_db_stats()
    print("\n" + "=" * 70)
    print("  周期  |  K线数  |  覆盖区间")
    print("=" * 70)
    for tf in reversed(["W1", "D1", "H4", "H1", "M30", "M15", "M5", "M1"]):
        info = stats.get(tf)
        if info and info["count"] > 0:
            from_ts = datetime.fromtimestamp(info["from"], tz=timezone.utc).strftime("%Y-%m-%d")
            to_ts = datetime.fromtimestamp(info["to"], tz=timezone.utc).strftime("%Y-%m-%d")
            print(f"  {tf:4s}  |  {info['count']:>6}  |  {from_ts} ~ {to_ts}")
        else:
            print(f"  {tf:4s}  |  {0:>6}  |  (无数据)")
    print("=" * 70)


def verify_integrity():
    """检查数据连续性"""
    parent = os.path.dirname(os.path.dirname(__file__))
    db_path = os.path.join(parent, "data", "market_data.db")
    conn = get_conn()
    issues = []

    timeframes = ["M15", "M30", "H1", "H4", "D1"]
    for tf in timeframes:
        rows = conn.execute("""
            SELECT timestamp FROM ohlcv
            WHERE timeframe = ?
            ORDER BY timestamp ASC
        """, (tf,)).fetchall()

        if len(rows) < 2:
            continue

        # 检查是否有大的时间缺口
        tf_sec = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
        gap = tf_sec.get(tf, 3600)
        gaps = 0
        for i in range(1, len(rows)):
            diff = rows[i][0] - rows[i-1][0]
            if diff > gap * 3:  # 超过3倍正常间隔
                gaps += 1
                if gaps <= 3:
                    from_gap = datetime.fromtimestamp(rows[i-1][0], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                    to_gap = datetime.fromtimestamp(rows[i][0], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                    issues.append(f"  {tf}: 数据缺口 {diff//3600}h ({from_gap} ~ {to_gap})")

        if gaps > 0:
            print(f"  {tf}: {gaps} 个数据缺口")
            for iss in issues:
                if iss.startswith(f"  {tf}"):
                    print(iss)
        else:
            print(f"  {tf}: 数据连续 (✓)")

    conn.close()
    return issues


if __name__ == "__main__":
    print("=" * 70)
    print("XAUUSD 全周期数据存储管線")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    print("\n[1/4] 初始化数据库...")
    init_db()

    print("\n[2/4] 导入 H1 2024 CSV 数据到 DB...")
    import_h1_csv_to_db()

    print("\n[3/4] 导出所有周期 CSV 到 xauusd-dev/data/...")
    export_all_csv()

    print("\n[4/4] 数据完整性检查...")
    verify_integrity()

    print("\n" + "=" * 70)
    print("最终数据摘要:")
    print_summary()
    print("\n存储完成！所有数据已写入 DB + CSV 导出。")
