"""
共享技术指标计算模块
====================
与 DataFactory 口径一致：优先 TA-Lib，回退纯 numpy 实现。
所有回测和纸面测试脚本应引用此模块，避免指标函数重复实现。
"""
from .common import (
    calc_ema, calc_ema_series,
    calc_sma, calc_sma_series,
    calc_rsi, calc_rsi_series,
    calc_atr, calc_atr_series,
    calc_bb, calc_bb_series,
    calc_macd, calc_macd_series,
    calc_stoch, calc_stoch_series,
    calc_adx, calc_adx_series,
    calc_mfi, calc_mfi_series,
    calc_keltner, calc_keltner_series,
    calc_wildersmooth,
)

__all__ = [
    "calc_ema", "calc_ema_series",
    "calc_sma", "calc_sma_series",
    "calc_rsi", "calc_rsi_series",
    "calc_atr", "calc_atr_series",
    "calc_bb", "calc_bb_series",
    "calc_macd", "calc_macd_series",
    "calc_stoch", "calc_stoch_series",
    "calc_adx", "calc_adx_series",
    "calc_mfi", "calc_mfi_series",
    "calc_keltner", "calc_keltner_series",
    "calc_wildersmooth",
]
