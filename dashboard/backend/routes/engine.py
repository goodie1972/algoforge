"""
/api/engine/* 路由 - 引擎启停、状态查询、动态策略管理、健康检查
"""
import logging
import time
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from config import settings
from dashboard.backend.config_service import RuntimeConfig
from data import database as db

_rtc = RuntimeConfig()  # singleton, 所有重叠配置走运行时

router = APIRouter(prefix="/api/engine", tags=["engine"])

# 由 main.py 在启动时注入
engine_runner = None
paper_engine_manager = None
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
    """获取引擎运行状态（含纸面引擎子进程状态）"""
    if not engine_runner:
        return {"status": "uninitialized", "uptime_seconds": 0}
    result = engine_runner.get_status()
    # 附加纸面引擎状态
    if paper_engine_manager is not None:
        result["paper_engine"] = paper_engine_manager.get_status()
    else:
        result["paper_engine"] = {"status": "not_configured"}
    return result


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


@router.post("/restart")
async def restart_engine():
    """一键重启引擎（stop → start），用于纸面/实盘模式切换后重建桥接

    前端契约：保存纸面配置收到 mode_switch=true 且用户确认后调用本接口。
    边界处理：引擎未运行时跳过 stop 直接 start（等价于 /start 的效果），
    start 失败返回 500；引擎未初始化返回 500。
    """
    if not engine_runner:
        raise HTTPException(500, "引擎未初始化")
    was_running = engine_runner.is_running
    if was_running:
        # stop() 内部 join(timeout=15) 同步阻塞，放线程池避免卡死事件循环 ~16s
        await run_in_threadpool(engine_runner.stop)
        if engine_runner.is_running:
            raise HTTPException(503, "旧进程尚未退出，请稍候重试")
    ok = await run_in_threadpool(engine_runner.start)
    if not ok:
        raise HTTPException(500, "引擎重启失败，请检查日志")
    return {"status": "restarted" if was_running else "started"}


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
    """Consolidated health check — engine, bridge, account, positions, risk, database, exit systems"""
    engine_block = _build_engine_block()
    bridge_block = _build_bridge_block()
    strategies_block = _build_strategies_block()
    account_block = _build_account_block()
    positions_block = _build_positions_block()
    risk_block = _build_risk_block()
    signals_block = _build_signals_block()
    database_block = _build_database_block()
    exit_block = _build_exit_systems_block()

    datafactory_block = _build_datafactory_block()
    strategy_blocks_block = _build_strategy_blocks_block()

    # Derive overall verdict from all blocks
    verdict, reason = _compute_verdict(
        engine_block, bridge_block, risk_block, account_block,
        database_block=database_block,
        datafactory_block=datafactory_block,
        positions_block=positions_block,
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
        "database": database_block,
        "exit_systems": exit_block,
        "datafactory": datafactory_block,
        "strategy_blocks": strategy_blocks_block,
    }


# ---------------------------------------------------------------------------
# Internal helpers — each builds one block of the health response
# ---------------------------------------------------------------------------

def _build_engine_block() -> dict:
    if not engine_runner:
        return {"status": "uninitialized", "uptime_seconds": 0}
    block = engine_runner.get_status()
    # 附加纸面引擎状态到 health 端点
    if paper_engine_manager is not None:
        block["paper_engine"] = paper_engine_manager.get_status()
    return block


def _build_datafactory_block() -> dict:
    """DataFactory 健康状况"""
    try:
        from services.data_factory import get_health
        health = get_health()
        now = time.time()
        tfs = health.get("tfs", {})
        ok = True
        issues = []
        for tf, st in tfs.items():
            if not st.get("ok"):
                ok = False
                issues.append(f"{tf}:sync_failed")
            age = now - st.get("last_sync", 0)
            if age > 60:
                ok = False
                issues.append(f"{tf}:stale({age:.0f}s)")
        if not health.get("bridging"):
            ok = False
            issues.append("bridge_disconnected")
        return {
            "ok": ok,
            "bridging": health.get("bridging", False),
            "tfs": {tf: {"ok": st.get("ok"), "candles": st.get("candles", 0),
                         "age_s": round(now - st.get("last_sync", 0), 1)}
                    for tf, st in tfs.items()},
            "tick_age_s": round(now - health.get("last_tick_time", 0), 1) if health.get("last_tick_time") else -1,
            "tick_count": health.get("tick_count", 0),
            "errors": health.get("sync_errors", [])[-5:],
            "issues": issues,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}


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


