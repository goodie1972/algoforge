"""
策略信号记录器 — 每60秒记录一次所有策略的最新信号
输出到 logs/signal_log.csv
"""
import csv
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
CSV_PATH = LOG_DIR / "signal_log.csv"
API_BASE = "http://127.0.0.1:1783"

HEADERS = [
    "timestamp", "strategy", "signal", "score_long", "score_short",
    "factors_long", "factors_short", "close", "mfi",
    "bb_upper", "bb_mid", "bb_lower", "status", "exit_reason", "exit_pnl",
    "ticket"
]

def fetch_signals():
    url = f"{API_BASE}/api/signals?limit=20"
    resp = urllib.request.urlopen(url, timeout=10)
    return json.loads(resp.read().decode())

def fetch_price():
    url = f"{API_BASE}/api/market/price"
    resp = urllib.request.urlopen(url, timeout=5)
    return json.loads(resp.read().decode())

def main():
    # 检查CSV是否存在，不存在则写表头
    exists = CSV_PATH.exists()
    f = open(CSV_PATH, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=HEADERS)
    if not exists:
        writer.writeheader()
        f.flush()

    seen_ids: set[int | str] = set()
    # 加载已有记录
    if exists:
        with open(CSV_PATH, "r", encoding="utf-8") as rf:
            reader = csv.DictReader(rf)
            for row in reader:
                tid = row.get("ticket", "")
                if tid:
                    seen_ids.add(int(tid) if tid.isdigit() else tid)

    print(f"信号记录器启动，已记录 {len(seen_ids)} 个ticket")
    price = fetch_price()
    print(f"当前价格: Bid={price.get('bid')} Ask={price.get('ask')}")

    while True:
        try:
            signals = fetch_signals()
            new_count = 0
            for s in signals:
                ticket = s.get("ticket")
                if ticket and ticket not in seen_ids:
                    seen_ids.add(ticket)
                    row = {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "strategy": s.get("strategy", ""),
                        "signal": s.get("signal", ""),
                        "score_long": s.get("score_long", 0),
                        "score_short": s.get("score_short", 0),
                        "factors_long": json.dumps(s.get("factors_long", []), ensure_ascii=False),
                        "factors_short": json.dumps(s.get("factors_short", []), ensure_ascii=False),
                        "status": s.get("status", ""),
                        "exit_reason": s.get("exit_reason", ""),
                        "exit_pnl": s.get("exit_pnl", ""),
                        "ticket": ticket,
                    }
                    # 从 indicator_values 提取
                    iv = s.get("indicator_values", {})
                    if isinstance(iv, str):
                        try:
                            iv = json.loads(iv)
                        except:
                            iv = {}
                    row["close"] = iv.get("close", "")
                    row["mfi"] = iv.get("mfi", "")
                    row["bb_upper"] = iv.get("bb_upper", "")
                    row["bb_mid"] = iv.get("bb_mid", "")
                    row["bb_lower"] = iv.get("bb_lower", "")
                    writer.writerow(row)
                    f.flush()
                    new_count += 1
                    print(f"[新增] {row['timestamp']} {row['strategy']} {row['signal']} ticket={ticket} close={row['close']} mfi={row['mfi']}")

            if new_count > 0:
                print(f"本轮新增 {new_count} 条信号")

        except Exception as e:
            print(f"[错误] {e}")

        time.sleep(60)

if __name__ == "__main__":
    main()
