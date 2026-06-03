"""
XAUUSD 量化交易系统 - 配置文件
"""

import importlib
import sys


def reload():
    """强制重新载入本模块（由引擎侧的 mtime 检查触发）"""
    importlib.reload(sys.modules[__name__])


# ============================================================
# MT4 连接配置 (FreeMT4 Bridge - 本地 MT4 Socket 桥接)
# EA 源码: tools/FreeMT4Bridge.mq4
# ============================================================
MT4_MODE = "freemt4"  # "freemt4" | "metaapi"

# FreeMT4 Bridge 配置 (本地 MT4 + EA 桥接)
FREEMT4_HOST = "127.0.0.1"
FREEMT4_PORT = 23232  # FreeMT4Bridge EA 监听的端口

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

# 风控 — 见文件底部 STRATEGY_POOL 后动态计算

# === 账户级硬止损（balance-based） ===
MAX_DAILY_LOSS_PCT = 12.0   # 全局已实现亏损上限，触发后所有策略停开仓

# === 浮动亏损（equity-based，单策略） ===
FLOATING_LOSS_WARN_PCT = 5.0       # 警告线，仅日志
FLOATING_LOSS_BLOCK_PCT = 10.0     # 阻断线，不能开单，浮动降低后自动恢复

# === 单策略已实现亏损 ===
PER_STRATEGY_REALIZED_LOSS_PCT = 5.0    # 单策略已实现亏损上限
PER_STRATEGY_LOSS_BLOCK_HOURS = 12      # 触发后阻断小时数

# === 快速出场检测（单策略） ===
MAX_RAPID_EXITS = 3                     # 窗口内最多出场次数
RAPID_EXIT_WINDOW_SECONDS = 300         # 检测窗口（5 分钟）
RAPID_EXIT_COOLDOWN_SECONDS = 7200      # 触发后冷却（2 小时）

# === 单策略绝对亏损冷却（与快速出场/百分比亏损并行） ===
PER_STRATEGY_REALIZED_LOSS_AMOUNT = 30.0    # 已实现亏损 ≥$30 触发 12h 冷却
MAX_CONSECUTIVE_LOSSES = 3                  # 连续亏损 N 次后触发冷却
CONSECUTIVE_LOSS_COOLDOWN_HOURS = 4         # 连续亏损冷却时长

# === 安全锁 ===
SAFETY_LOCK_TIMEOUT_MINUTES = 90        # 自动过期时间（分钟）

STOP_LOSS_PIPS = 50         # 默认止损点数
TAKE_PROFIT_PIPS = 100      # 默认止盈点数

# ============================================================
# 策略池配置 — 支持多策略同时运行
# 每个策略有独立的 magic number、时间周期、仓位
# ============================================================
STRATEGY_POOL = {
    "H4_stoch_bollinger": {
        "magic": 888888,
        "timeframe": "H4",
        "double_first": False,
        "max_positions": 1,
    },
    "H1_rsi_bollinger": {
        "magic": 777777,
        "timeframe": "H1",
        "double_first": False,
        "max_positions": 1,
    },
}

# 全局最大持仓 = 策略数量 × 1.5 四舍五入
MAX_POSITIONS = int(len(STRATEGY_POOL) * 1.5 + 0.5)  # 3策略 → 5

# 向后兼容
STRATEGY = list(STRATEGY_POOL.keys())[0] if STRATEGY_POOL else "H4_stoch_bollinger"
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

# RSI 双线交叉策略参数
RSI_FAST = 3                # 快线周期
RSI_SLOW = 13               # 慢线周期

# Stoch + 布林带策略参数
STOCH_K = 8                 # Stoch %K 周期
STOCH_SLOWING = 3           # %K 平滑参数（3 就是 K 线再做 3 期均线）
STOCH_D = 3                 # Stoch %D 平滑周期
STOCH_OVERSOLD = 30         # Stoch 超卖信号阈值（金叉需 K 低于此值）
STOCH_OVERBOUGHT = 80       # Stoch 超买信号阈值（死叉需 K 高于此值）
STOCH_EXTREME_OVERSOLD = 20  # Stoch 极端超卖区（买入保护/出场保护边界）
STOCH_EXTREME_OVERBOUGHT = 80  # Stoch 极端超买区（卖出保护/出场保护边界）

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