def _build_database_block() -> dict:
    """Check SQLite database status — table existence, data freshness."""
    import time
    try:
        stats = db.get_db_stats()
        timeframes = list(stats.keys()) if stats else []
        total_candles = sum(v["count"] for v in stats.values()) if stats else 0
        most_recent = max((v["to"] for v in stats.values()), default=0)
        staleness = int(time.time() - most_recent) if most_recent else -1
        return {
            "initialized": len(timeframes) > 0,
            "timeframes_populated": timeframes,
            "total_candles": total_candles,
            "most_recent_timestamp": most_recent,
            "staleness_seconds": staleness,
        }
    except Exception as e:
        return {
            "initialized": False,
            "timeframes_populated": [],
            "total_candles": 0,
            "most_recent_timestamp": 0,
            "staleness_seconds": -1,
            "error": str(e),
        }


def _build_exit_systems_block() -> dict:
    """Audit all exit systems across strategies."""
    if not engine_runner or not engine_runner._engine:
        return {"strategies_with_exits": [], "has_positions": False, "global_loss_blocked": False}

    engine = engine_runner._engine
    has_positions = False
    try:
        positions = getattr(engine_runner, "_cached_positions", []) or []
        has_positions = len(positions) > 0
    except Exception:
        pass

    global_loss_blocked = getattr(engine, "_global_loss_blocked", False)

    strategies_with_exits = []
    with engine._strategies_lock:
        for s in engine.strategies:
            exit_cfg = {
                "name": s.name,
                "magic": s.magic,
                "timeframe": s.timeframe,
            }
            # Extract ATR exit multipliers (common naming across strategies)
            for attr in ("hard_mult", "trail_mult", "profit_trail_mult", "hard_stop_mult"):
                if hasattr(s, attr):
                    exit_cfg[attr] = getattr(s, attr)
            strategies_with_exits.append(exit_cfg)

    return {
        "strategies_with_exits": strategies_with_exits,
        "has_positions": has_positions,
        "global_loss_blocked": global_loss_blocked,
    }


