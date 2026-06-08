"""
全量历史数据回填 + CSV 导出

用法：
  python backtest\_backfill_history.py

流程：
  1. 检查引擎是否占用桥接（是则提示先关引擎）
  2. 分页拉取 MT4 全量历史（M15/M30/H1/H4/D1 → 覆盖到 2024）
  3. 写入 market_data.db
  4. 导出 CSV 到 xauusd-dev\data\ 供回测使用

注意：
  - 需要 MT4 的 FreeMT4Bridge EA 正在运行（端口 23232）
  - 引擎必须先停止（一个 EA 只接受一个客户端）
  - MT4 历史中心需要存有足够的历史数据
"""
import os
import sys
import time
import signal
import subprocess
from datetime import datetime, timezone

# GBK 兼容
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# 将项目根加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.downloader import download_all_paged, init_db
from data.database import get_db_stats


def check_bridge_available() -> bool:
    """检查桥接端口 23232 是否可用（没有被引擎占用连接）"""
    import subprocess as sp
    try:
        out = sp.check_output(
            ["netstat", "-an"], shell=True, encoding="gbk", timeout=5
        )
        # 找 ESTABLISHED 状态且端口为 23232
        for line in out.splitlines():
            if "23232" in line and "ESTABLISHED" in line:
                return False  # 有人连着了
        return True  # 没有 ESTABLISHED 连接 → 可用
    except Exception:
        # fallback: 尝试连接，能连就是空闲
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(("127.0.0.1", 23232))
            s.close()
            return True  # 连上了但没人用（刚断开）
        except Exception:
            return False


def export_all_csv():
    """从 DB 导出各周期 CSV 到 xauusd-dev/data/"""
    parent = os.path.dirname(os.path.dirname(__file__))
    dev_data = os.path.join(parent, "..", "xauusd-dev", "data")
    os.makedirs(dev_data, exist_ok=True)

    import sqlite3
    import csv

    db_path = os.path.join(parent, "data", "market_data.db")
    if not os.path.exists(db_path):
        print(f"  ERROR: {db_path} not found")
        return

    conn = sqlite3.connect(db_path)
    timeframes = ["M15", "M30", "H1", "H4", "D1"]

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


if __name__ == "__main__":
    print("=" * 60)
    print("XAUUSD 全量历史数据回填工具")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    # 1. 检查桥接
    print("\n[1/4] 检查 MT4 桥接状态...")
    if not check_bridge_available():
        print("  [!] 桥接端口 23232 被占用（引擎可能正在运行）")
        print("  -> 请先停止引擎，释放桥接连接，再运行本脚本")
        sys.exit(1)
    print("  [OK] 桥接空闲")

    # 2. 全量分页下载
    print("\n[2/4] 开始全量分页下载（目标: 2024-01-01）...")
    result = download_all_paged()
    if "error" in result:
        print(f"\n  ❌ {result['error']}")
        sys.exit(1)

    # 3. 导出 CSV
    print("\n[3/4] 导出 CSV 到 xauusd-dev/data/ ...")
    export_all_csv()

    # 4. 最终统计
    print("\n[4/4] 最终数据统计:")
    stats = get_db_stats()
    for tf, info in stats.items():
        if info["count"] > 0:
            print(f"  {tf}: {info['count']} candles  ({info['from']} ~ {info['to']})")

    print("\n" + "=" * 60)
    print("[OK] 回填完成！现在可以重启引擎了。")
    print("=" * 60)
