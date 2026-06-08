"""
/api/engine/* 路由 - 引擎启停、状态查询、动态策略管理、健康检查
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings

router = APIRouter(prefix="/api/engine", tags=["engine"])

# 由 main.py 在启动时注入
engine_runner = None
# 由 main.py 注入 STRATEGY_MAP 的 name→label 信息
available_strategies: dict = {}


class AddStrategyRequest(BaseModel):
    name: str
    config: dict


class RemoveStrategyRequest(BaseModel):
    name: str
    close_positions: bool = True


@router.get("/status")
async def get_status():
    """获取引擎运行状态"""
    if not engine_runner:
        return {"status": "uninitialized", "uptime_seconds": 0}
    return engine_runner.get_status()


@router.post("/start")
async def start_engine():
    """启动交易引擎"""
    if not engine_runner:
        raise HTTPException(500, "引擎未初始化")
    if engine_runner.is_running:
        raise HTTPException(409, "引擎已在运行中")
    ok = engine_runner.start()
    if not ok:
        raise HTTPException(500, "引擎启动失败，请检查 MT4 连接")
    return {"message": "引擎启动成功"}


@router.post("/stop")
async def stop_engine():
    """停止交易引擎"""
    if not engine_runner:
        raise HTTPException(500, "引擎未初始化")
    if not engine_runner.is_running:
        raise HTTPException(409, "引擎未在运行")
    engine_runner.stop()
    return {"message": "引擎已停止"}


@router.get("/strategies")
async def list_strategies():
    """列出当前引擎中运行的策略"""
    if not engine_runner or not engine_runner._engine:
        return {"running": [], "available": list(available_strategies.keys())}
    with engine_runner._engine._strategies_lock:
        running = [
            {"name": s.name, "magic": s.magic, "timeframe": s.timeframe,
             "double_first": s.double_first, "max_positions": s.max_positions}
            for s in engine_runner._engine.strategies
        ]
    return {"running": running, "available": list(available_strategies.keys())}


@router.post("/strategies/add")
async def add_strategy(req: AddStrategyRequest):
    """动态添加策略（无需重启引擎）"""
    if not engine_runner:
        raise HTTPException(500, "引擎未初始化")
    if not engine_runner.is_running:
        raise HTTPException(409, "引擎未在运行，请先启动")
    ok = engine_runner.add_strategy(req.name, req.config)
    if not ok:
        raise HTTPException(400, f"策略 {req.name} 添加失败（可能已存在或 Magic 冲突）")
    return {"message": f"策略 {req.name} 已添加", "config": req.config}


@router.post("/strategies/remove")
async def remove_strategy(req: RemoveStrategyRequest):
    """动态移除策略（无需重启引擎）"""
    if not engine_runner:
        raise HTTPException(500, "引擎未初始化")
    if not engine_runner.is_running:
        raise HTTPException(409, "引擎未在运行")
    ok = engine_runner.remove_strategy(req.name, req.close_positions)
    if not ok:
        raise HTTPException(404, f"策略 {req.name} 不存在")
    return {"message": f"策略 {req.name} 已移除", "closed_positions": req.close_positions}


@router.get("/health")
async def get_health():
    """Consolidated health check — engine, bridge, account, positions, risk"""
    engine_block = _build_engine_block()
    bridge_block = _build_bridge_block()
    strategies_block = _build_strategies_block()
    account_block = _build_account_block()
    positions_block = _build_positions_block()
    risk_block = _build_risk_block()
    signals_block = _build_signals_block()

    # Derive overall verdict from all blocks
    verdict, reason = _compute_verdict(
        engine_block, bridge_block, risk_block, account_block
    )

    return {
        "verdict": verdict,
        "verdict_reason": reason,
        "engine": engine_block,
        "bridge": bridge_block,
        "account": account_block,
        "positions": positions_block,
        "risk": risk_block,
        "strategies": strategies_block.get("running", []),
        "signals": signals_block,
    }


# ---------------------------------------------------------------------------
# Internal helpers — each builds one block of the health response
# ---------------------------------------------------------------------------

def _build_engine_block() -> dict:
    if not engine_runner:
        return {"status": "uninitialized", "uptime_seconds": 0}
    return engine_runner.get_status()


def _build_bridge_block() -> dict:
    connected = (
        engine_runner is not None
        and engine_runner.bridge is not None
        and hasattr(engine_runner.bridge, "_connected")
        and engine_runner.bridge._connected
    )
    return {
        "connected": connected,
        "host": getattr(settings, "FREEMT4_HOST", "unknown"),
        "port": getattr(settings, "FREEMT4_PORT", 0),
    }


def _build_strategies_block() -> dict:
    if not engine_runner or not engine_runner._engine:
        return {"running": [], "available": list(available_strategies.keys())}
    engine = engine_runner._engine
    with engine._strategies_lock:
        running = [
            {
                "name": s.name,
                "magic": s.magic,
                "timeframe": s.timeframe,
                "double_first": s.double_first,
                "max_positions": s.max_positions,
            }
            for s in engine.strategies
        ]
    return {"running": running, "available": list(available_strategies.keys())}


def _build_account_block() -> dict | None:
    if not engine_runner:
        return None
    return engine_runner._cached_account


def _build_positions_block() -> dict:
    """Aggregate statistics from cached positions."""
    if not engine_runner:
        return {
            "count": 0,
            "total_volume": 0.0,
            "unrealized_pnl": 0.0,
            "longs": {"count": 0, "volume": 0.0, "unrealized_pnl": 0.0},
            "shorts": {"count": 0, "volume": 0.0, "unrealized_pnl": 0.0},
        }

    positions = engine_runner._cached_positions or []
    count = len(positions)
    total_volume = sum(p.get("volume", 0) for p in positions)
    unrealized_pnl = sum(p.get("profit", 0) for p in positions)

    longs = [p for p in positions if p.get("order_type", "").upper() in ("BUY", "OP_BUY")]
    shorts = [p for p in positions if p.get("order_type", "").upper() in ("SELL", "OP_SELL")]

    return {
        "count": count,
        "total_volume": round(total_volume, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "longs": {
            "count": len(longs),
            "volume": round(sum(p.get("volume", 0) for p in longs), 2),
            "unrealized_pnl": round(sum(p.get("profit", 0) for p in longs), 2),
        },
        "shorts": {
            "count": len(shorts),
            "volume": round(sum(p.get("volume", 0) for p in shorts), 2),
            "unrealized_pnl": round(sum(p.get("profit", 0) for p in shorts), 2),
        },
    }


def _build_risk_block() -> dict:
    """Daily P&L and drawdown from engine internal state."""
    if not engine_runner or not engine_runner._engine:
        return {
            "daily_pnl": 0.0,
            "daily_drawdown": 0.0,
            "drawdown_pct": 0.0,
        }

    engine = engine_runner._engine
    start_balance = getattr(engine, "_daily_start_balance", 0.0) or 0.0
    current_balance = engine._get_balance()
    daily_pnl = current_balance - start_balance
    daily_drawdown = 0.0
    drawdown_pct = 0.0

    if daily_pnl < 0:
        daily_drawdown = abs(daily_pnl)
        if start_balance > 0:
            drawdown_pct = round(daily_drawdown / start_balance * 100, 2)

    return {
        "daily_pnl": round(daily_pnl, 2),
        "daily_drawdown": round(daily_drawdown, 2),
        "drawdown_pct": drawdown_pct,
    }


def _build_signals_block() -> dict:
    """Check each strategy for the most recent signal, if tracked."""
    latest = {}
    total_count = 0

    if engine_runner and engine_runner._engine:
        engine = engine_runner._engine
        with engine._strategies_lock:
            for s in engine.strategies:
                candidate = None
                # Strategies implement on_tick() — we check for any
                # stored signal attribute such as last_signal / _last_signal.
                if hasattr(s, "last_signal"):
                    candidate = s.last_signal
                elif hasattr(s, "_last_signal"):
                    candidate = s._last_signal
                if candidate is not None:
                    latest[s.name] = candidate
                    total_count += 1

    return {
        "latest": latest,
        "count": total_count,
    }


def _compute_verdict(
    engine_block: dict,
    bridge_block: dict,
    risk_block: dict,
    account_block: dict | None,
) -> tuple:
    """Return (verdict: str, reason: str) based on current state."""
    reasons: list[str] = []

    # --- RED conditions ---
    eng_status = engine_block.get("status", "uninitialized")
    if eng_status in ("uninitialized", "stopped"):
        return "RED", f"Engine is {eng_status}"

    if eng_status != "running":
        return "RED", f"Engine status is '{eng_status}'"

    # --- YELLOW / RED bridge ---
    bridge_ok = bridge_block.get("connected", False)
    if not bridge_ok:
        return "RED", "Engine running but bridge disconnected"

    # --- RED: critical risk (global loss block) ---
    if engine_runner and engine_runner._engine:
        engine = engine_runner._engine
        if getattr(engine, "_global_loss_blocked", False):
            return "RED", "Global daily loss limit breached — all strategies blocked"

    # --- YELLOW conditions ---
    dd_pct = risk_block.get("drawdown_pct", 0.0)
    max_dd = getattr(settings, "MAX_DAILY_LOSS_PCT", 12.0)
    warning_dd = max_dd * 0.7  # 70 % of limit → YELLOW

    if dd_pct >= max_dd:
        reasons.append(f"Daily drawdown {dd_pct:.1f}% at limit ({max_dd}%)")
    elif dd_pct >= warning_dd:
        reasons.append(f"Daily drawdown {dd_pct:.1f}% approaching limit ({max_dd}%)")

    # Check margin level if we have account data
    if account_block:
        margin = account_block.get("margin", 0)
        equity = account_block.get("equity", 0)
        if margin > 0 and equity > 0:
            margin_level = equity / margin * 100
            if margin_level < 200:
                reasons.append(f"Margin level low ({margin_level:.0f}%)")
            if margin_level < 100:
                return "RED", f"Margin call level ({margin_level:.0f}%)"

    if reasons:
        return "YELLOW", "; ".join(reasons)

    return "GREEN", "All systems operational"
