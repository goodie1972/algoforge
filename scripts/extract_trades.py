"""
从历史日志（GBK编码）中提取已平仓记录
"""
import json
import os
import re
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
OUTPUT = os.path.join(LOG_DIR, "closed_trades.jsonl")

# GBK encoded Chinese patterns (binary)
# 开空仓 / 开仓成功 / 接管 / 跟踪止损平仓 / 平仓成功 / Stoch衰减 / K-D衰减 / 新闻止损
OPEN_PAT = rb'\xbf\xaa\xb2\xd6\xb3\xc9\xb9\xa6:\s*(BUY|SELL)\s+XAUUSD\s+([\d.]+)\xca\xd6\s+Ticket=(\d+)'  # 开仓成功
TAKEOVER_PAT = rb'\[(\w+)\]\s+\xbd\xd3\xb9\xdc.*?Magic=(\d+)\s+([\d.]+)\xca\xd6\s+@\s*([\d.]+)\s+SL=([\d.]+)\s+TP=([\d.]+)\s+Ticket=(\d+)'  # 接管
TAKEOVER2_PAT = rb'\[(\w+)\]\s+\xbd\xd3\xb9\xdc.*?Magic=\d+\s+([\d.]+)\xca\xd6\s+@\s*([\d.]+)\s+Ticket=(\d+)'  # 接管(双单)
POSITION_PAT = rb'Ticket=(\d+)\s+(BUY|SELL)\s+([\d.]+)\xca\xd6\s+@\s*([\d.]+)\s+[\w]+=([-\d.]+)'  # 持仓信息
STRAT_OPEN_PAT = rb'\[(\w+)\]\s+\xbf\xaa\xb2\xd6\s+Magic=(\d+)\s+([\d.]+)\xca\xd6\s+@\s*([\d.]+)\s+SL=([\d.]+)\s+TP=([\d.]+)\s+Ticket=(\d+)'  # [策略] 开仓
EMA_EXIT_PAT = rb'EMA20[\xcb\xf9\xd7\xd9\xd6\xb9\xcb\xf0]\s*\xc6\xbd\xb2\xd6\s+Ticket=(\d+)'  # EMA20跟踪止损平仓
STOCH_EXIT_PAT = rb'Stoch\xcb\xa5\xbc\xf5\xb3\xf6\xb3\xa1.*?ticket=(\d+)'  # Stoch衰减出场
STOCH_EXIT2_PAT = rb'K-D\xcb\xa5\xbc\xf5\xb4\xa5\xb7\xa2\xa3\xac\xc6\xbd\xb2\xd6\s+Ticket=(\d+)'  # K-D衰减触发
NEWS_EXIT_PAT = rb'\xd0\xc2\xce\xc5\xd6\xb9\xcb\xf0.*?Ticket=(\d+)'  # 新闻止损
CONFIRM_PAT = rb'\xc6\xbd\xb2\xd6\xb3\xc9\xb9\xa6:\s+Ticket=(\d+)'  # 平仓成功

STRATEGY_BY_MAGIC = {666666: "H1_v6_hybrid"}


