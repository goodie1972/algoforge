"""
XAUUSD 量化交易系统 - 配置文件
"""

import importlib
import sys
from datetime import timezone, timedelta, datetime as _dt


# 本地显示时区：UTC+8（用户期望，与系统服务器时区一致）
LOCAL_TZ = timezone(timedelta(hours=8))


def dt_local(ts: float) -> _dt:
    """将 Unix timestamp 转换为本地显示时间（UTC+8）"""
    return _dt.fromtimestamp(ts, tz=LOCAL_TZ)


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
SAFETY_LOCK_TIMEOUT_MINUTES = 525600    # 1 年 (2026-06-19: 在没找到稳健策略前永久锁仓, 必须手动删 config/safety_lock.txt 才能解锁)

STOP_LOSS_PIPS = 50         # 默认止损点数
TAKE_PROFIT_PIPS = 100      # 默认止盈点数

# ============================================================
# 策略池配置 — 支持多策略同时运行
# 每个策略有独立的 magic number、时间周期、仓位
# ============================================================
# 纸面交易模式 — True=模拟交易（不真实发单，策略进出场逻辑原样运行）
PAPER_MODE = True
# 纸面交易配置开关（RuntimeConfig 覆盖用，settings.py 仅作为兜底 fallback）
PAPER_TRADING_ENABLED = False

STRATEGY_POOL = {
    # === 核心实盘策略 ===
    "M30_rsi_bb": {
        "magic": 660706,
        "timeframe": "M30",
        "double_first": False,
        "max_positions": 1,
    },
    "gold_auto_research": {
        "magic": 880306,
        "timeframe": "H1",
        "double_first": False,
        "max_positions": 1,
    },
    "sanqing_h1": {
        "magic": 880107,
        "timeframe": "H1",
        "double_first": False,
        "max_positions": 1,
    },
    "h1_breakout": {
        "magic": 880301,
        "timeframe": "H1",
        "double_first": False,
        "max_positions": 1,
    },
    "m30_bb_deepreturn_optimized": {
        "magic": 661102,
        "timeframe": "M30",
        "double_first": False,
        "max_positions": 5,
    },
    "mfi_bb_m30_upgraded": {
        "magic": 661003,
        "timeframe": "M30",
        "double_first": False,
        "max_positions": 1,
    },
    "rsi_grading_m30_upgraded": {
        "magic": 660904,
        "timeframe": "M30",
        "double_first": False,
        "max_positions": 1,
    },
    "sanqing_h1_upgraded": {
        "magic": 880108,
        "timeframe": "H1",
        "double_first": False,
        "max_positions": 1,
    },
    "stoch_trend_h1_optimized": {
        "magic": 661202,
        "timeframe": "H1",
        "double_first": False,
        "max_positions": 1,
    },
    # === 备选/历史策略 (disabled by default) ===
    # "stoch_trend_h1": {  # 旧版本，已被 stoch_trend_h1_optimized 替代
    #     "magic": 661201,
    #     "timeframe": "H1",
    #     "double_first": False,
    #     "max_positions": 1,
    # },
    # "rsi_grading_m30": {  # 旧版本，已被 rsi_grading_m30_upgraded 替代
    #     "magic": 660902,
    #     "timeframe": "M30",
    #     "double_first": False,
    #     "max_positions": 1,
    # },
    # "mfi_bb_m30": {  # 旧版本，已被 mfi_bb_m30_upgraded 替代
    #     "magic": 661001,
    #     "timeframe": "M30",
    #     "double_first": False,
    #     "max_positions": 1,
    # },
    # "m30_bb_deepreturn": {  # 旧版本，已被 m30_bb_deepreturn_optimized 替代
    #     "magic": 661101,
    #     "timeframe": "M30",
    #     "double_first": False,
    #     "max_positions": 1,
    # },
    # "sanqing_original": {  # 原版 sanqing，已被 sanqing_h1_upgraded 替代
    #     "magic": 880201,
    #     "timeframe": "M5",
    #     "double_first": False,
    #     "max_positions": 5,
    # },
    "timeprofit_ea": {
        "magic": 880202,
        "timeframe": "M5",
        "double_first": False,
        "max_positions": 5,
    },
    # === 其他可选策略 ===
    # "entry_score_pro": { "magic": 661501, "timeframe": "M30", "double_first": False, "max_positions": 1 },
    # "mfi_bb_m30_optimized": { "magic": 661002, "timeframe": "M30", "double_first": False, "max_positions": 1 },
    # "m30_vol_return": { "magic": 880302, "timeframe": "M30", "double_first": False, "max_positions": 1 },
    # "momentum_pulse_pro": { "magic": 661301, "timeframe": "M30", "double_first": False, "max_positions": 1 },
    # "multi_confluence_quant": { "magic": 661601, "timeframe": "M30", "double_first": False, "max_positions": 1 },
    # "viprasol_sniper": { "magic": 661401, "timeframe": "M30", "double_first": False, "max_positions": 1 },
    # "bakome_gold_scalper_original": { "magic": 880303, "timeframe": "M5", "double_first": False, "max_positions": 1 },
    # "bakome_trinity_ea_original": { "magic": 880304, "timeframe": "M5", "double_first": False, "max_positions": 1 },
    # "xaubot_backup": { "magic": 777005, "timeframe": "H1", "double_first": False, "max_positions": 1 },
    # "bakome_backup": { "magic": 777004, "timeframe": "H1", "double_first": False, "max_positions": 1 },
    # "bakome_backup_optimized": { "magic": 777006, "timeframe": "H1", "double_first": False, "max_positions": 1 },
    # "stoch_trend_h1_upgraded": { "magic": 661204, "timeframe": "H1", "double_first": False, "max_positions": 1 },
}

