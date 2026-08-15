"""
events.py — 引擎日志和状态报告的纯函数

从 engine_standalone/main.py 渐进式抽离。
这些函数不依赖 self 状态，可安全独立测试。
"""
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)


def format_status_report(
    running: bool,
    uptime: float,
    bridge_connected: bool,
    strategy_count: int,
    position_count: int,
    balance: float,
    equity: float,
    floating_pnl: float,
    daily_pnl: float,
    paper_mode: bool = False,
) -> dict:
    """格式化引擎状态报告"""
    return {
        "status": "running" if running else "stopped",
        "uptime_seconds": round(uptime, 1),
        "started_at": datetime.fromtimestamp(time.time() - uptime).isoformat() if uptime > 0 else None,
        "bridge_connected": bridge_connected,
        "strategy_count": strategy_count,
        "position_count": position_count,
        "balance": round(balance, 2),
        "equity": round(equity, 2),
        "floating_pnl": round(floating_pnl, 2),
        "daily_pnl": round(daily_pnl, 2),
        "paper_mode": paper_mode,
    }


def format_trade_close_log(
    ticket: int | str,
    strategy_name: str,
    direction: str,
    pnl: float,
    hold_seconds: int,
    exit_reason: str = "",
) -> str:
    """格式化平仓日志"""
    hold_str = f"{hold_seconds // 60}m{hold_seconds % 60}s" if hold_seconds > 0 else "0s"
    sign = "+" if pnl >= 0 else ""
    return (
        f"[Close] {strategy_name} {direction} ticket={ticket} "
        f"pnl={sign}${pnl:.2f} hold={hold_str} reason={exit_reason}"
    )


def format_entry_log(
    strategy_name: str,
    direction: str,
    price: float,
    volume: float,
    magic: int,
    score: int = 0,
) -> str:
    """格式化入场日志"""
    return (
        f"[Entry] {strategy_name} {direction} price={price:.2f} "
        f"vol={volume} magic={magic} score={score}"
    )


def format_risk_block_log(
    strategy_name: str,
    block_type: str,
    threshold: str,
    cooldown: str,
) -> str:
    """格式化风控阻断日志"""
    return (
        f"[{strategy_name}] {block_type} 阻断: {threshold}，冷却 {cooldown}"
    )
