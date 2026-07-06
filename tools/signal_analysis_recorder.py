"""
策略信号全天监控记录器 — 记录每个信号时的完整指标快照
- 从 signals API 获取信号自身的 indicator_values
- 从 data factory 拉完整指标缓存（rsi, mfi, bb, ema, sma, atr, adx, macd, stoch...）
- 记录当前 bid/ask 价格
- 每60秒检查新信号
"""
import csv
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
CSV_PATH = LOG_DIR / "signal_analysis.csv"
JSONL_PATH = LOG_DIR / "signal_snapshots.jsonl"
API_BASE = "http://127.0.0.1:1783"

# CSV 表头 — 核心字段（易读）
CSV_HEADERS = [
    "record_time",      # 记录时间
    "signal_id",        # 信号ID
    "strategy",         # 策略名
    "timeframe",        # 周期
    "signal",           # BUY/SELL
    "score_long",       # 多头评分
    "score_short",      # 空头评分
    "factors_long",     # 多头因子
    "factors_short",    # 空头因子
    "status",           # 当前状态
    "void_reason",      # 作废原因
    "exit_reason",      # 出场原因
    "exit_pnl",         # 出场盈亏
    "close",            # 信号时收盘价
    "bid",              # 同时刻买价
    "ask",              # 同时刻卖价
    "all_indicators_json",  # 全部指标 JSON（展开就是所有细节）
]


def fetch_json(url, timeout=8):
    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
        return json.loads(resp.read().decode())
    except Exception as e:
        return None


def main():
    exists = CSV_PATH.exists()
    f_csv = open(CSV_PATH, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f_csv, fieldnames=CSV_HEADERS)
    if not exists:
        writer.writeheader()
        f_csv.flush()

    # 已记录的 signal_id
    recorded_ids = set()
    if exists:
        with open(CSV_PATH, "r", encoding="utf-8") as rf:
            reader = csv.DictReader(rf)
            for row in reader:
                sid = row.get("signal_id", "")
                if sid and sid.isdigit():
                    recorded_ids.add(int(sid))

    # 信号状态追踪
    signal_states = {}

    print(f"=" * 60)
    print(f"  信号全指标记录器启动")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  CSV: {CSV_PATH}")
    print(f"  JSONL: {JSONL_PATH}")
    print(f"  已记录: {len(recorded_ids)} 个信号")
    print(f"=" * 60)

    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        signals = fetch_json(f"{API_BASE}/api/signals?limit=50")
        if not signals:
            time.sleep(30)
            continue

        # 获取当前行情
        price_data = fetch_json(f"{API_BASE}/api/market/price")
        bid = price_data.get("bid", 0) if price_data else 0
        ask = price_data.get("ask", 0) if price_data else 0

        new_count = 0

        for s in signals:
            sid = s.get("id")
            if sid is None:
                continue

            status = s.get("status", "")
            old_status = signal_states.get(sid)
            is_new = sid not in recorded_ids
            status_changed = old_status is not None and old_status != status

            if not (is_new or status_changed):
                continue

            signal_states[sid] = status
            if is_new:
                recorded_ids.add(sid)
                new_count += 1

            # ── 因子解析 ──
            factors_long = s.get("factors_long", [])
            factors_short = s.get("factors_short", [])
            if isinstance(factors_long, str):
                try: factors_long = json.loads(factors_long)
                except: factors_long = [factors_long]
            if isinstance(factors_short, str):
                try: factors_short = json.loads(factors_short)
                except: factors_short = [factors_short]

            # ── 策略自身的 indicator_values ──
            iv = s.get("indicator_values", {})
            if isinstance(iv, str):
                try: iv = json.loads(iv)
                except: iv = {}

            # ── 从数据工厂拉该周期完整指标快照 ──
            tf = s.get("timeframe", "M30")
            factory_snapshot = fetch_json(f"{API_BASE}/api/data/indicators?timeframe={tf}")
            if not factory_snapshot:
                factory_snapshot = {}

            # ── 合并全部指标 ──
            all_indicators = dict(iv)  # 策略自身的指标
            # 补充工厂指标（不覆盖策略已有值）
            for k, v in factory_snapshot.items():
                if k not in all_indicators:
                    all_indicators[k] = v
                elif k == "bb" and isinstance(v, dict):
                    # 合并 bb 细节
                    if isinstance(all_indicators[k], dict):
                        for bk, bv in v.items():
                            if bk not in all_indicators[k]:
                                all_indicators[k][bk] = bv

            # ── 补充价格信息 ──
            all_indicators["_bid"] = bid
            all_indicators["_ask"] = ask
            all_indicators["_mid"] = round((bid + ask) / 2, 2)
            all_indicators["_status"] = status
            all_indicators["_signal_id"] = sid
            all_indicators["_strategy"] = s.get("strategy", "")
            all_indicators["_signal"] = s.get("signal", "")

            # ── 写入 CSV（核心字段） ──
            row = {
                "record_time": now,
                "signal_id": sid,
                "strategy": s.get("strategy", ""),
                "timeframe": tf,
                "signal": s.get("signal", ""),
                "score_long": s.get("score_long", 0),
                "score_short": s.get("score_short", 0),
                "factors_long": "; ".join(factors_long) if factors_long else "",
                "factors_short": "; ".join(factors_short) if factors_short else "",
                "status": status,
                "void_reason": s.get("void_reason", ""),
                "exit_reason": s.get("exit_reason", ""),
                "exit_pnl": s.get("exit_pnl", ""),
                "close": iv.get("close", ""),
                "bid": bid,
                "ask": ask,
                "all_indicators_json": json.dumps(all_indicators, ensure_ascii=False, default=str),
            }
            writer.writerow(row)
            f_csv.flush()

            # ── 写入 JSONL（完整机器可读） ──
            with open(JSONL_PATH, "a", encoding="utf-8") as jf:
                jsonl_row = {
                    "record_time": now,
                    "signal_id": sid,
                    "strategy": s.get("strategy", ""),
                    "timeframe": tf,
                    "signal": s.get("signal", ""),
                    "score_long": s.get("score_long", 0),
                    "score_short": s.get("score_short", 0),
                    "factors_long": factors_long,
                    "factors_short": factors_short,
                    "status": status,
                    "void_reason": s.get("void_reason", ""),
                    "exit_reason": s.get("exit_reason", ""),
                    "exit_pnl": s.get("exit_pnl", ""),
                    "price": {"bid": bid, "ask": ask, "close": iv.get("close")},
                    "strategy_indicators": iv,
                    "factory_indicators": factory_snapshot,
                    "all_indicators": all_indicators,
                }
                jf.write(json.dumps(jsonl_row, ensure_ascii=False, default=str) + "\n")

            # ── 控制台输出 ──
            action = "新信号" if is_new else f"状态变化: {old_status}→{status}"
            score_info = f"{row['score_long']}/{row['score_short']}" if row['score_long'] != '' else "?"
            print(f"[{now}] [{action}] #{sid} {s['strategy']:<20} {s.get('signal','?'):>4} "
                  f"评分={score_info} price={iv.get('close', '?')} bid={bid} ask={ask} "
                  f"状态={status}")

        if new_count > 0:
            print(f"  本轮新增 {new_count} 个信号，累计 {len(recorded_ids)} 个")
            print(f"  详细指标已写入: {JSONL_PATH}")

        time.sleep(30)


if __name__ == "__main__":
    main()
