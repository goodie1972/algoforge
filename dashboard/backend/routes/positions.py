"""
/api/positions 路由 - 持仓查询和管理
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from config import settings

router = APIRouter(prefix="/api/positions", tags=["positions"])

engine_runner = None
run_bridge = None


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


def _add_ts_fields(pos: dict) -> dict:
    result = dict(pos)
    for key in ("open_time", "created_at", "updated_at"):
        val = pos.get(key)
        if val:
            try:
                if isinstance(val, str):
                    # Unix 时间戳字符串（纯数字）直接转 int
                    if val.strip().isdigit():
                        result[f"{key}_ts"] = int(val)
                    else:
                        dt = datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
                        result[f"{key}_ts"] = int(dt.timestamp())
                elif isinstance(val, (int, float)):
                    result[f"{key}_ts"] = int(val)
            except Exception:
                pass
    return result


@router.get("")
async def get_positions(symbol: Optional[str] = None):
    """获取当前持��（用最新价格��新 current_price）"""
    if not engine_runner:
        return []
    positions = engine_runner._fresh_positions()
    # ���加 _ts 后��的 Unix 时间��字段
    positions = [_add_ts_fields(p) for p in positions]
    return positions


@router.post("/{ticket}/close")
async def close_position(ticket: int, req: CloseRequest = None):
    """平仓（自动记录到数据库 + 更新引擎风险状态）"""
    if not engine_runner or not engine_runner.bridge:
        raise HTTPException(503, "桥接器未连接")
    try:
        volume = req.volume if req and req.volume else 0
        ok = engine_runner.close_position(ticket, volume)
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
