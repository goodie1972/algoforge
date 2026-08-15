"""CoreLoopMixin 单元测试 — 主循环逻辑"""
import pytest
import time
from unittest.mock import MagicMock, patch
from engine_standalone.core_loop import CoreLoopMixin
from engine_standalone.entry_exit import EntryExitMixin


class FakeEngine(CoreLoopMixin, EntryExitMixin):
    """最小化测试用引擎"""
    def __init__(self):
        self.bridge = MagicMock()
        self.strategies = []
        self._risk_states = {}
        self._entries_locked = False
        self._lock_time = 0
        self._last_status_report = 0
        self._start_time = time.time()
        self._daily_start_balance = 5000.0
        self._global_loss_blocked = False
        self._last_balance_check = 0
        self.news_filter = MagicMock()
        self._known_position_count = {}
        self._entry_times = {}
        self._entry_signal_data = {}
        self._profit_exit_cooldown = {}
        self._closed_trades = []
        self._trades_file = "/tmp/test_trades.jsonl"
        self._peak_profit = {}

    def _get_balance(self):
        return 5000.0

    def _get_equity(self):
        return 5000.0

    def _rt(self, key, default=None):
        defaults = {
            'max_positions': 1, 'lot_size': 0.01,
            'p_hard_atr': 1.2, 'p_take_profit_atr': 2.0,
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
        }
        return defaults.get(key, default)

    def _update_floating_pnl(self):
        pass

    def _check_floating_loss_blocks(self):
        pass

    def _run_strategy(self, strategy):
        pass

    def _coordinated_exits(self, snapshot):
        pass

    def _check_trend_reverse_tp(self):
        pass

    def _sync_market_data(self):
        pass


def test_is_market_open_weekday():
    """工作日市场开放"""
    from datetime import datetime
    engine = FakeEngine()
    # Mock datetime to Wednesday 10am
    with patch('engine_standalone.core_loop.datetime') as mock_dt:
        mock_dt.now.return_value = datetime(2026, 8, 13, 10, 0)  # Wednesday
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        assert engine._is_market_open() is True


def test_is_market_open_saturday():
    """周六休市"""
    from datetime import datetime
    engine = FakeEngine()
    with patch('engine_standalone.core_loop.datetime') as mock_dt:
        mock_dt.now.return_value = datetime(2026, 8, 15, 10, 0)  # Saturday
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        assert engine._is_market_open() is False


def test_is_market_open_sunday_before_7():
    """周日凌晨休市"""
    from datetime import datetime
    engine = FakeEngine()
    with patch('engine_standalone.core_loop.datetime') as mock_dt:
        mock_dt.now.return_value = datetime(2026, 8, 16, 6, 0)  # Sunday 6am
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        assert engine._is_market_open() is False


def test_is_market_open_sunday_after_7():
    """周日7点后开市"""
    from datetime import datetime
    engine = FakeEngine()
    with patch('engine_standalone.core_loop.datetime') as mock_dt:
        mock_dt.now.return_value = datetime(2026, 8, 16, 8, 0)  # Sunday 8am
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
        assert engine._is_market_open() is True


def test_is_safety_locked_not_locked():
    """安全锁未激活"""
    engine = FakeEngine()
    engine._entries_locked = False
    assert engine._is_safety_locked() is False


def test_is_safety_locked_active():
    """安全锁激活"""
    engine = FakeEngine()
    engine._entries_locked = True
    engine._lock_time = time.time()
    assert engine._is_safety_locked() is True


def test_is_safety_locked_expired():
    """安全锁超时自动解除"""
    engine = FakeEngine()
    engine._entries_locked = True
    engine._lock_time = time.time() - 3700  # > 1 hour ago
    assert engine._is_safety_locked() is False
    assert engine._entries_locked is False


def test_status_report_format():
    """状态报告格式"""
    engine = FakeEngine()
    report = engine._status_report()
    assert "uptime=" in report
    assert "balance=" in report
    assert "positions=" in report


def test_check_status_report_throttle():
    """状态报告5分钟节流"""
    engine = FakeEngine()
    engine._last_status_report = time.time()
    # Should not report (within 300s)
    engine._check_status_report()
    # Force report
    engine._last_status_report = time.time() - 301
    engine._check_status_report()
    assert engine._last_status_report >= time.time() - 1


def test_check_news_blackout_blocked():
    """新闻禁售期检查 - 被阻断"""
    engine = FakeEngine()
    engine.news_filter.is_in_blackout.return_value = (True, "FOMC")
    with patch('engine_standalone.core_loop.time.sleep'):
        assert engine._check_news_blackout() is True


def test_check_news_blackout_clear():
    """新闻禁售期检查 - 正常"""
    engine = FakeEngine()
    engine.news_filter.is_in_blackout.return_value = (False, "")
    assert engine._check_news_blackout() is False


def test_check_news_bias_block_active():
    """新闻偏向阻断 - 激活"""
    engine = FakeEngine()
    engine.news_filter.get_current_bias.return_value = {"block_trading": True, "direction": "bearish"}
    assert engine._check_news_bias_block() is True


def test_check_news_bias_block_inactive():
    """新闻偏向阻断 - 未激活"""
    engine = FakeEngine()
    engine.news_filter.get_current_bias.return_value = None
    assert engine._check_news_bias_block() is False


def test_check_news_bias_block_exception():
    """新闻偏向阻断 - 异常时放行"""
    engine = FakeEngine()
    engine.news_filter.get_current_bias.side_effect = Exception("fail")
    assert engine._check_news_bias_block() is False


def test_lock_new_entries():
    """锁定新入场"""
    engine = FakeEngine()
    engine._lock_new_entries("test_reason")
    assert engine._entries_locked is True
    assert engine._lock_reason == "test_reason"
