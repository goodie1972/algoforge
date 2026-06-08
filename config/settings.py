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
    "M30_rsi_bb": {
        "magic": 777001,
        "timeframe": "M30",
        "double_first": False,
        "max_positions": 1,
    },
    "H1_v6_hybrid": {
        "magic": 666666,
        "timeframe": "H1",
        "double_first": False,
        "max_positions": 1,
    },
    # === 新增实盘策略 (来自 GitHub 开源回测) ===
    "sanqing_h1": {
        "magic": 777002,
        "timeframe": "H1",
        "double_first": False,
        "max_positions": 1,
    },
    "gold_auto_research": {
        "magic": 777003,
        "timeframe": "H1",
        "double_first": False,
        "max_positions": 1,
    },
    # === 后备策略 (随时可启用) ===
    # "bakome_backup": {
    #     "magic": 777004,
    #     "timeframe": "H1",
    #     "double_first": False,
    #     "max_positions": 1,
    # },
    # "xaubot_backup": {
    #     "magic": 777005,
    #     "timeframe": "H1",
    #     "double_first": False,
    #     "max_positions": 1,
    # },
}

# 全局最大持仓 = 策略数量 × 1.5 四舍五入
MAX_POSITIONS = int(len(STRATEGY_POOL) * 1.5)  # 1策略 → 1

# 向后兼容
STRATEGY = "M30_rsi_bb"
MAGIC_NUMBER = 777001       # 向后兼容，新引擎用 STRATEGY_POOL 中的 magic
# 通用指标参数（供工具脚本使用）
BB_PERIOD = 20              # 布林带周期
BB_STD = 2.0                # 布林带标准差倍数
RSI_PERIOD = 14             # RSI 计算周期
RSI_OVERSOLD = 30           # 超卖阈值
RSI_OVERBOUGHT = 70         # 超买阈值
ATR_PERIOD = 14             # ATR 计算周期
STOCH_K = 8                 # Stoch %K 周期

TIMEFRAME = "H1"           # K线周期: M1/M5/M15/M30/H1/H4/D1

# ============================================================
# 新闻过滤配置
# ============================================================
NEWS_FILTER_ENABLED = True        # 是否启用新闻过滤
NEWS_BEFORE_MINUTES = 30          # 数据发布前 N 分钟停止开新仓
NEWS_AFTER_MINUTES = 120          # 数据发布后 N 分钟恢复交易（原30→120）
NEWS_PRE_TIGHTEN_MINUTES = 120    # 事件前 N 分钟开始收紧止损
NEWS_PRE_CLOSE_MINUTES = 15       # 事件前 N 分钟强制平仓
NEWS_IMPACT_FILTER = "High"       # 影响级别: "High" | "High,Medium"
NEWS_CURRENCY_FILTER = "USD"      # 关注货币: "USD" | "USD,EUR"

# ============================================================
# 多策略协调器配置 — 策略间信号联动出场
# ============================================================
COORDINATOR_CONFIG = {
    "enabled": False,                              # 总开关
    # 功能①：跨策略联动出场（信号策略盈利时平目标策略同向单）
    "cross_exit_enabled": False,
    "signal_strategy": "H1_v6_hybrid",             # 信号源策略名
    "signal_direction": "BUY",                     # 信号方向 (BUY/SELL)
    "target_strategies": [
        "M30_rsi_bb", "sanqing_h1", "gold_auto_research",
    ],  # 被影响的策略列表
    "target_direction": "SELL",                    # 关闭的目标方向
    # 功能②：短周期反向止盈（EMA20 斜率反转时平盈利单）
    "m15_reverse_tp_enabled": False,   # M15 周期
    "m5_reverse_tp_enabled": False,    # M5 周期
}

# === 止盈冷却时间（策略盈利平仓后，N 小时内不再开同向单） ===
PROFIT_EXIT_COOLDOWN_HOURS = 2

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
