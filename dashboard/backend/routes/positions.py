"""
/api/positions 路由 - 持仓查询和管理
"""
import csv
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from pathlib import Path

from config import settings
from dashboard.backend.utils import _add_ts_fields

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["positions"])

engine_runner = None
run_bridge = None

# 纸面交易 CSV 路径（与 core/paper_bridge.py 一致）
_PAPERTEST_DIR = Path(__file__).resolve().parent.parent.parent.parent / "papertest"
_CSV_TRADES = _PAPERTEST_DIR / "papertest_bridge.csv"


class CloseRequest(BaseModel):
    volume: Optional[float] = None


class ModifyRequest(BaseModel):
    sl: Optional[float] = None
    tp: Optional[float] = None


def _pos_to_dict(pos):
    return {
        "ticket": pos.ticket,
        "symbol": pos.symbol,
        "order_type": pos.order_type,
        "volume": pos.volume,
        "open_price": pos.open_price,
        "current_price": pos.current_price,
        "stop_loss": pos.stop_loss,
        "take_profit": pos.take_profit,
        "profit": round(pos.profit, 2),
        "swap": pos.swap,
        "commission": pos.commission,
        "magic": pos.magic,
        "comment": pos.comment,
        "open_time": pos.open_time,
    }


def _get_paper_positions() -> list[dict]:
    """从 PaperBridge 的 CSV 持久化文件读取当前未平仓持仓。

    Returns:
        与 live positions 格式一致的 dict 列表，标记 is_paper=True。
        CSV 不存在或读取失败时返回空列表。
    """
    if not _CSV_TRADES.exists():
        return []

    try:
        # 1. 解析 CSV，找出未平仓的 ticket（有入场但无出场）
        open_positions = {}
        with open(str(_CSV_TRADES), "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticket = row.get("ticket", "").strip()
                if not ticket:
                    continue
                # 有出场时间 → 已平仓
                if row.get("exit_time", "").strip():
                    open_positions.pop(ticket, None)
                # 有入场时间且未标记平仓 → 开仓行
                elif row.get("entry_time", "").strip():
                    open_positions[ticket] = {
                        "ticket": ticket,
                        "strategy": str(row.get("strategy", "")),
                        "magic": int(row.get("magic", 0) or 0),
                        "direction": str(row.get("direction", "BUY")),
                        "volume": float(row.get("volume", 0) or 0.01),
                        "entry_price": float(row.get("entry_price", 0) or 0),
                        "entry_time": str(row.get("entry_time", "")),
                        "stop_loss": float(row.get("stop_loss", 0) or 0),
                        "take_profit": float(row.get("take_profit", 0) or 0),
                    }

        if not open_positions:
            return []

        # 2. 尝试获取最新价格（用于计算浮动盈亏）
        current_price_bid = 0.0
        current_price_ask = 0.0
        try:
            if engine_runner and engine_runner.bridge:
                bid, ask = engine_runner.bridge.get_tick_price("XAUUSD")
                if bid > 0:
                    current_price_bid = bid
                    current_price_ask = ask
        except Exception:
            pass

        # 3. 转换为与 live positions 一致的格式
        LOT_SCALE = 100  # 与 PaperBridge 一致
        result = []
        for ticket, data in open_positions.items():
            is_buy = "BUY" in data["direction"].upper()
            entry_price = data["entry_price"]
            volume = data["volume"]

            # 计算当前价格和浮动盈亏
            if current_price_bid > 0:
                if is_buy:
                    cur_price = current_price_bid
                    pnl = round((cur_price - entry_price) * volume * LOT_SCALE, 2)
                else:
                    cur_price = current_price_ask
                    pnl = round((entry_price - cur_price) * volume * LOT_SCALE, 2)
            else:
                cur_price = entry_price
                pnl = 0.0

            # 转换 entry_time 为 Unix 时间戳字符串（与 live position 格式一致）
            open_time_str = data["entry_time"]
            try:
                dt = datetime.strptime(open_time_str, "%Y-%m-%d %H:%M:%S")
                open_time_unix = str(int(dt.timestamp()))
            except (ValueError, OSError):
                open_time_unix = "0"

            result.append({
                "ticket": ticket,
                "symbol": "XAUUSD",
                "order_type": "OP_BUY" if is_buy else "OP_SELL",
                "volume": volume,
                "open_price": entry_price,
                "current_price": cur_price,
                "stop_loss": data["stop_loss"],
                "take_profit": data["take_profit"],
                "profit": pnl,
                "swap": 0.0,
                "commission": 0.0,
                "magic": data["magic"],
                "comment": data["strategy"],
                "open_time": open_time_unix,
                "is_paper": True,
            })

        return result

    except Exception as e:
        logger.warning(f"[读取纸面持仓失败]: {e}")
        return []


@router.get("")
async def get_positions(symbol: Optional[str] = None):
    """获取当前持仓（合并实盘引擎 + 纸面引擎持仓）

    实盘持仓 is_paper=false，纸面持仓 is_paper=true。
    纸面引擎未运行或 CSV 不存在时仅返回实盘持仓。
    """
    # 1. 获取实盘引擎持仓
    live_positions = []
    if engine_runner:
        live_positions = engine_runner._fresh_positions()

    # 2. 获取纸面引擎持仓（从 CSV 读取）
    paper_positions = _get_paper_positions()

    # 3. 标记 is_paper 字段
    for p in live_positions:
        p["is_paper"] = False
    # paper_positions 已在 _get_paper_positions() 中标记 is_paper=True

    # 4. 合并
    all_positions = live_positions + paper_positions

    # 5. 附加 _ts 后缀的 Unix 时间戳字段
    all_positions = [_add_ts_fields(p) for p in all_positions]
    return all_positions


@router.post("/{ticket}/close")
async def close_position(ticket: int, req: CloseRequest = None):
    """平仓（自动记录到数据库 + 更新引擎风险状态）"""
    if not engine_runner or not engine_runner.bridge:
        raise HTTPException(503, "桥接器未连接")
    try:
        volume = req.volume if req and req.volume else 0
        ok = await run_bridge(engine_runner.close_position, ticket, volume)
        if not ok:
            raise HTTPException(404, f"平仓失败，订单 {ticket} 可能已不存在")
        return {"message": f"订单 {ticket} 已平仓", "ticket": ticket}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"平仓失败: {e}")


@router.post("/{ticket}/modify")
async def modify_position(ticket: int, req: ModifyRequest):
    """修改止损止盈"""
    if not engine_runner or not engine_runner.bridge:
        raise HTTPException(503, "桥接器未连接")
    try:
        sl = req.sl or 0
        tp = req.tp or 0
        ok = await run_bridge(engine_runner.bridge.modify_order, ticket, sl, tp)
        if not ok:
            raise HTTPException(404, f"修改失败，订单 {ticket} 可能已不存在")
        engine_runner._update_positions_cache()
        return {"message": f"订单 {ticket} 已修改", "ticket": ticket, "sl": sl, "tp": tp}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"修改失败: {e}")
