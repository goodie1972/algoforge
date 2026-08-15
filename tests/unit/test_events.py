"""
events.py 单元测试 — 验证日志格式化函数
"""
import pytest
from engine_standalone.events import (
    format_status_report,
    format_trade_close_log,
    format_entry_log,
    format_risk_block_log,
)


class TestFormatStatusReport:
    def test_running_status(self):
        report = format_status_report(
            running=True, uptime=100.5, bridge_connected=True,
            strategy_count=9, position_count=2, balance=5000.0,
            equity=5010.0, floating_pnl=10.0, daily_pnl=5.0,
        )
        assert report["status"] == "running"
        assert report["uptime_seconds"] == 100.5
        assert report["bridge_connected"] is True
        assert report["strategy_count"] == 9

    def test_stopped_status(self):
        report = format_status_report(
            running=False, uptime=0, bridge_connected=False,
            strategy_count=0, position_count=0, balance=0,
            equity=0, floating_pnl=0, daily_pnl=0,
        )
        assert report["status"] == "stopped"
        assert report["bridge_connected"] is False

    def test_paper_mode(self):
        report = format_status_report(
            running=True, uptime=10, bridge_connected=True,
            strategy_count=5, position_count=1, balance=5000,
            equity=5005, floating_pnl=5, daily_pnl=5,
            paper_mode=True,
        )
        assert report["paper_mode"] is True


class TestFormatTradeCloseLog:
    def test_win(self):
        log = format_trade_close_log(10001, "gold", "BUY", 10.5, 3600, "take_profit")
        assert "gold" in log
        assert "BUY" in log
        assert "+$10.50" in log
        assert "60m0s" in log
        assert "take_profit" in log

    def test_loss(self):
        log = format_trade_close_log(10002, "test", "SELL", -5.0, 120, "stop_loss")
        assert "$-5.00" in log
        assert "2m0s" in log

    def test_zero_hold(self):
        log = format_trade_close_log(10003, "test", "BUY", 0, 0, "")
        assert "0s" in log


class TestFormatEntryLog:
    def test_basic(self):
        log = format_entry_log("gold_auto_research", "BUY", 4389.0, 0.01, 880306, score=5)
        assert "gold_auto_research" in log
        assert "BUY" in log
        assert "4389.00" in log
        assert "880306" in log
        assert "score=5" in log


class TestFormatRiskBlockLog:
    def test_rapid_exit(self):
        log = format_risk_block_log("gold", "快速出场", "5次/5min", "30min")
        assert "gold" in log
        assert "快速出场" in log
        assert "5次/5min" in log
        assert "30min" in log