def extract_binary(filepath: str) -> list[dict]:
    """用二进制模式匹配提取"""
    with open(filepath, 'rb') as f:
        data = f.read()

    lines = data.split(b'\r\n')
    trades = []
    opens: dict[int, dict] = {}
    seen: set[int] = set()

    for raw in lines:
        if not raw:
            continue
        # extract timestamp
        ts_match = re.match(rb'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', raw)
        if not ts_match:
            continue
        ts = ts_match.group(1).decode('ascii')

        # === 开仓成功 ===
        m = re.search(OPEN_PAT, raw)
        if m:
            ticket = int(m.group(3))
            if ticket not in opens:
                opens[ticket] = {"ticket": ticket, "direction": m.group(1).decode(), "volume": float(m.group(2)),
                                 "entry_price": 0, "strategy": "", "magic": 0, "open_time": ts, "sl": 0, "tp": 0}
            continue

        # === 接管 (含SL/TP) ===
        m = re.search(TAKEOVER_PAT, raw)
        if m:
            ticket = int(m.group(6))
            opens[ticket] = {"ticket": ticket, "direction": "unknown", "volume": float(m.group(3)),
                             "entry_price": float(m.group(4)), "strategy": m.group(1).decode(), "magic": int(m.group(2)),
                             "open_time": ts, "sl": float(m.group(5)), "tp": float(m.group(6))}
            continue

        # === 接管 (双单, 无SL/TP) ===
        m = re.search(TAKEOVER2_PAT, raw)
        if m:
            ticket = int(m.group(4))
            if ticket not in opens:
                opens[ticket] = {"ticket": ticket, "direction": "unknown", "volume": float(m.group(2)),
                                 "entry_price": float(m.group(3)), "strategy": m.group(1).decode(),
                                 "magic": 0, "open_time": ts, "sl": 0, "tp": 0}
            continue

        # === 持仓信息（方向+价格） ===
        m = re.search(POSITION_PAT, raw)
        if m:
            ticket = int(m.group(1))
            direction = m.group(2).decode()
            volume = float(m.group(3))
            price = float(m.group(4))
            if ticket in opens:
                if opens[ticket]["direction"] == "unknown":
                    opens[ticket]["direction"] = direction
                if opens[ticket]["entry_price"] == 0:
                    opens[ticket]["entry_price"] = price
            else:
                opens[ticket] = {"ticket": ticket, "direction": direction, "volume": volume,
                                 "entry_price": price, "strategy": "", "magic": 0, "open_time": ts, "sl": 0, "tp": 0}
            continue

        # === 策略开仓 ===
        m = re.search(STRAT_OPEN_PAT, raw)
        if m:
            ticket = int(m.group(7))
            opens[ticket] = {"ticket": ticket, "direction": "unknown", "volume": float(m.group(3)),
                             "entry_price": float(m.group(4)), "strategy": m.group(1).decode(), "magic": int(m.group(2)),
                             "open_time": ts, "sl": float(m.group(5)), "tp": float(m.group(6))}
            continue

        # === 平仓检测 ===
        exit_reason = ""
        ticket = 0

        m = re.search(EMA_EXIT_PAT, raw)
        if m:
            ticket = int(m.group(1))
            exit_reason = "ema20_trail"
        else:
            m = re.search(STOCH_EXIT_PAT, raw)
            if m:
                ticket = int(m.group(1))
                exit_reason = "stoch_decay"
            else:
                m = re.search(STOCH_EXIT2_PAT, raw)
                if m:
                    ticket = int(m.group(1))
                    exit_reason = "stoch_decay"

        if ticket and ticket in opens and ticket not in seen:
            info = opens.pop(ticket)
            seen.add(ticket)

            hold_sec = 0
            try:
                ot = datetime.strptime(info["open_time"], "%Y-%m-%d %H:%M:%S")
                ct = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                hold_sec = int((ct - ot).total_seconds())
            except:
                pass

            strategy = info["strategy"] or STRATEGY_BY_MAGIC.get(info.get("magic", 0), "")

            trades.append({
                "ticket": ticket, "symbol": "XAUUSD",
                "order_type": info["direction"], "volume": info["volume"],
                "entry_price": info["entry_price"], "exit_price": 0,
                "pnl": 0, "stop_loss": info.get("sl", 0),
                "take_profit": info.get("tp", 0),
                "swap": 0, "commission": -0.5,
                "magic": info.get("magic", 0),
                "strategy": strategy,
                "open_time": info["open_time"], "close_time": ts,
                "hold_seconds": hold_sec, "exit_reason": exit_reason,
            })

    return trades


def main():
    log_files = sorted(
        [f for f in os.listdir(LOG_DIR) if f.startswith("trading_") and f.endswith(".log")],
        key=lambda f: os.path.getmtime(os.path.join(LOG_DIR, f)),
    )
    cr = os.path.join(LOG_DIR, "current_run.log")
    if os.path.exists(cr):
        log_files.append("current_run.log")

    all_trades = []
    for fn in log_files:
        fp = os.path.join(LOG_DIR, fn)
        if os.path.getsize(fp) == 0:
            continue
        trades = extract_binary(fp)
        all_trades.extend(trades)

    # dedup by ticket (keep last)
    deduped = {t["ticket"]: t for t in all_trades}
    all_trades = list(deduped.values())
    all_trades.sort(key=lambda t: t["ticket"])

    with open(OUTPUT, "w", encoding="utf-8") as f:
        for t in all_trades:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    good = [t for t in all_trades if t["entry_price"] > 0 and t["order_type"] != "unknown"]
    print(f"导出 {len(all_trades)} 条 (含完整数据: {len(good)})")
    for t in all_trades[-15:]:
        print(f"  #{t['ticket']} {t['strategy']:16s} {t['order_type']:7s} entry={t['entry_price']:<8.2f} hold={t['hold_seconds']:>5}s {t['exit_reason']}")


if __name__ == "__main__":
    main()
