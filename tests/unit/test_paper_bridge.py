"""
PaperBridge 单元测试 — 验证持仓数据类和 SL/TP 逻辑

Position 定义在 core/bridge.py，是 dataclass。
PaperBridge 的 SL/TP 触发逻辑在 _run_exits 中，无法直接单元测试，
这里测试 Position 数据类的正确性。
"""
import pytest
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.bridge import Position


class TestPosition:
    """Position 数据类测试"""

    def test_position_creation(self):
        """基本持仓创建"""
        pos = Position(
            ticket=10001,
            symbol="XAUUSD",
            order_type="buy",
            volume=0.01,
            open_price=4389.0,
            current_price=4389.0,
            stop_loss=4350.0,
            take_profit=4420.0,
            profit=0.0,
            swap=0.0,
            commission=0.0,
            magic=880306,
            comment="test",
            open_time="2026-08-14 20:00:00",
        )
        assert pos.ticket == 10001
        assert pos.order_type == "buy"
        assert pos.open_price == 4389.0
        assert pos.stop_loss == 4350.0

    def test_position_sell(self):
        """卖单创建"""
        pos = Position(
            ticket=10002,
            symbol="XAUUSD",
            order_type="sell",
            volume=0.01,
            open_price=4389.0,
            current_price=4380.0,
            stop_loss=4410.0,
            take_profit=4350.0,
            profit=9.0,
            swap=0.0,
            commission=0.0,
            magic=880306,
            comment="test",
            open_time="2026-08-14 20:00:00",
        )
        assert pos.order_type == "sell"
        assert pos.profit == 9.0

    def test_position_stop_loss(self):
        """止损价位正确"""
        pos = Position(
            ticket=10003,
            symbol="XAUUSD",
            order_type="buy",
            volume=0.01,
            open_price=4380.0,
            current_price=4380.0,
            stop_loss=4350.0,
            take_profit=4420.0,
            profit=0.0,
            swap=0.0,
            commission=0.0,
            magic=880306,
            comment="",
            open_time="2026-08-14 20:00:00",
        )
        # 买单止损在下方
        assert pos.stop_loss < pos.open_price
        # 买单止盈在上方
        assert pos.take_profit > pos.open_price

    def test_position_sell_sl_tp(self):
        """卖单 SL/TP 方向正确"""
        pos = Position(
            ticket=10004,
            symbol="XAUUSD",
            order_type="sell",
            volume=0.01,
            open_price=4380.0,
            current_price=4380.0,
            stop_loss=4410.0,
            take_profit=4350.0,
            profit=0.0,
            swap=0.0,
            commission=0.0,
            magic=880306,
            comment="",
            open_time="2026-08-14 20:00:00",
        )
        # 卖单止损在上方
        assert pos.stop_loss > pos.open_price
        # 卖单止盈在下方
        assert pos.take_profit < pos.open_price


class TestSLTPLogic:
    """SL/TP 触发逻辑测试（纯函数，不依赖桥接）"""

    def _should_close_buy(self, current_price, open_price, sl, tp):
        """模拟买单 SL/TP 触发判断"""
        if sl > 0 and current_price <= sl:
            return "stop_loss"
        if tp > 0 and current_price >= tp:
            return "take_profit"
        return None

    def _should_close_sell(self, current_price, open_price, sl, tp):
        """模拟卖单 SL/TP 触发判断"""
        if sl > 0 and current_price >= sl:
            return "stop_loss"
        if tp > 0 and current_price <= tp:
            return "take_profit"
        return None

    def test_buy_stop_loss_trigger(self):
        """买单触发止损"""
        result = self._should_close_buy(4350.0, 4380.0, 4350.0, 4420.0)
        assert result == "stop_loss"

    def test_buy_take_profit_trigger(self):
        """买单触发止盈"""
        result = self._should_close_buy(4420.0, 4380.0, 4350.0, 4420.0)
        assert result == "take_profit"

    def test_sell_stop_loss_trigger(self):
        """卖单触发止损"""
        result = self._should_close_sell(4410.0, 4380.0, 4410.0, 4350.0)
        assert result == "stop_loss"

    def test_sell_take_profit_trigger(self):
        """卖单触发止盈"""
        result = self._should_close_sell(4350.0, 4380.0, 4410.0, 4350.0)
        assert result == "take_profit"

    def test_no_trigger(self):
        """价格在 SL/TP 之间不触发"""
        result = self._should_close_buy(4390.0, 4380.0, 4350.0, 4420.0)
        assert result is None

    def test_no_sl_tp(self):
        """无 SL/TP 时不触发"""
        result = self._should_close_buy(4300.0, 4380.0, 0, 0)
        assert result is None
