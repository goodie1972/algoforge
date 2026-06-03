"""
/api/trades 路由 - 历史成交记录查询
"""
import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/trades", tags=["trades"])

engine_runner = None
run_bridge = None
logger = logging.getLogger(__name__)

MAGIC_TO_STRATEGY = {
    777777: "H1_rsi_bollinger",
    777888: "M30_rsi_turn",
    888888: "H4_stoch_bollinger",
}


@router.get("/history")
async def get_trade_history(limit: int = 100):
    """获取最近 N 条已平仓记录"""
    if not engine_runner or not engine_runner._engine:
        return []
    try:
        trades = engine_runner._engine.closed_trades
        return trades[-limit:]
    except Exception as e:
        raise HTTPException(502, f"获取历史成交失败: {e}")


@router.post("/recover")
async def recover_trades():
    """从 MT4 拉取全部历史成交，补写缺失记录到 closed_trades.jsonl"""
    if not engine_runner or not engine_runner.bridge or not engine_runner.is_running:
        raise HTTPException(400, "引擎未运行或桥接未连接")

    engine = engine_runner._engine
    if not engine:
        raise HTTPException(400, "引擎未初始化")

    try:
        orders = await run_bridge(engine_runner.bridge.get_order_history, "XAUUSD")
    except Exception as e:
        raise HTTPException(502, f"从 MT4 获取历史成交失败: {e}")

    if not orders:
        return {"recovered": 0, "message": "MT4 无历史成交记录"}

    # 去重
    existing_tickets = {t["ticket"] for t in engine._closed_trades}
    missing = [o for o in orders if o["ticket"] not in existing_tickets]

    if not missing:
        return {"recovered": 0, "message": "所有历史成交已入库，无需补充"}

    # 格式化并写入
    records = []
    for order in missing:
        magic = order["magic"]
        strategy = MAGIC_TO_STRATEGY.get(magic, f"magic_{magic}")
        open_dt = datetime.fromtimestamp(order["open_time"])
        close_dt = datetime.fromtimestamp(order["close_time"])
        hold_sec = int(order["close_time"] - order["open_time"])

        record = {
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
        records.append(record)
        engine._closed_trades.append(record)

    # 追加到 JSONL 文件
    trades_file = engine._trades_file
    try:
        with open(trades_file, "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError as e:
        raise HTTPException(500, f"写入成交记录文件失败: {e}")

    total_pnl = sum(r["pnl"] for r in records)
    buy_count = sum(1 for r in records if r["order_type"] == "BUY")
    sell_count = sum(1 for r in records if r["order_type"] == "SELL")

    logger.info(
        f"成交恢复: {len(records)} 条 "
        f"(多 {buy_count} 空 {sell_count}) "
        f"总盈亏 ${total_pnl:.2f}"
    )

    return {
        "recovered": len(records),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "total_pnl": round(total_pnl, 2),
        "records": records,
    }
