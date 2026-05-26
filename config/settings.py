"""
XAUUSD 量化交易系统 - 配置文件
"""

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
MAX_POSITIONS = 3           # 最大同时持仓数
MAX_DAILY_LOSS_PCT = 5.0    # 日内最大亏损百分比（触发后停止交易）
STOP_LOSS_PIPS = 50         # 默认止损点数
TAKE_PROFIT_PIPS = 100      # 默认止盈点数

# ============================================================
# 策略配置
# ============================================================
STRATEGY = "double_ma"      # 策略名称: "double_ma" | "atr_breakout"
MA_FAST = 20                # 快速均线周期
MA_SLOW = 60                # 慢速均线周期
MA_METHOD = "EMA"           # 均线类型: EMA / SMA

# ATR 突破策略参数
ATR_BREAKOUT_PERIOD = 20    # 突破周期
ATR_PERIOD = 14             # ATR 计算周期
ATR_MULTIPLIER = 2.0        # ATR 止损倍数

TIMEFRAME = "H1"            # K线周期: M1/M5/M15/H1/H4/D1

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
