"""
/api/paper-trading/* 路由 — 纸面交易管理
"""
import csv
import logging
import os
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/paper-trading", tags=["paper-trading"])

# 由 main.py 注入
engine_runner = None

logger = logging.getLogger("dashboard.paper_trading")

CSV_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "../../../papertest/papertest_bridge.csv")
)


@router.post("/reset")
async def reset_paper_trading():
    """重置纸面交易数据 — 清空持仓、历史成交、余额归零"""
    if not engine_runner:
        raise HTTPException(500, "引擎未初始化")

    bridge = engine_runner.bridge
    if bridge is None:
        raise HTTPException(500, "桥接未初始化")

    # 尝试用 PaperBridge 接口重置
    reset_func = getattr(bridge, "reset_all", None)
    if reset_func is None:
        raise HTTPException(400, "当前桥接非纸面模式，不支持重置")

    result = reset_func()

    # 确保 CSV 文件存在且只有表头
    _ensure_csv_cleared()

    return {"message": "纸面数据已重置", **result}


def _ensure_csv_cleared():
    """确保 CSV 文件存在并有表头（兜底，reset_all 已处理清空）"""
    headers = [
        "ticket", "strategy", "magic", "direction", "volume",
        "entry_time", "entry_price", "exit_time", "exit_price",
        "pnl", "commission", "net_pnl", "exit_reason",
        "stop_loss", "take_profit", "entry_bid", "entry_ask",
    ]
    if not os.path.exists(CSV_PATH):
        os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(headers)
        logger.info("createdemptypaper trading CSV file")
