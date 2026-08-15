"""EntryExitMixin 单元测试 — 入场出场逻辑"""
import time
import pytest
from unittest.mock import MagicMock, patch
from engine_standalone.entry_exit import EntryExitMixin


class FakeEngine(EntryExitMixin):
    """测试用引擎"""
    def __init__(self):
        self.bridge = MagicMock()
        self.strategies = []
        self._risk_states = {}
        self._known_position_count = {}
        self._entry_times = {}
        self._entry_signal_data = {}
        self._closed_trades = []
        self._trades_file = "/tmp/test_trades.jsonl"
        self._peak_profit = {}

    def _get_balance(self):
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

    def _strategy_magics(self, strategy):
        return {strategy.magic}

    def _record_close(self, ticket, pnl, magic, direction=""):
        pass

    def _check_global_loss(self):
        return False

    def _is_market_open(self):
        return True

    def _is_safety_locked(self):
        return False

    def _check_news_blackout(self):
        return False

    def _check_news_bias_block(self):
        return False

    def _is_strategy_blocked(self, magic):
        return None

    def _mtf_resonance_allowed(self, signal_dir):
        return None

    def _coordinated_exits(self, snapshot):
        pass

    def _check_trend_reverse_tp(self):
        pass

    def _check_floating_loss_blocks(self):
        pass

    def _update_floating_pnl(self):
        pass


def make_strategy(magic=660706, name="test"):
    """创建测试策略"""
    s = MagicMock()
    s.magic = magic
    s.name = name
    s.score_threshold = 5
    s.last_atr = 2.0
    s.last_factors = {}
    s.last_values = {}
    s.last_scores = {}
    s.legacy_magics = []
    return s


def test_execute_buy_success():
    """成功买入"""
    engine = FakeEngine()
    strategy = make_strategy()
    engine.bridge.get_tick_price.return_value = (4350.0, 4352.0)
    engine.bridge.send_order.return_value = 10001

    engine._execute_buy(strategy)
    assert engine._known_position_count[660706] == 1
    assert 10001 in engine._entry_times
    assert engine.bridge.send_order.called


def test_execute_buy_max_positions():
    """达到最大持仓不买入"""
    engine = FakeEngine()
    strategy = make_strategy()
    engine._known_position_count[660706] = 1  # Already at max

    engine._execute_buy(strategy)
    assert not engine.bridge.send_order.called


def test_execute_buy_invalid_price():
    """无效价格不买入"""
    engine = FakeEngine()
    strategy = make_strategy()
    engine.bridge.get_tick_price.return_value = (4350.0, 0)

    engine._execute_buy(strategy)
    assert not engine.bridge.send_order.called


def test_execute_sell_success():
    """成功卖出"""
    engine = FakeEngine()
    strategy = make_strategy()
    engine.bridge.get_tick_price.return_value = (4350.0, 4352.0)
    engine.bridge.send_order.return_value = 10002

    engine._execute_sell(strategy)
    assert engine._known_position_count[660706] == 1
    assert 10002 in engine._entry_times


def test_execute_sell_max_positions():
    """达到最大持仓不卖出"""
    engine = FakeEngine()
    strategy = make_strategy()
    engine._known_position_count[660706] = 1

    engine._execute_sell(strategy)
    assert not engine.bridge.send_order.called


def test_execute_sell_invalid_price():
    """无效价格不卖出"""
    engine = FakeEngine()
    strategy = make_strategy()
    engine.bridge.get_tick_price.return_value = (0, 4352.0)

    engine._execute_sell(strategy)
    assert not engine.bridge.send_order.called


def test_run_strategy_blocked_global_loss():
    """全局亏损时跳过策略"""
    engine = FakeEngine()
    strategy = make_strategy()
    engine._check_global_loss = lambda: True
    engine._run_strategy(strategy)
    # Should return early without calling bridge
    assert not engine.bridge.get_positions.called


