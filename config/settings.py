"""
XAUUSD 量化交易系统 - 配置文件
"""

import importlib
import sys


def reload():
    """强制重新载入本模块（由引擎侧的 mtime 检查触发）"""
    importlib.reload(sys.modules[__name__])


# ============================================================
# MT4 连接配置 (PyTrader 方式 - 本地 MT4 桥接)
# ============================================================
MT4_MODE = "pytrader"  # "pytrader" | "metaapi"

# PyTrader 配置 (本地 MT4 + EA 桥接)
PYTRADER_HOST = "127.0.0.1"
PYTRADER_PORT = 23232  # PyTrader EA 监听的端口

# MetaApi 配置 (云服务方式，如选用)
METAAPI_TOKEN = ""  # metaapi.cloud 的 API token
METAAPI_ACCOUNT_ID = ""  # MetaApi 中的账户 ID

# ============================================================
# 交易配置
# ============================================================
SYMBOL = "XAUUSD"           # 交易品种
LOT_SIZE = 0.01             # 每次开仓手数（从最小开始）
MAGIC_NUMBER = 888888       # EA 魔术号，用于标识本程序的订单
SLIPPAGE = 30               # 最大滑点（points）

# 风控
MAX_POSITIONS = 2           # 最大同时持仓数（双倍首单，每次开2张）
MAX_DAILY_LOSS_PCT = 5.0    # 日内最大亏损百分比（触发后停止交易）
STOP_LOSS_PIPS = 50         # 默认止损点数
TAKE_PROFIT_PIPS = 100      # 默认止盈点数

# ============================================================
# 策略池配置 — 支持多策略同时运行
# 每个策略有独立的 magic number、时间周期、仓位
# ============================================================
STRATEGY_POOL = {
    "stoch_bollinger": {
        "magic": 888888,
        "timeframe": "H4",
        "double_first": True,
        "max_positions": 2,
    },
    "rsi_bollinger": {
        "magic": 777777,
        "timeframe": "H1",
        "double_first": True,
        "max_positions": 2,
    },
}

# 向后兼容
STRATEGY = list(STRATEGY_POOL.keys())[0] if STRATEGY_POOL else "stoch_bollinger"
MAGIC_NUMBER = 888888       # 向后兼容，新引擎用 STRATEGY_POOL 中的 magic
MA_FAST = 20                # 快速均线周期
MA_SLOW = 60                # 慢速均线周期
MA_METHOD = "EMA"           # 均线类型: EMA / SMA

# ATR 突破策略参数
ATR_BREAKOUT_PERIOD = 20    # 突破周期
ATR_PERIOD = 14             # ATR 计算周期
ATR_MULTIPLIER = 2.0        # ATR 止损倍数

# RSI + 布林带策略参数
BB_PERIOD = 20              # 布林带周期
BB_STD = 2.0                # 布林带标准差倍数
RSI_PERIOD = 14             # RSI 计算周期
RSI_OVERSOLD = 30           # 超卖阈值
RSI_OVERBOUGHT = 70         # 超买阈值

# Stoch + 布林带策略参数
STOCH_K = 8                 # Stoch %K 周期
STOCH_SLOWING = 3           # %K 平滑参数（3 就是 K 线再做 3 期均线）
STOCH_D = 3                 # Stoch %D 平滑周期
STOCH_OVERSOLD = 20         # Stoch 超卖阈值
STOCH_OVERBOUGHT = 80       # Stoch 超买阈值

TIMEFRAME = "H4"           # K线周期: M1/M5/M15/M30/H1/H4/D1

# ============================================================
# 新闻过滤配置
# ============================================================
NEWS_FILTER_ENABLED = True        # 是否启用新闻过滤
NEWS_BEFORE_MINUTES = 30          # 数据发布前 N 分钟停止开新仓
NEWS_AFTER_MINUTES = 30           # 数据发布后 N 分钟恢复交易
NEWS_IMPACT_FILTER = "High"       # 影响级别: "High" | "High,Medium"
NEWS_CURRENCY_FILTER = "USD"      # 关注货币: "USD" | "USD,EUR"

# ============================================================
# 回测配置
# ============================================================
BACKTEST_START_DATE = "2024-01-01"
BACKTEST_END_DATE = "2025-01-01"
BACKTEST_INITIAL_CASH = 10000.0

# ============================================================
# 日志配置
# ============================================================
LOG_DIR = "logs"
LOG_LEVEL = "INFO"
