"""
config_schema 单元测试 — 验证 pydantic 校验逻辑
"""
import pytest
from config.config_schema import (
    StrategyPoolEntry,
    RuntimeConfigSchema,
    validate_config,
)


def test_valid_strategy_pool_entry():
    """合法策略配置"""
    entry = StrategyPoolEntry(name="gold_auto_research", enabled=True, max_positions=1, magic=880306, timeframe="H1")
    assert entry.enabled is True
    assert entry.max_positions == 1


def test_negative_max_positions_rejected():
    """max_positions 不能为负"""
    with pytest.raises(Exception):
        StrategyPoolEntry(name="test", max_positions=-1, magic=100)


def test_negative_magic_rejected():
    """magic 不能为负"""
    with pytest.raises(Exception):
        StrategyPoolEntry(name="test", magic=-1)


def test_validate_config_valid():
    """完整合法配置"""
    config = {
        "strategy_pool": {
            "gold_auto_research": {
                "enabled": True,
                "max_positions": 1,
                "magic": 880306,
                "timeframe": "H1",
            },
        },
        "max_positions": 7,
        "paper_trading": {"enabled": True},
    }
    is_valid, errors = validate_config(config)
    assert is_valid is True
    assert len(errors) == 0


def test_validate_config_invalid_max_positions():
    """全局 max_positions < 1"""
    config = {
        "strategy_pool": {},
        "max_positions": 0,
    }
    is_valid, errors = validate_config(config)
    assert is_valid is False
    assert any("max_positions" in e for e in errors)


def test_validate_config_invalid_strategy():
    """策略 max_positions 为负"""
    config = {
        "strategy_pool": {
            "bad_strategy": {
                "max_positions": -5,
                "magic": 100,
            },
        },
        "max_positions": 7,
    }
    is_valid, errors = validate_config(config)
    assert is_valid is False
    assert len(errors) > 0


def test_validate_config_missing_strategy_pool():
    """缺少 strategy_pool"""
    config = {"max_positions": 7}
    is_valid, errors = validate_config(config)
    # strategy_pool 默认为空 dict，应该通过
    assert is_valid is True


def test_validate_config_paper_trading_not_dict():
    """paper_trading 不是 dict"""
    config = {
        "max_positions": 7,
        "paper_trading": "not_a_dict",
    }
    is_valid, errors = validate_config(config)
    assert is_valid is False
    assert any("paper_trading" in e for e in errors)