def test_run_strategy_market_closed():
    """市场关闭时跳过"""
    engine = FakeEngine()
    strategy = make_strategy()
    engine._is_market_open = lambda: False
    engine._run_strategy(strategy)
    assert not engine.bridge.get_positions.called


def test_run_strategy_safety_locked():
    """安全锁激活时跳过"""
    engine = FakeEngine()
    strategy = make_strategy()
    engine._is_safety_locked = lambda: True
    engine._run_strategy(strategy)
    assert not engine.bridge.get_positions.called


def test_run_strategy_news_blackout():
    """新闻禁售期跳过"""
    engine = FakeEngine()
    strategy = make_strategy()
    engine._check_news_blackout = lambda: True
    engine._run_strategy(strategy)
    assert not engine.bridge.get_positions.called


def test_run_strategy_blocked():
    """策略被阻断时跳过"""
    engine = FakeEngine()
    strategy = make_strategy()
    engine._is_strategy_blocked = lambda m: "blocked"
    engine._run_strategy(strategy)
    assert not engine.bridge.get_positions.called


def test_run_strategy_no_signal():
    """无信号时跳过"""
    engine = FakeEngine()
    strategy = make_strategy()
    strategy.get_signal.return_value = None
    engine._run_strategy(strategy)
    # Should not call send_order
    assert not engine.bridge.send_order.called


def test_run_strategy_low_score():
    """评分不足时跳过"""
    engine = FakeEngine()
    strategy = make_strategy()
    strategy.get_signal.return_value = {"direction": "BUY", "score": 2}
    strategy.score_threshold = 5
    engine._run_strategy(strategy)
    assert not engine.bridge.send_order.called


def test_run_strategy_buy_signal():
    """买入信号执行"""
    engine = FakeEngine()
    strategy = make_strategy()
    strategy.get_signal.return_value = {"direction": "BUY", "score": 6, "id": 1}
    engine.bridge.get_tick_price.return_value = (4350.0, 4352.0)
    engine.bridge.send_order.return_value = 10001

    engine._run_strategy(strategy)
    assert engine.bridge.send_order.called


def test_run_strategy_sell_signal():
    """卖出信号执行"""
    engine = FakeEngine()
    strategy = make_strategy()
    strategy.get_signal.return_value = {"direction": "SELL", "score": 6, "id": 1}
    engine.bridge.get_tick_price.return_value = (4350.0, 4352.0)
    engine.bridge.send_order.return_value = 10002

    engine._run_strategy(strategy)
    assert engine.bridge.send_order.called


def test_run_strategy_exception():
    """策略异常不崩溃"""
    engine = FakeEngine()
    strategy = make_strategy()
    strategy.get_signal.side_effect = Exception("test error")
    # Should not raise
    engine._run_strategy(strategy)


def test_lock_new_entries():
    """锁定新入场"""
    engine = FakeEngine()
    engine._lock_new_entries("test")
    assert engine._entries_locked is True
    assert engine._lock_reason == "test"


def test_get_midline_returns_value():
    """获取中线返回值"""
    engine = FakeEngine()
    strategy = make_strategy()
    strategy.get_indicators.return_value = {"sma_14": 4340.5}
    pos = MagicMock()
    mid = engine._get_midline(strategy, pos)
    assert mid == 4340.5


def test_get_midline_fallback():
    """获取中线回退到 sma_20"""
    engine = FakeEngine()
    strategy = make_strategy()
    strategy.get_indicators.return_value = {"sma_20": 4345.0}
    pos = MagicMock()
    mid = engine._get_midline(strategy, pos)
    assert mid == 4345.0


def test_get_midline_exception():
    """获取中线异常返回 None"""
    engine = FakeEngine()
    strategy = make_strategy()
    strategy.get_indicators.side_effect = Exception("fail")
    pos = MagicMock()
    mid = engine._get_midline(strategy, pos)
    assert mid is None
