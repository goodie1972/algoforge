"""
risk_mgr.py — 策略风控状态管理

从 engine_standalone/main.py 渐进式抽离 StrategyRiskState。
风控检查逻辑仍留在 TradingEngine 中（因为需要访问 self.bridge / self._rt），
但 dataclass 独立出来便于测试和将来扩展。
"""
from dataclasses import dataclass, field
from collections import deque
from typing import Optional


@dataclass
class StrategyRiskState:
    """策略风控状态"""
    name: str
    magic: int
    realized_pnl: float = 0.0                     # 累计已实现盈亏
    floating_pnl: float = 0.0                     # 当前浮动盈亏
    exit_timestamps: deque = field(default_factory=deque)  # 快速出场检测窗口
    realized_loss_blocked: bool = False            # 已实现亏损阻断（百分比）
    floating_loss_blocked: bool = False            # 浮动亏损阻断
    rapid_exit_blocked: bool = False               # 快速出场阻断
    realized_loss_amount_blocked: bool = False     # 已实现亏损 ≥$30 阻断
    realized_loss_amount_blocked_at: float = 0.0
    consecutive_losses: int = 0                    # 连续亏损次数
    consecutive_loss_blocked: bool = False         # 连续亏损阻断
    consecutive_loss_blocked_at: float = 0.0
    realized_loss_blocked_at: float = 0.0          # 阻断时间戳
    rapid_exit_blocked_at: float = 0.0


def check_rapid_exit(
    state: StrategyRiskState,
    window_seconds: int,
    max_exits: int,
    now: float,
) -> bool:
    """检查快速出场是否触发阻断

    Args:
        state: 策略风控状态
        window_seconds: 检测窗口秒数
        max_exits: 窗口内最大允许出场次数
        now: 当前时间戳

    Returns:
        True 表示触发阻断
    """
    cutoff = now - window_seconds
    return sum(1 for t in state.exit_timestamps if t >= cutoff) >= max_exits


def prune_exit_window(state: StrategyRiskState, window_seconds: int, now: float) -> None:
    """维护操作：移除窗口外的时间戳，防止 exit_timestamps 无限增长。

    由引擎在每个 tick 主动调用。单独拆出来，是为了让 :func:`check_rapid_exit`
    成为纯查询（不偷偷改状态）。
    """
    while state.exit_timestamps and state.exit_timestamps[0] < now - window_seconds:
        state.exit_timestamps.popleft()


def register_trade_result(state: StrategyRiskState, pnl: float) -> None:
    """根据单笔盈亏更新连续亏损计数（唯一允许修改 consecutive_losses 的地方）。

    - pnl < 0：连续亏损 +1
    - pnl > 0：连续亏损清零
    - pnl == 0：不变（保本/未结算，不计入连亏也不清零）

    注意：本函数只负责「改状态」，不下任何判断结论。是否触发阻断请用
    :func:`check_consecutive_loss` 查询。把「改状态」与「查状态」拆开，
    可以避免把 check 调用两次就重复计数的陷阱。
    """
    if pnl < 0:
        state.consecutive_losses += 1
    elif pnl > 0:
        state.consecutive_losses = 0


def check_consecutive_loss(state: StrategyRiskState, max_consecutive: int) -> bool:
    """纯查询：当前连续亏损次数是否已达阻断阈值（**不修改任何状态**）。

    Args:
        state: 策略风控状态
        max_consecutive: 允许的最大连续亏损次数

    Returns:
        True 表示已达阈值、应触发阻断
    """
    return state.consecutive_losses >= max_consecutive


def check_realized_loss_amount(
    state: StrategyRiskState,
    threshold: float,
) -> bool:
    """检查绝对亏损金额是否触发阻断

    Returns:
        True 表示已实现亏损超过阈值
    """
    return state.realized_pnl <= -threshold


def check_realized_loss_pct(
    state: StrategyRiskState,
    balance: float,
    threshold_pct: float,
) -> bool:
    """检查百分比亏损是否触发阻断

    Returns:
        True 表示亏损百分比超过阈值
    """
    if balance <= 0:
        return False
    loss_pct = abs(state.realized_pnl) / balance * 100
    return state.realized_pnl < 0 and loss_pct >= threshold_pct


def is_rapid_exit_blocked(state: StrategyRiskState, cooldown_seconds: int, now: float) -> bool:
    """快速出场阻断是否仍在冷却期内"""
    if not state.rapid_exit_blocked:
        return False
    return now - state.rapid_exit_blocked_at < cooldown_seconds


def is_consecutive_loss_blocked(state: StrategyRiskState, cooldown_hours: float, now: float) -> bool:
    """连续亏损阻断是否仍在冷却期内"""
    if not state.consecutive_loss_blocked:
        return False
    return now - state.consecutive_loss_blocked_at < cooldown_hours * 3600


def is_realized_loss_blocked(state: StrategyRiskState, cooldown_hours: float, now: float) -> bool:
    """已实现亏损阻断是否仍在冷却期内"""
    if not state.realized_loss_blocked:
        return False
    return now - state.realized_loss_blocked_at < cooldown_hours * 3600


def is_realized_loss_amount_blocked(state: StrategyRiskState, cooldown_hours: float, now: float) -> bool:
    """绝对亏损阻断是否仍在冷却期内"""
    if not state.realized_loss_amount_blocked:
        return False
    return now - state.realized_loss_amount_blocked_at < cooldown_hours * 3600