def _build_strategy_blocks_block() -> list[dict]:
    """Per-strategy risk blocking status — exposes exactly why each strategy
    is or isn't allowed to open new positions."""
    if not engine_runner or not engine_runner._engine:
        return []

    engine = engine_runner._engine
    result = []

    # Current positions grouped by magic (from cached data)
    positions_by_magic: dict[int, int] = {}
    cached_positions = engine_runner._cached_positions or []
    for p in cached_positions:
        m = p.get("magic")
        if m is not None:
            positions_by_magic[m] = positions_by_magic.get(m, 0) + 1

    with engine._strategies_lock:
        for s in engine.strategies:
            item = {
                "name": s.name,
                "magic": s.magic,
                "timeframe": s.timeframe,
                "max_positions": getattr(s, "max_positions", 1),
                "holdings": positions_by_magic.get(s.magic, 0),
                "is_blocked": False,
                "block_reason": None,
            }

            # Engine-level blocking check (risk states)
            risk_state = engine._risk_states.get(s.magic)
            if risk_state is not None:
                item["floating_pnl"] = round(risk_state.floating_pnl, 2)
                item["realized_pnl"] = round(risk_state.realized_pnl, 2)
                item["consecutive_losses"] = risk_state.consecutive_losses

                # Blocking states
                now = __import__("time").time()
                blocks = []

                if risk_state.realized_loss_blocked:
                    elapsed = now - risk_state.realized_loss_blocked_at
                    remain_h = max(0, (_rtc.get("per_strategy_loss_block_hours") * 3600 - elapsed) / 3600)
                    blocks.append(f"已实现亏损阻断，剩余 {remain_h:.1f}h")

                if risk_state.floating_loss_blocked:
                    blocks.append(f"浮动亏损阻断 (${abs(risk_state.floating_pnl):.2f})")

                if risk_state.realized_loss_amount_blocked:
                    elapsed = now - risk_state.realized_loss_amount_blocked_at
                    remain_h = max(0, (_rtc.get("per_strategy_loss_block_hours") * 3600 - elapsed) / 3600)
                    blocks.append(f"绝对亏损冷却，剩余 {remain_h:.1f}h")

                if risk_state.consecutive_loss_blocked:
                    elapsed = now - risk_state.consecutive_loss_blocked_at
                    remain_h = max(0, (_rtc.get("consecutive_loss_cooldown_hours") * 3600 - elapsed) / 3600)
                    blocks.append(f"连续亏损冷却，剩余 {remain_h:.1f}h")

                if risk_state.rapid_exit_blocked:
                    elapsed = now - risk_state.rapid_exit_blocked_at
                    remain_m = max(0, (_rtc.get("rapid_exit_cooldown_seconds") - elapsed) / 60)
                    blocks.append(f"快速出场阻断，剩余 {remain_m:.0f}min")

                if blocks:
                    item["is_blocked"] = True
                    item["block_reason"] = "; ".join(blocks)
            else:
                item["floating_pnl"] = 0.0
                item["realized_pnl"] = 0.0
                item["consecutive_losses"] = 0

            result.append(item)

    return result


def _compute_verdict(
    engine_block: dict,
    bridge_block: dict,
    risk_block: dict,
    account_block: dict | None,
    database_block: dict | None = None,
    positions_block: dict | None = None,
    datafactory_block: dict | None = None,
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

    # --- YELLOW: DataFactory health ---
    if datafactory_block:
        if not datafactory_block.get("ok", True):
            issues = datafactory_block.get("issues", [])
            return "YELLOW", f"DataFactory issues: {'; '.join(issues)}"
        # 检查各周期年龄
        tfs = datafactory_block.get("tfs", {})
        stale_tfs = [tf for tf, st in tfs.items() if st.get("age_s", 0) > 120]
        if stale_tfs:
            return "YELLOW", f"DataFactory {', '.join(stale_tfs)} 过期"

    # --- RED: critical risk (global loss block) ---
    if engine_runner and engine_runner._engine:
        engine = engine_runner._engine
        if getattr(engine, "_global_loss_blocked", False):
            return "RED", "Global daily loss limit breached — all strategies blocked"

    # --- YELLOW conditions ---
    dd_pct = risk_block.get("drawdown_pct", 0.0)
    max_dd = _rtc.get("max_daily_loss_pct") or 12.0
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

    # --- Database health check ---
    if database_block:
        if not database_block.get("initialized", False):
            reasons.append("Database not initialized")
        else:
            staleness = database_block.get("staleness_seconds", 0)
            if staleness > 600:  # 10 min stale
                reasons.append(f"Database data stale ({staleness}s old)")
            timeframes = database_block.get("timeframes_populated", [])
            # Engine has strategies but database has no data for any timeframe
            if engine_runner and engine_runner._engine and not timeframes:
                reasons.append("No timeframe data in database")

    # --- Exit systems check: positions open but no exit config? ---
    if positions_block and positions_block.get("count", 0) > 0:
        # If there are open positions, we expect exit configs
        if not engine_runner or not engine_runner._engine:
            reasons.append("Positions exist but engine not running")
        elif getattr(engine_runner._engine, "_global_loss_blocked", False):
            pass  # already RED above

    if reasons:
        return "YELLOW", "; ".join(reasons)

    return "GREEN", "All systems operational"
