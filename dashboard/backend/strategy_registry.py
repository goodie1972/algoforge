"""
策略注册表 — 将内部策略名映射到 backup 命名规范
所有新发现策略只需在此注册即可自动出现在策略中心
"""

# 内部名 → 注册信息
# backup_name: 策略展示名 (以 backup/ 目录中最新文件名为准)
# file: 实际代码文件名
# default_magic: 默认魔术号
# default_timeframe: 默认周期
STRATEGY_REGISTRY = {
    "M30_rsi_bb": {
        "backup_name": "m30_rsi_v7",
        "file": "m30_rsi.py",
        "display": "M30 RSI+BB v7",
        "backup_file": "20260620_m30_rsi_v7.py",
        "default_magic": 660706,
        "default_timeframe": "M30",
    },
    "H1_v6_hybrid": {
        "backup_name": "h1_v6_hybrid_v6",
        "file": "v6_hybrid.py",
        "display": "H1 V6 混合 v6",
        "backup_file": "20260615_h1_v6_hybrid_v6.py",
        "default_magic": 660607,
        "default_timeframe": "H1",
    },
    "sanqing_h1": {
        "backup_name": "sanqing_h1_v6",
        "file": "sanqing_h1.py",
        "display": "H1 三清 v6",
        "backup_file": "20260615_sanqing_h1_v6.py",
        "default_magic": 880107,
        "default_timeframe": "H1",
    },
    "gold_auto_research": {
        "backup_name": "gold_autoresearch_h1_v5",
        "file": "gold_autoresearch_h1.py",
        "display": "H1 黄金自动研究 v5",
        "backup_file": "20260611_gold_autoresearch_h1_v5.py",
        "default_magic": 880306,
        "default_timeframe": "H1",
    },
    "mtf_resonance_h1": {
        "backup_name": "mtf_resonance_h1",
        "file": "mtf_resonance_h1.py",
        "display": "H1 MTF 共振",
        "backup_file": "",
        "default_magic": 660801,
        "default_timeframe": "H1",
    },
    "bakome_backup": {
        "backup_name": "H1_bakome_backup",
        "file": "bakome_backup.py",
        "display": "H1 Bakome 备用",
        "backup_file": "20260607_H1_bakome_backup.py",
        "default_magic": 777004,
        "default_timeframe": "H1",
    },
    "xaubot_backup": {
        "backup_name": "H1_xaubot_backup",
        "file": "xaubot_backup.py",
        "display": "H1 XAUBot 备用",
        "backup_file": "20260607_H1_xaubot_backup.py",
        "default_magic": 777005,
        "default_timeframe": "H1",
    },
    "stoch_m30": {
        "backup_name": "m30_stoch_T6V1",
        "file": "stoch_m30.py",
        "display": "M30 Stoch T0 (纯震荡)",
        "backup_file": "20260619_m30_stoch_T6V1.py",
        "default_magic": 660901,
        "default_timeframe": "M30",
    },
    "stoch_trend_m30": {
        "backup_name": "m30_stoch_T6V8",
        "file": "stoch_trend_m30.py",
        "display": "M30 Stoch T6V8 (趋势叠加)",
        "backup_file": "20260619_m30_stoch_T6V8.py",
        "default_magic": 660903,
        "default_timeframe": "M30",
    },
    "rsi_grading_m30": {
        "backup_name": "rsi_grading_m30",
        "file": "rsi_grading_m30.py",
        "display": "M30 RSI 分级评分",
        "backup_file": "",
        "default_magic": 660902,
        "default_timeframe": "M30",
    },
}


def get_available_strategies():
    """返回所有可用策略列表（含内外部名映射）"""
    result = []
    for internal_name, info in STRATEGY_REGISTRY.items():
        result.append({
            "id": internal_name,
            "name": info["backup_name"],
            "display": info["display"],
            "file": info["file"],
            "backup_file": info["backup_file"] or None,
            "default_magic": info["default_magic"],
            "default_timeframe": info["default_timeframe"],
        })
    return result


def get_strategy_info(internal_name: str) -> dict | None:
    """根据内部名获取注册信息"""
    return STRATEGY_REGISTRY.get(internal_name)
