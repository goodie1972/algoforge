"""
从 MT4 下载 M15/M30 历史数据并导出 CSV
通过 FreeMT4Bridge 端口 23232 请求
"""
import socket, csv, os, sys
from datetime import datetime, timezone

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 23232
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "xauusd-dev", "data")
os.makedirs(OUT_DIR, exist_ok=True)

def query_bridge(cmd: str, timeout: int = 30) -> str:
    """发送命令到 FreeMT4Bridge，返回响应"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((BRIDGE_HOST, BRIDGE_PORT))
    s.sendall((cmd + "\n").encode("utf-8"))
    resp = b""
    while True:
        try:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
        except socket.timeout:
            break
    s.close()
    return resp.decode("utf-8", errors="replace")

def parse_candles(resp: str) -> list:
    """解析 GET_CANDLES 返回的蜡烛数据"""
    candles = []
    for line in resp.strip().split("\n"):
        parts = line.split("|")
        if len(parts) >= 8:
            try:
                candles.append({
                    "time": datetime.fromtimestamp(int(parts[2]), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "open": float(parts[3]),
                    "high": float(parts[4]),
                    "low": float(parts[5]),
                    "close": float(parts[6]),
                    "volume": float(parts[7]),
                })
            except (ValueError, IndexError):
                continue
    return candles

def save_csv(timeframe: str, candles: list):
    """保存蜡烛数据到 CSV"""
    path = os.path.join(OUT_DIR, f"XAUUSD_{timeframe}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c["time"], c["open"], c["high"], c["low"], c["close"], c["volume"]])
    print(f"  -> saved {len(candles)} candles to {path}")

if __name__ == "__main__":
    # 测试连接
    print("Testing bridge connection...")
    try:
        resp = query_bridge("PING", timeout=5)
        print(f"  Bridge response: {resp.strip()}")
    except Exception as e:
        print(f"  ERROR: Cannot connect to bridge: {e}")
        sys.exit(1)

    # 下载 M15
    print("\nDownloading M15 (5000 candles)...")
    try:
        resp = query_bridge("GET_CANDLES|XAUUSD|M15|5000", timeout=60)
        candles = parse_candles(resp)
        if candles:
            print(f"  Got {len(candles)} M15 candles: {candles[0]['time']} ~ {candles[-1]['time']}")
            save_csv("M15", candles)
        else:
            print("  No M15 candles received")
    except Exception as e:
        print(f"  ERROR downloading M15: {e}")

    # 下载 M30
    print("\nDownloading M30 (5000 candles)...")
    try:
        resp = query_bridge("GET_CANDLES|XAUUSD|M30|5000", timeout=60)
        candles = parse_candles(resp)
        if candles:
            print(f"  Got {len(candles)} M30 candles: {candles[0]['time']} ~ {candles[-1]['time']}")
            save_csv("M30", candles)
        else:
            print("  No M30 candles received")
    except Exception as e:
        print(f"  ERROR downloading M30: {e}")
