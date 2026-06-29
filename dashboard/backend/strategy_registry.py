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
        "display": "M30 RSI+BB v11",
        "backup_file": "20260620_m30_rsi_v7.py",
        "default_magic": 660706,
        "default_timeframe": "M30",
    },
    "H1_v6_hybrid": {
        "backup_name": "h1_v6_hybrid_v6",
        "file": "v6_hybrid.py",
        "display": "H1 V6 混合 v6 [已下架]",
        "backup_file": "20260615_h1_v6_hybrid_v6.py",
        "default_magic": 660607,
        "default_timeframe": "H1",
    },
    "sanqing_h1": {
        "backup_name": "sanqing_h1_v6",
        "file": "sanqing_h1.py",
        "display": "H1 三清 v6r",
        "backup_file": "20260615_sanqing_h1_v6.py",
        "default_magic": 880107,
        "default_timeframe": "H1",
    },
    "gold_auto_research": {
        "backup_name": "gold_autoresearch_h1_v5",
        "file": "gold_autoresearch_h1.py",
        "display": "H1 黄金自动研究 v6",
        "backup_file": "20260611_gold_autoresearch_h1_v5.py",
        "default_magic": 880306,
        "default_timeframe": "H1",
    },
    "mtf_resonance_h1": {
        "backup_name": "mtf_resonance_h1",
        "file": "mtf_resonance_h1.py",
        "display": "H1 MTF 共振",
        "backup_file": "20260629_mtf_resonance_h1.py",
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
        "display": "M30 Stoch T6V1 (纯震荡)",
        "backup_file": "20260619_m30_stoch_T6V1.py",
        "default_magic": 660901,
        "default_timeframe": "M30",
    },
    "stoch_trend_m30": {
        "backup_name": "m30_stoch_T6V8",
        "file": "stoch_trend_m30.py",
        "display": "Stoch 回调顺势 (旧版已下架)",
        "backup_file": "20260619_m30_stoch_T6V8.py",
        "default_magic": 660903,
        "default_timeframe": "H1",
    },
    "stoch_trend_h1": {
        "backup_name": "stoch_trend_h1_v6",
        "file": "stoch_trend_h1.py",
        "display": "Stoch 多周期回调顺势 v6 (H4→H1→M15)",
        "backup_file": "20260629_stoch_trend_h1.py",
        "default_magic": 661201,
        "default_timeframe": "H1",
    },
    "rsi_grading_m30": {
        "backup_name": "rsi_grading_m30",
        "file": "rsi_grading_m30.py",
        "display": "M30 RSI 分级评分",
        "backup_file": "20260629_rsi_grading_m30.py",
        "default_magic": 660902,
        "default_timeframe": "M30",
    },
    "mfi_bb_m30": {
        "backup_name": "mfi_bb_m30",
        "file": "m30_mfi_bb.py",
        "display": "M30 MFI+BB 双模",
        "backup_file": "20260629_mfi_bb_m30.py",
        "default_magic": 661001,
        "default_timeframe": "M30",
    },
    "m30_bb_deepreturn": {
        "backup_name": "m30_bb_deepreturn",
        "file": "m30_bb_deepreturn.py",
        "display": "M30 BB DeepReturn 超跌反弹",
        "backup_file": "20260629_m30_bb_deepreturn.py",
        "default_magic": 661101,
        "default_timeframe": "M30",
    },
    # === 网研策略（来自 TradingView/Quant 社区）===
    "momentum_pulse_pro": {
        "backup_name": "momentum_pulse_pro",
        "file": "momentum_pulse_pro.py",
        "display": "Momentum Pulse PRO (7维度评分+三层TP)",
        "backup_file": "",
        "default_magic": 661301,
        "default_timeframe": "M30",
    },
    "viprasol_sniper": {
        "backup_name": "viprasol_sniper",
        "file": "viprasol_sniper.py",
        "display": "Viprasol Sniper (7因子共识+5级RR)",
        "backup_file": "",
        "default_magic": 661401,
        "default_timeframe": "M30",
    },
    "entry_score_pro": {
        "backup_name": "entry_score_pro",
        "file": "entry_score_pro.py",
        "display": "Entry Score PRO (5因子加权评分0-100)",
        "backup_file": "",
        "default_magic": 661501,
        "default_timeframe": "M30",
    },
    "multi_confluence_quant": {
        "backup_name": "multi_confluence_quant",
        "file": "multi_confluence_quant.py",
        "display": "Multi-Confluence Quant (14因子综合评分)",
        "backup_file": "",
        "default_magic": 661601,
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
