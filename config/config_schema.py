"""
runtime_config.json Schema 校验 — 使用 pydantic 模型防止配置错误
"""
from pydantic import BaseModel, field_validator, ConfigDict
from typing import Optional


class StrategyPoolEntry(BaseModel):
    """单个策略配置"""
    model_config = ConfigDict(extra='allow')  # 允许额外字段（兼容未来扩展）

    name: str
    enabled: bool = False
    max_positions: int = 1
    magic: int = 0
    timeframe: str = "H1"
    double_first: bool = False

    @field_validator('max_positions')
    @classmethod
    def max_pos_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"max_positions must be >= 0, got {v}")
        return v

    @field_validator('magic')
    @classmethod
    def magic_positive(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"magic must be >= 0, got {v}")
        return v


class RuntimeConfigSchema(BaseModel):
    """runtime_config.json 顶层结构"""
    model_config = ConfigDict(extra='allow')

    strategy_pool: dict[str, StrategyPoolEntry] = {}
    max_positions: int = 7
    paper_trading: Optional[dict] = None

    @field_validator('max_positions')
    @classmethod
    def global_max_pos_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"global max_positions must be >= 1, got {v}")
        return v


def validate_config(config: dict) -> tuple[bool, list[str]]:
    """校验 runtime_config.json 配置

    Returns:
        (is_valid, errors)
    """
    errors: list[str] = []

    # 校验 strategy_pool
    pool = config.get("strategy_pool", {})
    if not isinstance(pool, dict):
        errors.append("strategy_pool must be a dict")
    else:
        for name, cfg in pool.items():
            try:
                if not isinstance(cfg, dict):
                    errors.append(f"strategy_pool.{name} must be a dict")
                    continue
                entry_data = {"name": name, **cfg}
                StrategyPoolEntry(**entry_data)
            except Exception as e:
                errors.append(f"strategy_pool.{name}: {e}")

    # 校验 max_positions
    mp = config.get("max_positions")
    if mp is not None and (not isinstance(mp, int) or mp < 1):
        errors.append(f"max_positions must be >= 1, got {mp}")

    # 校验 paper_trading
    pt = config.get("paper_trading")
    if pt is not None and not isinstance(pt, dict):
        errors.append("paper_trading must be a dict")

    return (len(errors) == 0, errors)