# 全局最大持仓 = 策略数量 × 1.5 四舍五入
MAX_POSITIONS = int(len(STRATEGY_POOL) * 1.5)  # 1策略 → 1

# 向后兼容
STRATEGY = "M30_rsi_bb"
MAGIC_NUMBER = 660706       # 向后兼容，新引擎用 STRATEGY_POOL 中的 magic
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

# News-Bias 事后评估（观察模式，不影响交易）
NEWS_BIAS_ENABLED = True          # 是否执行评估
NEWS_BIAS_REPORT_HOURS = "8,20"   # 生成报告的小时(北京时间)，逗号分隔，默认8点和20点

# News-Bias 阻塞控制（影响开仓）
BLOCK_LONG_WHEN_BIAS_BEARISH = False   # 新闻预判为看跌时，阻止所有策略开多（已关闭）
BLOCK_SHORT_WHEN_BIAS_BULLISH = False  # 新闻预判为看涨时，阻止所有策略开空（已关闭）
NEWS_BIAS_BLOCK_REFRESH_SECONDS = 60    # 引擎刷新最新 bias 方向的间隔

# News-Bias ADX 门禁：H1 ADX ≤ 此值时视为震荡市，绕过 news-bias 阻塞
NEWS_BIAS_ADX_GATE = 25


# ============================================================
# 多策略协调器配置 — 策略间信号联动出场
# ============================================================
COORDINATOR_CONFIG = {
    "enabled": False,                              # 总开关
    # 功能①：跨策略联动出场（信号策略盈利时平目标策略同向单）
    "cross_exit_enabled": False,
    "signal_strategy": None,                         # v6_hybrid 已下架，禁用跨策略联动信号源
    "signal_direction": "BUY",                     # 信号方向 (BUY/SELL)
    "target_strategies": [
        "M30_rsi_bb", "sanqing_h1", "gold_auto_research",
    ],  # 被影响的策略列表
    "target_direction": "SELL",                    # 关闭的目标方向
    # 功能②：短周期反向止盈（M15 EMA20 斜率归一化反转时平盈利单）
    "m15_reverse_tp_enabled": False,   # M15 周期（M5 过于敏感已移除）
    # 斜率归一化阈值：斜率/ATR 超过此值才算真反转
    # 0.0 = 关闭归一化（原版逻辑，斜率>0即触发）
    # 0.1~1.0 = 数值越大越不敏感，推荐 0.5（触发率约25%）
    "m15_reverse_tp_sensitivity": 0.5,
    # 功能③：MTF 共振方向门禁（H1+M15 TA-Lib 形态共振时限制开仓方向）
    "mtf_resonance_enabled": True,  # H1+M15 共振方向门禁
    # 功能④：K线过滤器 — 每个过滤器独立开关，统一由 BaseStrategy 施加
    # ① 位置门禁：M30 N根K线区间底部 threshold 禁空、顶部 threshold 禁多
    "position_gate_enabled": True,
    "position_gate_lookback": 60,
    "position_gate_m30_lookback": 40,
    "position_gate_bottom": 0.10,
    "position_gate_top": 0.90,
    # ② 急跌急涨惩罚：M30周期内从高/低点起算超过 threshold % 禁追
    "rally_drop_enabled": True,
    "rally_drop_lookback": 30,
    "rally_drop_threshold": 1.5,
    # ③ 利润回撤止盈：浮动盈利从峰值回撤 N% 即止盈（引擎出场逻辑）
    "profit_drawdown_enabled": True,
    "profit_drawdown_pct": 0.25,
    # ADX 跳过（位置门禁：|+DI - -DI| > 阈值时跳过）
    "di_gate_skip_threshold": 20,
    # ADX 跳过（急跌急涨：M30 ADX > 阈值时跳过）
    "rally_drop_adx_skip": 25,
    # ④ News-Bias DI 差值门禁：M30 |+DI - -DI| < 此值时绕过新闻阻塞（0=关闭）
    "news_bias_di_gap": 8,
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
