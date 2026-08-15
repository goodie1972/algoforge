"""
risk_mgr 单元测试 — 验证风控状态管理和阻断逻辑
"""
import pytest
import time
from collections import deque
from engine_standalone.risk_mgr import (
    StrategyRiskState,
    check_rapid_exit,
    check_consecutive_loss,
    check_realized_loss_amount,
    check_realized_loss_pct,
    is_rapid_exit_blocked,
    is_consecutive_loss_blocked,
    is_realized_loss_blocked,
    is_realized_loss_amount_blocked,
)


class TestStrategyRiskState:
    def test_default_values(self):
        state = StrategyRiskState(name="test", magic=100)
        assert state.realized_pnl == 0.0
        assert state.floating_pnl == 0.0
        assert state.realized_loss_blocked is False
        assert state.consecutive_losses == 0

    def test_exit_timestamps_is_deque(self):
        state = StrategyRiskState(name="test", magic=100)
        assert isinstance(state.exit_timestamps, deque)


class TestRapidExit:
    def test_below_threshold(self):
        """出场次数未达阈值"""
        state = StrategyRiskState(name="test", magic=100)
        now = time.time()
        state.exit_timestamps.append(now - 10)
        state.exit_timestamps.append(now - 5)
        triggered = check_rapid_exit(state, window_seconds=300, max_exits=5, now=now)
        assert triggered is False

    def test_at_threshold(self):
        """出场次数达到阈值"""
        state = StrategyRiskState(name="test", magic=100)
        now = time.time()
        for i in range(5):
            state.exit_timestamps.append(now - i)
        triggered = check_rapid_exit(state, window_seconds=300, max_exits=5, now=now)
        assert triggered is True

    def test_old_timestamps_cleaned(self):
        """窗口外的时间戳被清除"""
        state = StrategyRiskState(name="test", magic=100)
        now = time.time()
        state.exit_timestamps.append(now - 500)  # 窗口外
        state.exit_timestamps.append(now - 10)    # 窗口内
        triggered = check_rapid_exit(state, window_seconds=300, max_exits=5, now=now)
        assert triggered is False
        assert len(state.exit_timestamps) == 1  # 只剩窗口内


class TestConsecutiveLoss:
    def test_loss_increments(self):
        state = StrategyRiskState(name="test", magic=100)
        check_consecutive_loss(state, pnl=-10, max_consecutive=3)
        assert state.consecutive_losses == 1

    def test_win_resets(self):
        state = StrategyRiskState(name="test", magic=100)
        state.consecutive_losses = 3
        check_consecutive_loss(state, pnl=10, max_consecutive=3)
        assert state.consecutive_losses == 0

    def test_threshold_reached(self):
        state = StrategyRiskState(name="test", magic=100)
        for _ in range(3):
            check_consecutive_loss(state, pnl=-10, max_consecutive=3)
        assert state.consecutive_losses == 3

    def test_zero_pnl_no_change(self):
        state = StrategyRiskState(name="test", magic=100)
        state.consecutive_losses = 2
        check_consecutive_loss(state, pnl=0, max_consecutive=3)
        assert state.consecutive_losses == 2


class TestRealizedLossAmount:
    def test_above_threshold(self):
        state = StrategyRiskState(name="test", magic=100)
        state.realized_pnl = -35.0
        assert check_realized_loss_amount(state, threshold=30.0) is True

    def test_below_threshold(self):
        state = StrategyRiskState(name="test", magic=100)
        state.realized_pnl = -15.0
        assert check_realized_loss_amount(state, threshold=30.0) is False

    def test_positive_pnl(self):
        state = StrategyRiskState(name="test", magic=100)
        state.realized_pnl = 10.0
        assert check_realized_loss_amount(state, threshold=30.0) is False


class TestRealizedLossPct:
    def test_above_threshold(self):
        state = StrategyRiskState(name="test", magic=100)
        state.realized_pnl = -50.0
        assert check_realized_loss_pct(state, balance=500.0, threshold_pct=5.0) is True

    def test_below_threshold(self):
        state = StrategyRiskState(name="test", magic=100)
        state.realized_pnl = -5.0
        assert check_realized_loss_pct(state, balance=500.0, threshold_pct=5.0) is False

    def test_positive_pnl(self):
        state = StrategyRiskState(name="test", magic=100)
        state.realized_pnl = 20.0
        assert check_realized_loss_pct(state, balance=500.0, threshold_pct=5.0) is False

    def test_zero_balance(self):
        state = StrategyRiskState(name="test", magic=100)
        state.realized_pnl = -100.0
        assert check_realized_loss_pct(state, balance=0, threshold_pct=5.0) is False


class TestBlockCheckCooldowns:
    def test_rapid_exit_in_cooldown(self):
        state = StrategyRiskState(name="test", magic=100)
        state.rapid_exit_blocked = True
        state.rapid_exit_blocked_at = time.time() - 100
        assert is_rapid_exit_blocked(state, cooldown_seconds=300, now=time.time()) is True

    def test_rapid_exit_cooldown_expired(self):
        state = StrategyRiskState(name="test", magic=100)
        state.rapid_exit_blocked = True
        state.rapid_exit_blocked_at = time.time() - 400
        assert is_rapid_exit_blocked(state, cooldown_seconds=300, now=time.time()) is False

    def test_consecutive_loss_in_cooldown(self):
        state = StrategyRiskState(name="test", magic=100)
        state.consecutive_loss_blocked = True
        state.consecutive_loss_blocked_at = time.time() - 1800
        assert is_consecutive_loss_blocked(state, cooldown_hours=1.0, now=time.time()) is True

    def test_consecutive_loss_expired(self):
        state = StrategyRiskState(name="test", magic=100)
        state.consecutive_loss_blocked = True
        state.consecutive_loss_blocked_at = time.time() - 4000
        assert is_consecutive_loss_blocked(state, cooldown_hours=1.0, now=time.time()) is False

    def test_not_blocked(self):
        state = StrategyRiskState(name="test", magic=100)
        assert is_rapid_exit_blocked(state, cooldown_seconds=300, now=time.time()) is False
        assert is_consecutive_loss_blocked(state, cooldown_hours=1.0, now=time.time()) is False
        assert is_realized_loss_blocked(state, cooldown_hours=1.0, now=time.time()) is False
        assert is_realized_loss_amount_blocked(state, cooldown_hours=1.0, now=time.time()) is False
