"""
从 MT4 历史成交中恢复缺失的交易记录，补写到 closed_trades.jsonl

用法: python scripts/recover_trades.py

前提: MT4 已运行 + EA 已加载（需包含 F062 指令支持）
"""
import json
import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.bridge import create_bridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("recover_trades")

MAGIC_TO_STRATEGY = {
    666666: "H1_v6_hybrid",
}

TRADES_FILE = os.path.join(os.path.dirname(__file__), "..", "logs", "closed_trades.jsonl")


def load_existing_tickets() -> set[int]:
    """读取已入库的 ticket 号"""
    if not os.path.exists(TRADES_FILE):
        return set()
    tickets = set()
    with open(TRADES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    record = json.loads(line)
                    tickets.add(record["ticket"])
                except (json.JSONDecodeError, KeyError):
                    continue
    logger.info(f"已入库 {len(tickets)} 条记录")
    return tickets


def append_trades(records: list[dict]):
    """追加到 closed_trades.jsonl"""
    count = 0
    with open(TRADES_FILE, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            count += 1
    logger.info(f"补写 {count} 条到 {TRADES_FILE}")


def format_record(order: dict) -> dict:
    """将 MT4 order 转为 closed_trades.jsonl 格式"""
    magic = order["magic"]
    strategy = MAGIC_TO_STRATEGY.get(magic, f"magic_{magic}")

    open_dt = datetime.fromtimestamp(order["open_time"])
    close_dt = datetime.fromtimestamp(order["close_time"])
    hold_sec = int(order["close_time"] - order["open_time"])

    return {
        "ticket": order["ticket"],
        "symbol": order["symbol"],
        "order_type": order["order_type"],
        "volume": order["volume"],
        "entry_price": order["open_price"],
        "exit_price": order["close_price"],
        "pnl": round(order["profit"], 2),
        "stop_loss": order["stop_loss"],
        "take_profit": order["take_profit"],
        "swap": round(order["swap"], 2),
        "commission": round(order["commission"], 2),
        "magic": magic,
        "strategy": strategy,
        "open_time": open_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "close_time": close_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "hold_seconds": hold_sec,
        "exit_reason": "mt4_history",
    }


def main():
    logger.info("连接 MT4...")
    bridge = create_bridge()
    if not bridge.connect():
        logger.error("无法连接 MT4，请确认 MT4 已运行且 EA 已加载")
        sys.exit(1)

    logger.info("拉取历史成交...")
    orders = bridge.get_order_history("XAUUSD")
    logger.info(f"MT4 返回 {len(orders)} 条历史记录")

    existing = load_existing_tickets()
    missing = [o for o in orders if o["ticket"] not in existing]
    logger.info(f"其中 {len(missing)} 条尚未入库")

    if not missing:
        logger.info("无需补充")
        bridge.disconnect()
        return

    records = [format_record(o) for o in missing]
    append_trades(records)

    # 汇总
    total_pnl = sum(r["pnl"] for r in records)
    buy_count = sum(1 for r in records if r["order_type"] == "BUY")
    sell_count = sum(1 for r in records if r["order_type"] == "SELL")
    logger.info(
        f"恢复完成: {len(records)} 条 "
        f"(多 {buy_count} 空 {sell_count}) "
        f"总盈亏 ${total_pnl:.2f}"
    )

    bridge.disconnect()


if __name__ == "__main__":
    main()
