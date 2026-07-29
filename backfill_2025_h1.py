"""回填 2025 年 H1 数据"""
import sys
sys.path.insert(0, r'D:\backup\BaoBao\PythonProgram\xauusd')

from datetime import datetime, timezone
from core.freemt4_bridge import FreeMT4Bridge
from data.downloader import download_timeframe_paged

print("=" * 60)
print("回填 2025 年 H1 数据")
print("=" * 60)

bridge = FreeMT4Bridge(host="127.0.0.1", port=23232, name="backfill")

# 目标: 覆盖到 2025-01-01 (2025-01-01 00:00:00 UTC = 1735689600)
target_ts = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())
print(f"目标: 覆盖到 2025-01-01 (target_ts={target_ts})")

# 回填 H1
print("\n开始回填 H1...")
n = download_timeframe_paged(bridge, "H1", target_ts=target_ts)
print(f"H1 回填: {n} 根新数据")
