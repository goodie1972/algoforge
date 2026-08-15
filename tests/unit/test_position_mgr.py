"""PositionMgrMixin 单元测试 — 仓位管理和风控阻断逻辑"""
import time
import pytest
from unittest.mock import MagicMock, patch
from collections import deque
from engine_standalone.position_mgr import PositionMgrMixin
from engine_standalone.risk_mgr import StrategyRiskState


class FakeEngine(PositionMgrMixin):
    """测试用引擎"""
    def __init__(self):
        self.bridge = MagicMock()
        self.strategies = []
        self._risk_states = {}
        self._known_position_count = {}
        self._entry_times = {}
        self._entry_signal_data = {}
        self._profit_exit_cooldown = {}
        self._closed_trades = []
        self._trades_file = "/tmp/test_trades.jsonl"
        self._daily_start_balance = 5000.0
        self._global_loss_blocked = False
        self._last_balance_check = 0

    def _get_balance(self):
        return 5000.0

    def _strategy_magics(self, strategy):
        return {strategy.magic}

    def _mt4_to_local(self, ts):
        from datetime import datetime
        return datetime.fromtimestamp(ts)

    def _rt(self, key, default=None):
        defaults = {
            'rapid_exit_window_seconds': 3600, 'max_rapid_exits': 3,
            'rapid_exit_cooldown_seconds': 7200,
            'max_consecutive_losses': 3,
            'consecutive_loss_cooldown_hours': 4,
            'per_strategy_realized_loss_amount': 30,
            'per_strategy_loss_block_hours': 12,
            'per_strategy_realized_loss_pct': 10,
            'floating_loss_block_pct': 15,
            'max_daily_loss_pct': 12,
            'profit_exit_cooldown_hours': 6,
            'lot_size': 0.01,
        }
        return defaults.get(key, default)

    def _pos_open_time(self, pos):
        return ("2026-08-15 10:00:00", 1723702800)


def make_state(magic=660706, name="test"):
    """创建测试用风控状态"""
    state = MagicMock(spec=StrategyRiskState)
    state.magic = magic
    state.name = name
    state.realized_pnl = 0.0
    state.floating_pnl = 0.0
    state.exit_timestamps = deque()
    state.rapid_exit_blocked = False
    state.rapid_exit_blocked_at = 0
    state.consecutive_losses = 0
    state.consecutive_loss_blocked = False
    state.consecutive_loss_blocked_at = 0
    state.realized_loss_blocked = False
    state.realized_loss_blocked_at = 0
    state.realized_loss_amount_blocked = False
    state.realized_loss_amount_blocked_at = 0
    state.floating_loss_blocked = False
    return state


def test_record_close_basic():
    """平仓记录基本逻辑"""
    engine = FakeEngine()
    state = make_state()
    engine._risk_states[660706] = state
    engine._entry_times[1001] = time.time()
    engine._known_position_count[660706] = 1

    engine._record_close(1001, 10.0, 660706, "BUY")
    assert state.realized_pnl == 10.0
    assert 1001 not in engine._entry_times
    assert engine._known_position_count[660706] == 0
    assert state.consecutive_losses == 0


def test_record_close_loss_increments_consecutive():
    """亏损平仓增加连续亏损计数"""
    engine = FakeEngine()
    state = make_state()
    engine._risk_states[660706] = state

    engine._record_close(1002, -5.0, 660706, "SELL")
    assert state.consecutive_losses == 1
    assert state.realized_pnl == -5.0


def test_record_close_triggers_rapid_exit_block():
    """快速出场触发阻断"""
    engine = FakeEngine()
    state = make_state()
    engine._risk_states[660706] = state

    # 3 次快速出场
    for i in range(3):
        engine._record_close(1000 + i, -1.0, 660706, "BUY")
        time.sleep(0.01)

    assert state.rapid_exit_blocked is True


def test_record_close_triggers_consecutive_loss_block():
    """连续亏损触发阻断"""
    engine = FakeEngine()
    state = make_state()
    engine._risk_states[660706] = state

    for i in range(3):
        engine._record_close(1000 + i, -1.0, 660706, "BUY")

    assert state.consecutive_loss_blocked is True


def test_record_close_triggers_abs_loss_block():
    """绝对亏损触发阻断"""
    engine = FakeEngine()
    state = make_state()
    engine._risk_states[660706] = state

    engine._record_close(1000, -35.0, 660706, "BUY")
    assert state.realized_loss_amount_blocked is True


def test_record_close_triggers_pct_loss_block():
    """百分比亏损触发阻断"""
    engine = FakeEngine()
    state = make_state()
    engine._risk_states[660706] = state

    # -550 = 11% of 5000, threshold is 10%
    engine._record_close(1000, -550.0, 660706, "BUY")
    assert state.realized_loss_blocked is True


