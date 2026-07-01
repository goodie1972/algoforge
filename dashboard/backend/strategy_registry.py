"""
策略注册表 — 自动从 strategies/ 目录扫描发现
新策略只需放到 strategies/ 目录就会自动出现
"""

from strategies.scanner import scan_strategy_metadata


def get_available_strategies():
    """返回所有可用策略列表"""
    metas = scan_strategy_metadata()
    return [
        {
            "id": internal_name,
            "name": meta["name"],
            "display": meta["display"],
            "file": meta["file"],
            "backup_file": None,
            "default_magic": meta["default_magic"],
            "default_timeframe": meta["default_timeframe"],
        }
        for internal_name, meta in metas.items()
    ]


def get_strategy_info(internal_name: str) -> dict | None:
    """根据内部名获取注册信息"""
    return scan_strategy_metadata().get(internal_name)