def test_record_close_profit_resets_consecutive():
    """盈利平仓重置连续亏损"""
    engine = FakeEngine()
    state = make_state()
    state.consecutive_losses = 2
    engine._risk_states[660706] = state

    engine._record_close(1000, 5.0, 660706, "BUY")
    assert state.consecutive_losses == 0


def test_record_close_unknown_magic():
    """未知 magic 不报错"""
    engine = FakeEngine()
    # No risk_states for magic 999
    engine._record_close(1000, 5.0, 999, "BUY")
    # Should not raise


def test_check_global_loss_clear():
    """全局亏损检查 - 正常"""
    engine = FakeEngine()
    assert engine._check_global_loss() is False


def test_check_global_loss_triggered():
    """全局亏损检查 - 触发"""
    engine = FakeEngine()
    engine._daily_start_balance = 5000.0
    # Mock balance to 4000 (20% loss, > 12% threshold)
    engine._get_balance = lambda: 4000.0
    engine._last_balance_check = 0
    assert engine._check_global_loss() is True
    assert engine._global_loss_blocked is True


def test_check_global_loss_throttle():
    """全局亏损检查 - 5分钟节流"""
    engine = FakeEngine()
    engine._global_loss_blocked = True
    engine._last_balance_check = time.time()
    # Should return cached value without checking
    assert engine._check_global_loss() is True


def test_is_strategy_blocked_clear():
    """策略未阻断"""
    engine = FakeEngine()
    state = make_state()
    engine._risk_states[660706] = state
    assert engine._is_strategy_blocked(660706) is None


def test_is_strategy_blocked_realized_loss():
    """策略被已实现亏损阻断"""
    engine = FakeEngine()
    state = make_state()
    state.realized_loss_blocked = True
    state.realized_loss_blocked_at = time.time()
    engine._risk_states[660706] = state
    result = engine._is_strategy_blocked(660706)
    assert result is not None
    assert "已实现亏损" in result


def test_is_strategy_blocked_expired():
    """已实现亏损阻断到期自动解除"""
    engine = FakeEngine()
    state = make_state()
    state.realized_loss_blocked = True
    state.realized_loss_blocked_at = time.time() - 13 * 3600  # 13h ago, > 12h threshold
    engine._risk_states[660706] = state
    assert engine._is_strategy_blocked(660706) is None
    assert state.realized_loss_blocked is False


def test_is_strategy_blocked_unknown_magic():
    """未知 magic 返回 None"""
    engine = FakeEngine()
    assert engine._is_strategy_blocked(999) is None


def test_is_strategy_blocked_rapid_exit():
    """快速出场阻断"""
    engine = FakeEngine()
    state = make_state()
    state.rapid_exit_blocked = True
    state.rapid_exit_blocked_at = time.time()
    engine._risk_states[660706] = state
    result = engine._is_strategy_blocked(660706)
    assert "快速出场" in result


def test_is_strategy_blocked_consecutive_loss():
    """连续亏损阻断"""
    engine = FakeEngine()
    state = make_state()
    state.consecutive_loss_blocked = True
    state.consecutive_loss_blocked_at = time.time()
    engine._risk_states[660706] = state
    result = engine._is_strategy_blocked(660706)
    assert "连续亏损" in result


def test_is_strategy_blocked_floating_loss():
    """浮动亏损阻断"""
    engine = FakeEngine()
    state = make_state()
    state.floating_loss_blocked = True
    state.floating_pnl = -800.0  # 16% > 15% threshold
    engine._risk_states[660706] = state
    result = engine._is_strategy_blocked(660706)
    assert "浮动亏损" in result


def test_is_strategy_blocked_floating_loss_recovered():
    """浮动亏损恢复后解除"""
    engine = FakeEngine()
    state = make_state()
    state.floating_loss_blocked = True
    state.floating_pnl = -100.0  # 2% < 15% threshold
    engine._risk_states[660706] = state
    assert engine._is_strategy_blocked(660706) is None
    assert state.floating_loss_blocked is False


def test_is_strategy_blocked_abs_loss():
    """绝对亏损阻断"""
    engine = FakeEngine()
    state = make_state()
    state.realized_loss_amount_blocked = True
    state.realized_loss_amount_blocked_at = time.time()
    engine._risk_states[660706] = state
    result = engine._is_strategy_blocked(660706)
    assert "绝对亏损" in result


def test_update_floating_pnl():
    """更新浮动盈亏"""
    engine = FakeEngine()
    state = make_state()
    state.magic = 660706
    engine._risk_states[660706] = state

    strategy = MagicMock()
    strategy.magic = 660706
    strategy.legacy_magics = []
    engine.strategies = [strategy]

    pos1 = MagicMock()
    pos1.magic = 660706
    pos1.profit = 5.0
    pos2 = MagicMock()
    pos2.magic = 999
    pos2.profit = 3.0
    engine.bridge.get_positions.return_value = [pos1, pos2]

    engine._update_floating_pnl()
    assert state.floating_pnl == 5.0  # only pos1 matches
