"""
实盘交易主循环 — 多策略并行引擎
支持 STRATEGY_POOL 中多个策略同时运行，各自独立 magic/timeframe
"""

import json
import logging
import time
import sys
import os
import importlib
import threading
from datetime import datetime
from dataclasses import dataclass, field
from collections import deque
from typing import Optional

# 当从 engine_standalone/ 运行时，将项目根加入 sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from config import settings
from core.bridge import create_bridge, OrderType
from services.news_filter import NewsFilter
from data.downloader import download_timeframe
from data import database as db
from strategies.m30_rsi import M30RSIStrategy
from strategies.v6_hybrid import V6HybridStrategy
from strategies.sanqing_h1 import SanQingH1Strategy
from strategies.gold_autoresearch_h1 import GoldAutoResearchStrategy
from strategies.bakome_backup import BAKOMEBackupStrategy
from strategies.xaubot_backup import XAUBotBackupStrategy

STRATEGY_MAP = {
    "M30_rsi_bb": M30RSIStrategy,
    "H1_v6_hybrid": V6HybridStrategy,
    "sanqing_h1": SanQingH1Strategy,
    "gold_auto_research": GoldAutoResearchStrategy,
    "bakome_backup": BAKOMEBackupStrategy,
    "xaubot_backup": XAUBotBackupStrategy,
}

# 日志配置
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(f"{settings.LOG_DIR}/trading_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

SAFETY_LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "safety_lock.txt")
MIN_HOLD_SECONDS = 30  # 持仓小于此时间被平仓视为可疑


@dataclass
class StrategyRiskState:
    """单策略风控状态"""
    name: str
    magic: int
    realized_pnl: float = 0.0                     # 累计已实现盈亏
    floating_pnl: float = 0.0                     # 当前浮动盈亏
    exit_timestamps: deque = field(default_factory=deque)  # 快速出场检测窗口
    realized_loss_blocked: bool = False            # 已实现亏损阻断（百分比）
    floating_loss_blocked: bool = False            # 浮动亏损阻断
    rapid_exit_blocked: bool = False               # 快速出场阻断
    realized_loss_amount_blocked: bool = False     # 已实现亏损 ≥$30 阻断
    realized_loss_amount_blocked_at: float = 0.0
    consecutive_losses: int = 0                    # 连续亏损次数
    consecutive_loss_blocked: bool = False         # 连续亏损阻断
    consecutive_loss_blocked_at: float = 0.0
    realized_loss_blocked_at: float = 0.0          # 阻断时间戳
    rapid_exit_blocked_at: float = 0.0


def create_strategies(bridge):
    """从 STRATEGY_POOL 创建策略实例列表"""
    strategies = []
    for name, cfg in settings.STRATEGY_POOL.items():
        cls = STRATEGY_MAP.get(name)
        if cls is None:
            logger.warning(f"未知策略: {name}，跳过")
            continue
        strategy = cls(bridge, magic=cfg["magic"], timeframe=cfg["timeframe"])
        # 附加策略专属配置
        strategy.magic = cfg["magic"]
        strategy.double_first = cfg.get("double_first", False)
        strategy.max_positions = cfg.get("max_positions", 1)
        strategies.append(strategy)
        logger.info(f"[策略加载] {name} Magic={strategy.magic} TF={strategy.timeframe}")
    return strategies


class TradingEngine:
    """多策略交易引擎"""

    def __init__(self):
        self.bridge = create_bridge()
        self.strategies = create_strategies(self.bridge)
        self._strategies_lock = threading.Lock()
        self.news_filter = NewsFilter()
        self.running = False
        self._last_balance_check = 0
        self._daily_start_balance = 0.0
        self._global_loss_blocked = False
        self._last_report_time = 0
        self._report_interval = 4 * 3600
        self._config_mtime = 0.0
        self._last_news_check = 0.0
        self._last_data_sync = 0.0
        self._data_sync_interval = 300  # 每300秒（5分钟）同步一次数据
        self._entry_times: dict[int, float] = {}           # ticket → 开仓时间戳
        self._risk_states: dict[int, StrategyRiskState] = {}  # magic → 风控状态
        self._known_position_count: dict[int, int] = {}    # magic → 本地跟踪持仓数（防桥接漏查）
        self._closed_trades: list[dict] = []               # 已平仓记录（内存）
        self._trades_file = os.path.join(settings.LOG_DIR, "closed_trades.jsonl")
        self._profit_exit_cooldown: dict[int, dict[str, float]] = {}  # magic → {方向 → 盈利平仓时间}
        self._load_closed_trades()

    @property
    def closed_trades(self) -> list[dict]:
        return list(self._closed_trades)

    def _load_closed_trades(self):
        """启动时从 JSONL 加载历史已平仓记录"""
        try:
            if os.path.exists(self._trades_file) and os.path.getsize(self._trades_file) > 0:
                with open(self._trades_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                self._closed_trades.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
                logger.info(f"加载历史成交 {len(self._closed_trades)} 条")
        except Exception as e:
            logger.warning(f"加载历史成交失败: {e}")

    def add_strategy(self, name: str, cfg: dict) -> bool:
        """动态添加策略（运行中），返回是否成功"""
        with self._strategies_lock:
            if any(s.name == name for s in self.strategies):
                logger.warning(f"[策略动态添加] {name} 已存在，跳过")
                return False
            magic = cfg["magic"]
            if any(s.magic == magic for s in self.strategies):
                logger.warning(f"[策略动态添加] Magic {magic} 已被占用，跳过")
                return False
            cls = STRATEGY_MAP.get(name)
            if cls is None:
                logger.warning(f"[策略动态添加] 未知策略: {name}")
                return False
            strategy = cls(self.bridge, magic=magic, timeframe=cfg.get("timeframe", "H1"))
            strategy.magic = magic
            strategy.double_first = cfg.get("double_first", False)
            strategy.max_positions = cfg.get("max_positions", 1)
            self.strategies.append(strategy)
            self._init_risk_state(name, magic)
            existing = self.bridge.takeover_existing_positions(settings.SYMBOL, magic)
            for pos in existing:
                self._entry_times[pos.ticket] = time.time()
            logger.info(f"[策略动态添加] {name} Magic={magic} TF={cfg.get('timeframe','H1')}")
            return True

    def remove_strategy(self, name: str, close_positions: bool = True) -> bool:
        """动态移除策略（运行中），返回是否成功"""
        with self._strategies_lock:
            strategy = next((s for s in self.strategies if s.name == name), None)
            if strategy is None:
                logger.warning(f"[策略动态移除] {name} 不存在")
                return False
            if close_positions:
                positions = self.bridge.get_positions(settings.SYMBOL)
                for pos in positions:
                    if pos.magic == strategy.magic:
                        self.bridge.close_order(pos.ticket)
                        self._entry_times.pop(pos.ticket, None)
            self.strategies = [s for s in self.strategies if s.name != name]
            self._risk_states.pop(strategy.magic, None)
            logger.info(f"[策略动态移除] {name} Magic={strategy.magic}")
            return True

    def _init_risk_state(self, name: str, magic: int):
        """初始化单策略风控状态"""
        if magic not in self._risk_states:
            self._risk_states[magic] = StrategyRiskState(name=name, magic=magic)

    def _update_floating_pnl(self):
        """更新所有策略的浮动盈亏"""
        all_positions = self.bridge.get_positions(settings.SYMBOL)
        for state in self._risk_states.values():
            my_pos = [p for p in all_positions if p.magic == state.magic]
            state.floating_pnl = sum(p.profit for p in my_pos)

    def _record_close(self, ticket: int, pnl: float, magic: int, direction: str = ""):
        """记录平仓：更新已实现盈亏 + 快速出场检测"""
        state = self._risk_states.get(magic)
        if state is None:
            return

        # 累计已实现盈亏
        state.realized_pnl += pnl

        # 清除 entry_time
        self._entry_times.pop(ticket, None)
        # 本地持仓计数器递减（防桥接漏查导致 max_positions 失效）
        self._known_position_count[magic] = max(0, self._known_position_count.get(magic, 0) - 1)

        # 快速出场检测
        now = time.time()
        state.exit_timestamps.append(now)
        # 清除窗口外的旧时间戳
        while state.exit_timestamps and state.exit_timestamps[0] < now - settings.RAPID_EXIT_WINDOW_SECONDS:
            state.exit_timestamps.popleft()

        if len(state.exit_timestamps) >= settings.MAX_RAPID_EXITS:
            state.rapid_exit_blocked = True
            state.rapid_exit_blocked_at = now
            logger.error(
                f"[{state.name}] 快速出场阻断: {settings.RAPID_EXIT_WINDOW_SECONDS//60}min 内 "
                f"{len(state.exit_timestamps)} 次平仓（上限 {settings.MAX_RAPID_EXITS}），"
                f"冷却 {settings.RAPID_EXIT_COOLDOWN_SECONDS//60}min"
            )

        # 连续亏损跟踪
        if pnl < 0:
            state.consecutive_losses += 1
            logger.info(
                f"[{state.name}] 连续亏损 {state.consecutive_losses} 次 "
                f"（上限 {settings.MAX_CONSECUTIVE_LOSSES}）"
            )
            if state.consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES and not state.consecutive_loss_blocked:
                state.consecutive_loss_blocked = True
                state.consecutive_loss_blocked_at = now
                logger.error(
                    f"[{state.name}] 连续亏损 {state.consecutive_losses} 次，"
                    f"冷却 {settings.CONSECUTIVE_LOSS_COOLDOWN_HOURS}h"
                )
        elif pnl > 0:
            state.consecutive_losses = 0
            # 盈利平仓 → 记录冷却时间
            if direction:
                if magic not in self._profit_exit_cooldown:
                    self._profit_exit_cooldown[magic] = {}
                self._profit_exit_cooldown[magic][direction] = time.time()
                logger.info(
                    f"[止盈冷却] {state.name} {direction} 盈利 ${pnl:.2f}，"
                    f"{settings.PROFIT_EXIT_COOLDOWN_HOURS}h 内不再开同向单"
                )

        # 绝对亏损阻断：已实现亏损 ≥$30 触发 12h 冷却
        if state.realized_pnl <= -settings.PER_STRATEGY_REALIZED_LOSS_AMOUNT and not state.realized_loss_amount_blocked:
            state.realized_loss_amount_blocked = True
            state.realized_loss_amount_blocked_at = now
            logger.error(
                f"[{state.name}] 已实现亏损 ${abs(state.realized_pnl):.2f} "
                f"（≥${settings.PER_STRATEGY_REALIZED_LOSS_AMOUNT}），"
                f"冷却 {settings.PER_STRATEGY_LOSS_BLOCK_HOURS}h"
            )
        # 亏损回正自动解除
        if state.realized_pnl > 0 and state.realized_loss_amount_blocked:
            state.realized_loss_amount_blocked = False
            logger.info(f"[{state.name}] 已实现亏损回正，解除绝对亏损冷却")

        # 已实现亏损阻断检查（百分比）
        balance = self._get_balance()
        if balance > 0:
            loss_pct = abs(state.realized_pnl) / balance * 100
            threshold = settings.PER_STRATEGY_REALIZED_LOSS_PCT
            if state.realized_pnl < 0 and loss_pct >= threshold and not state.realized_loss_blocked:
                state.realized_loss_blocked = True
                state.realized_loss_blocked_at = now
                logger.error(
                    f"[{state.name}] 已实现亏损 {loss_pct:.2f}%（≥{threshold}%），"
                    f"该策略暂停开仓 {settings.PER_STRATEGY_LOSS_BLOCK_HOURS}h"
                )

    def _check_global_loss(self) -> bool:
        """账户级硬止损：balance-based，12% 触发全局停开仓"""
        now = time.time()
        if now - self._last_balance_check < 300:
            return self._global_loss_blocked
        self._last_balance_check = now

        balance = self._get_balance()
        if balance <= 0:
            self._global_loss_blocked = True
            return True

        loss_pct = (self._daily_start_balance - balance) / self._daily_start_balance * 100 if self._daily_start_balance else 0
        if loss_pct >= settings.MAX_DAILY_LOSS_PCT:
            if not self._global_loss_blocked:
                logger.error(
                    f"[全局硬止损] 已实现亏损 {loss_pct:.2f}% "
                    f"（上限 {settings.MAX_DAILY_LOSS_PCT}%），全策略停开仓"
                )
            self._global_loss_blocked = True
            return True

        if self._global_loss_blocked:
            logger.info(f"[全局硬止损] 已实现亏损恢复至 {loss_pct:.2f}%，恢复开仓")
        self._global_loss_blocked = False
        return False

    def _is_strategy_blocked(self, magic: int) -> Optional[str]:
        """检查策略是否被阻断，返回阻断原因或 None"""
        state = self._risk_states.get(magic)
        if state is None:
            return None

        now = time.time()

        # 已实现亏损阻断 — 12h 自动解
        if state.realized_loss_blocked:
            elapsed = now - state.realized_loss_blocked_at
            if elapsed >= settings.PER_STRATEGY_LOSS_BLOCK_HOURS * 3600:
                state.realized_loss_blocked = False
                logger.info(
                    f"[{state.name}] 已实现亏损阻断到期（{elapsed/3600:.1f}h），恢复开仓"
                )
            else:
                remain_h = (settings.PER_STRATEGY_LOSS_BLOCK_HOURS * 3600 - elapsed) / 3600
                return f"已实现亏损阻断，剩余 {remain_h:.1f}h"

        # 浮动亏损阻断 — 降到 10% 以下自动恢复
        if state.floating_loss_blocked:
            balance = self._get_balance()
            if balance > 0:
                floating_pct = abs(state.floating_pnl) / balance * 100
                if floating_pct < settings.FLOATING_LOSS_BLOCK_PCT:
                    state.floating_loss_blocked = False
                    logger.info(
                        f"[{state.name}] 浮动亏损已降至 {floating_pct:.2f}%，恢复开仓"
                    )
                else:
                    return f"浮动亏损阻断（{floating_pct:.2f}%）"

        # 绝对亏损阻断 — 12h 自动解
        if state.realized_loss_amount_blocked:
            elapsed = now - state.realized_loss_amount_blocked_at
            if elapsed >= settings.PER_STRATEGY_LOSS_BLOCK_HOURS * 3600:
                state.realized_loss_amount_blocked = False
                logger.info(
                    f"[{state.name}] 绝对亏损冷却到期（{elapsed/3600:.1f}h），恢复开仓"
                )
            else:
                remain_h = (settings.PER_STRATEGY_LOSS_BLOCK_HOURS * 3600 - elapsed) / 3600
                return f"绝对亏损冷却，剩余 {remain_h:.1f}h"

        # 连续亏损阻断 — 4h 自动解
        if state.consecutive_loss_blocked:
            elapsed = now - state.consecutive_loss_blocked_at
            if elapsed >= settings.CONSECUTIVE_LOSS_COOLDOWN_HOURS * 3600:
                state.consecutive_loss_blocked = False
                logger.info(
                    f"[{state.name}] 连续亏损冷却到期（{elapsed/3600:.1f}h），恢复开仓"
                )
            else:
                remain_h = (settings.CONSECUTIVE_LOSS_COOLDOWN_HOURS * 3600 - elapsed) / 3600
                return f"连续亏损冷却，剩余 {remain_h:.1f}h"

        # 快速出场阻断 — 2h 自动解
        if state.rapid_exit_blocked:
            elapsed = now - state.rapid_exit_blocked_at
            if elapsed >= settings.RAPID_EXIT_COOLDOWN_SECONDS:
                state.rapid_exit_blocked = False
                logger.info(
                    f"[{state.name}] 快速出场冷却到期（{elapsed/60:.0f}min），恢复开仓"
                )
            else:
                remain_m = (settings.RAPID_EXIT_COOLDOWN_SECONDS - elapsed) / 60
                return f"快速出场阻断，剩余 {remain_m:.0f}min"

        return None

    def start(self):
        logger.info("=" * 60)
        logger.info("XAUUSD 多策略交易系统 启动")
        logger.info(f"品种: {settings.SYMBOL} | 手数: {settings.LOT_SIZE}")
        for s in self.strategies:
            logger.info(f"  策略: {s.name} | Magic={s.magic} | TF={s.timeframe} | "
                        f"双倍首单={s.double_first} | 最大仓位={s.max_positions}")
        logger.info("=" * 60)

        if not self.bridge.connect():
            logger.error("无法连接 MT4")
            return

        # 初始化策略风控状态
        for s in self.strategies:
            self._init_risk_state(s.name, s.magic)

        # 接管现有持仓 + 填充 _entry_times
        for s in self.strategies:
            existing = self.bridge.takeover_existing_positions(settings.SYMBOL, s.magic)
            self._known_position_count[s.magic] = len(existing)  # 初始化本地计数
            for pos in existing:
                # 以当前时间作为近似入场时间（无法获取真实开仓时间）
                self._entry_times[pos.ticket] = time.time()
                logger.info(f"[接管] {s.name} Ticket={pos.ticket} 已记录入场时间")

        self._daily_start_balance = self._get_balance()
        self.running = True

        # 新闻过滤初始化加载
        windows = self.news_filter.get_blackout_windows()
        if windows:
            logger.info(f"[新闻过滤] 已加载 {len(windows)} 个禁售窗口:")
            for s, e, t in windows[:5]:
                logger.info(f"  {s.strftime('%m-%d %H:%M')} ~ {e.strftime('%H:%M')} | {t}")

        logger.info("进入主循环...")

        while self.running:
            try:
                self._tick()
            except KeyboardInterrupt:
                logger.info("收到中断信号，停止交易")
                self.running = False
            except Exception as e:
                logger.exception(f"主循环异常: {e}")
                time.sleep(60)

        self.bridge.disconnect()
        logger.info("交易引擎已停止")

    def _tick(self):
        # 取策略快照（线程安全，允许运行中加减策略）
        with self._strategies_lock:
            snapshot = list(self.strategies)

        # 配置热重载
        try:
            mtime = os.path.getmtime(settings.__file__)
            if mtime > self._config_mtime:
                self._config_mtime = mtime
                importlib.reload(settings)
                for s in snapshot:
                    s.reload_config()
                logger.info("[热重载] 配置已更新")
        except OSError:
            pass

        # 周期性同步K线数据到SQLite
        self._sync_market_data()

        self._check_status_report()

        # ---- 新闻风险处理：收紧止损 or 强制平仓 ----
        self._handle_news_risk(snapshot)

        # ---- 止损平仓：所有风控/新闻禁售不限制平仓 ----
        for strategy in snapshot:
            self._run_exits(strategy)

        # ---- 多策略协调出场：信号盈利时联动平目标 ----
        self._coordinated_exits(snapshot)

        # ---- 短周期反向止盈：M15/M5 趋势反转时平盈利单 ----
        self._check_trend_reverse_tp()

        # 更新浮动盈亏
        self._update_floating_pnl()

        # ---- 阻断检查 ----
        global_blocked = self._check_global_loss()

        news_blocked = False
        if not global_blocked:
            news_blocked = self._check_news_blackout()

        safety_blocked = False
        if not global_blocked and not news_blocked:
            if self._is_safety_locked():
                safety_blocked = True
                logger.warning("[安全锁] 检测到锁文件，暂停开新仓")

        if global_blocked or news_blocked or safety_blocked:
            # 有全局阻断时，跳过本轮开仓，但每策略仍检查浮动亏损
            self._check_floating_loss_blocks()
            for _ in range(3):
                time.sleep(20)
                self.bridge.send_heartbeat()
            return

        # ---- 浮动亏损警告/阻断检查 ----
        self._check_floating_loss_blocks()

        # ---- 开仓：逐策略判断 ----
        for strategy in snapshot:
            block_reason = self._is_strategy_blocked(strategy.magic)
            if block_reason:
                logger.info(f"[{strategy.name}] 跳过开仓: {block_reason}")
                continue
            self._run_strategy(strategy)

    def _coordinated_exits(self, snapshot: list):
        """多策略协调出场：信号策略盈利时，联动关闭目标策略的同向盈利单"""
        try:
            coord = settings.COORDINATOR_CONFIG
        except AttributeError:
            return

        if not coord.get("enabled", False) or not coord.get("cross_exit_enabled", False):
            return

        signal_name = coord.get("signal_strategy", "")
        signal_dir = coord.get("signal_direction", "BUY")
        target_names = coord.get("target_strategies", [])
        target_dir = coord.get("target_direction", "SELL")
        if not signal_name or not target_names:
            return

        # 策略名 → magic 映射
        signal_magic = None
        target_magics: set[int] = set()
        for name, cfg in settings.STRATEGY_POOL.items():
            if name == signal_name:
                signal_magic = cfg["magic"]
            if name in target_names:
                target_magics.add(cfg["magic"])
        if signal_magic is None or not target_magics:
            return

        # 获取所有持仓
        try:
            positions = self.bridge.get_positions(settings.SYMBOL)
        except Exception as e:
            logger.warning(f"[协调器] 获取持仓失败: {e}")
            return

        # 信号策略的盈利单？
        signal_profit = 0.0
        signal_found = False
        for pos in positions:
            if pos.magic != signal_magic:
                continue
            is_buy = pos.order_type in ("OP_BUY", "BUY")
            if signal_dir == "BUY" and is_buy and pos.profit > 0:
                signal_profit = pos.profit
                signal_found = True
                break
            elif signal_dir == "SELL" and not is_buy and pos.profit > 0:
                signal_profit = pos.profit
                signal_found = True
                break

        if not signal_found:
            return

        # 联动关闭目标策略的盈利单
        target_is_buy = target_dir == "BUY"
        closed = 0
        for pos in positions:
            if pos.magic not in target_magics:
                continue
            is_buy = pos.order_type in ("OP_BUY", "BUY")
            if is_buy != target_is_buy:
                continue
            if pos.profit <= 0:
                continue

            logger.info(
                f"[协调器] {signal_name} {signal_dir}盈利 ${signal_profit:.2f} → "
                f"平 Magic={pos.magic} {target_dir} ticket={pos.ticket} "
                f"盈利 ${pos.profit:.2f}"
            )
            try:
                self.bridge.close_order(pos.ticket)
                direction = "BUY" if is_buy else "SELL"
                self._record_close(pos.ticket, pos.profit, pos.magic, direction)
                closed += 1
            except Exception as e:
                logger.error(f"[协调器] 平仓失败 ticket={pos.ticket}: {e}")

        if closed > 0:
            logger.info(f"[协调器] 本轮联动平仓 {closed} 单")

    def _check_trend_reverse_tp(self):
        """M15/M5 反向止盈：短周期趋势反转时平盈利单"""
        try:
            coord = settings.COORDINATOR_CONFIG
        except AttributeError:
            return

        if not coord.get("enabled", False):
            return

        timeframes = []
        if coord.get("m15_reverse_tp_enabled", False):
            timeframes.append("M15")
        if coord.get("m5_reverse_tp_enabled", False):
            timeframes.append("M5")
        if not timeframes:
            return

        try:
            positions = self.bridge.get_positions(settings.SYMBOL)
        except Exception as e:
            logger.warning(f"[反向止盈] 获取持仓失败: {e}")
            return

        if not positions:
            return

        # 策略名 → magic 映射
        strategy_names = {}
        for name, cfg in settings.STRATEGY_POOL.items():
            strategy_names[cfg["magic"]] = name

        closed_this_tick: set[int] = set()  # 防止同 tick 重复平仓

        for tf in timeframes:
            count = 60 if tf == "M15" else 120  # M15≈15h, M5≈10h
            try:
                candles = self.bridge.get_candles(settings.SYMBOL, tf, count)
            except Exception as e:
                logger.warning(f"[反向止盈] 获取{tf}数据失败: {e}")
                continue
            if not candles or len(candles) < count:
                continue

            closes = [c.close for c in candles]

            # 计算 EMA20 斜率（最近 3 根）
            k = 2.0 / 21
            ema = closes[0]
            ema_values = [ema]
            for p in closes[1:]:
                ema = (p - ema) * k + ema
                ema_values.append(ema)

            if len(ema_values) < 6:
                continue

            ema_slope = ema_values[-1] - ema_values[-4]  # 最近 3 根
            trend_up = ema_slope > 0
            trend_down = ema_slope < 0

            for pos in positions:
                if pos.ticket in closed_this_tick:
                    continue
                if pos.profit <= 0:
                    continue
                is_buy = pos.order_type in ("OP_BUY", "BUY")
                name = strategy_names.get(pos.magic, f"Magic={pos.magic}")

                # 空单但 M15/M5 趋势转多 → 止盈
                if not is_buy and trend_up:
                    logger.info(
                        f"[反向止盈] {name} {tf}转多 ticket={pos.ticket} "
                        f"盈利=${pos.profit:.2f} → 平仓"
                    )
                    try:
                        self.bridge.close_order(pos.ticket)
                        self._record_close(pos.ticket, pos.profit, pos.magic, "SELL")
                        closed_this_tick.add(pos.ticket)
                    except Exception as e:
                        logger.error(f"[反向止盈] 平仓失败 ticket={pos.ticket}: {e}")

                # 多单但 M15/M5 趋势转空 → 止盈
                elif is_buy and trend_down:
                    logger.info(
                        f"[反向止盈] {name} {tf}转空 ticket={pos.ticket} "
                        f"盈利=${pos.profit:.2f} → 平仓"
                    )
                    try:
                        self.bridge.close_order(pos.ticket)
                        self._record_close(pos.ticket, pos.profit, pos.magic, "BUY")
                        closed_this_tick.add(pos.ticket)
                    except Exception as e:
                        logger.error(f"[反向止盈] 平仓失败 ticket={pos.ticket}: {e}")

    def _check_floating_loss_blocks(self):
        """检查并更新各策略浮动亏损状态（警告 + 阻断）"""
        balance = self._get_balance()
        if balance <= 0:
            return
        for state in self._risk_states.values():
            if state.floating_pnl >= 0:
                continue
            loss_pct = abs(state.floating_pnl) / balance * 100

            # 阻断线
            if loss_pct >= settings.FLOATING_LOSS_BLOCK_PCT:
                if not state.floating_loss_blocked:
                    logger.warning(
                        f"[{state.name}] 浮动亏损 {loss_pct:.2f}% >= "
                        f"{settings.FLOATING_LOSS_BLOCK_PCT}%，阻断开仓"
                    )
                state.floating_loss_blocked = True
            # 警告线
            elif loss_pct >= settings.FLOATING_LOSS_WARN_PCT:
                if not state.floating_loss_blocked:
                    logger.info(
                        f"[{state.name}] 浮动亏损 {loss_pct:.2f}% >= "
                        f"{settings.FLOATING_LOSS_WARN_PCT}%（仅警告，不阻断）"
                    )

    def _run_exits(self, strategy):
        """止损平仓 — 不受风控/新闻禁售限制，但记录试算日志"""
        strategy.refresh_data()
        positions = self.bridge.get_positions(settings.SYMBOL)
        my_positions = [p for p in positions if p.magic == strategy.magic]
        if not my_positions:
            return
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        now = time.time()
        for pos in my_positions:
            should_exit = strategy.check_ema20_exit(pos, bid, ask)
            if not should_exit:
                continue

            # === 平仓试算 ===
            entry = pos.open_price
            hold_sec = now - self._entry_times.get(pos.ticket, now)
            if pos.order_type in ("OP_BUY", "BUY"):
                exit_price = bid
                pnl = (bid - entry) * settings.LOT_SIZE * 100
            else:
                exit_price = ask
                pnl = (entry - ask) * settings.LOT_SIZE * 100

            logger.info(
                f"[平仓试算] Ticket={pos.ticket} {pos.order_type} "
                f"入场={entry:.2f} 出场={exit_price:.2f} 盈亏=${pnl:.2f} "
                f"持仓={hold_sec:.0f}秒 SL={pos.stop_loss:.2f}"
            )

            # 可疑平仓检测：持仓极短且亏损
            if hold_sec < MIN_HOLD_SECONDS and pnl < 0:
                self._lock_new_entries(
                    f"可疑秒平 Ticket={pos.ticket}: "
                    f"入场={entry:.2f} 出场={exit_price:.2f} 持仓={hold_sec:.0f}秒 亏损=${abs(pnl):.2f}"
                )

            logger.info(f"[{strategy.name}] 策略出场 Ticket={pos.ticket}")
            self.bridge.close_order(pos.ticket)
            # 记录平仓：已实现盈亏 + 快速出场检测
            direction = "BUY" if pos.order_type in ("OP_BUY", "BUY") else "SELL"
            self._record_close(pos.ticket, pnl, strategy.magic, direction)

            # 记录已平仓明细到内存 + JSONL 文件
            close_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            record = dict(
                ticket=pos.ticket,
                symbol=pos.symbol,
                order_type=pos.order_type,
                volume=pos.volume,
                entry_price=entry,
                exit_price=exit_price,
                pnl=round(pnl, 2),
                stop_loss=pos.stop_loss,
                take_profit=pos.take_profit,
                swap=pos.swap,
                commission=pos.commission,
                magic=pos.magic,
                strategy=strategy.name,
                open_time=pos.open_time,
                close_time=close_time,
                hold_seconds=round(hold_sec),
                exit_reason="strategy_exit",
            )
            self._closed_trades.append(record)
            try:
                with open(self._trades_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError:
                pass

    def _lock_new_entries(self, reason: str):
        """安全锁：暂停开新仓，已持仓仍可正常平仓"""
        try:
            with open(SAFETY_LOCK_FILE, "w", encoding="utf-8") as f:
                f.write(f"LOCKED {datetime.now():%Y-%m-%d %H:%M:%S}\n{reason}\n")
            logger.error(f"[安全锁] 暂停开新仓！原因: {reason}")
        except OSError:
            logger.error(f"[安全锁] 写入锁文件失败: {reason}")

    def _is_safety_locked(self) -> bool:
        """检查安全锁文件是否存在，90 分钟自动过期"""
        try:
            if os.path.exists(SAFETY_LOCK_FILE):
                mtime = os.path.getmtime(SAFETY_LOCK_FILE)
                timeout = settings.SAFETY_LOCK_TIMEOUT_MINUTES * 60
                if time.time() - mtime > timeout:
                    os.remove(SAFETY_LOCK_FILE)
                    logger.info(f"[安全锁] 已自动清除（超过 {settings.SAFETY_LOCK_TIMEOUT_MINUTES}min）")
                    return False
                return True
        except OSError:
            pass
        return False

    def _run_strategy(self, strategy):
        """单个策略的一次 tick — 信号生成 + 开仓"""
        # 刷新数据
        strategy.refresh_data()

        # 获取该策略的持仓（桥接查询 + 本地跟踪双重校验防漏）
        positions = self.bridge.get_positions(settings.SYMBOL)
        my_positions = [p for p in positions if p.magic == strategy.magic]
        n_bridge = len(my_positions)
        n_local = self._known_position_count.get(strategy.magic, 0)
        n_total = max(n_bridge, n_local)  # 取较大值防止桥接漏查
        n_longs = sum(1 for p in my_positions if p.order_type in ("OP_BUY", "BUY"))
        n_shorts = sum(1 for p in my_positions if p.order_type in ("OP_SELL", "SELL"))
        logger.info(f"[{strategy.name}] 持仓: {n_total} (多:{n_longs} 空:{n_shorts})")

        if n_bridge != n_local:
            logger.warning(f"[{strategy.name}] 持仓不一致: 桥接={n_bridge} 本地={n_local}，取较大值={n_total}")

        if n_total >= strategy.max_positions:
            return  # 已达上限

        # 已有持仓则不加仓
        if n_total > 0:
            return

        # 生成信号
        signal = strategy.on_tick()
        if not signal:
            return

        # 止盈冷却检查：盈利平仓后 N 小时内不再开同向单
        signal_dir = "BUY" if "BUY" in signal else "SELL"
        cool = self._profit_exit_cooldown.get(strategy.magic, {})
        if signal_dir in cool:
            elapsed = time.time() - cool[signal_dir]
            cooldown_sec = settings.PROFIT_EXIT_COOLDOWN_HOURS * 3600
            if elapsed < cooldown_sec:
                remain_h = (cooldown_sec - elapsed) / 3600
                logger.info(f"[{strategy.name}] {signal_dir} 止盈冷却中（剩余 {remain_h:.1f}h），跳过开仓")
                return
            else:
                cool.pop(signal_dir, None)

        logger.info(f"[{strategy.name}] 收到信号: {signal}")

        # 双倍首单
        if signal == "信号: BUY":
            self._execute_buy(strategy)
            if strategy.double_first:
                self._execute_buy(strategy)
        elif signal == "信号: SELL":
            self._execute_sell(strategy)
            if strategy.double_first:
                self._execute_sell(strategy)

    def _execute_buy(self, strategy):
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        if hasattr(strategy, 'get_dynamic_sl_tp'):
            sl, tp = strategy.get_dynamic_sl_tp(OrderType.BUY, ask)
            if sl is None or tp is None:
                sl = ask - settings.STOP_LOSS_PIPS * 0.01
                tp = ask + settings.TAKE_PROFIT_PIPS * 0.01
        else:
            sl = ask - settings.STOP_LOSS_PIPS * 0.01
            tp = ask + settings.TAKE_PROFIT_PIPS * 0.01

        ticket = self.bridge.open_order(
            symbol=settings.SYMBOL,
            order_type=OrderType.BUY,
            volume=settings.LOT_SIZE,
            price=ask,
            sl=sl,
            tp=tp,
            comment=strategy.name,
            magic=strategy.magic,
        )
        if ticket:
            self._known_position_count[strategy.magic] = self._known_position_count.get(strategy.magic, 0) + 1
            logger.info(f"[{strategy.name}] 开多仓 Magic={strategy.magic} "
                        f"{settings.LOT_SIZE}手 @ {ask:.2f} SL={sl:.2f} TP={tp:.2f} Ticket={ticket}")
            self._entry_times[ticket] = time.time()
            if hasattr(strategy, 'mark_extreme_entry'):
                strategy.mark_extreme_entry(ticket)

    def _execute_sell(self, strategy):
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        if hasattr(strategy, 'get_dynamic_sl_tp'):
            sl, tp = strategy.get_dynamic_sl_tp(OrderType.SELL, bid)
            if sl is None or tp is None:
                sl = bid + settings.STOP_LOSS_PIPS * 0.01
                tp = bid - settings.TAKE_PROFIT_PIPS * 0.01
        else:
            sl = bid + settings.STOP_LOSS_PIPS * 0.01
            tp = bid - settings.TAKE_PROFIT_PIPS * 0.01

        ticket = self.bridge.open_order(
            symbol=settings.SYMBOL,
            order_type=OrderType.SELL,
            volume=settings.LOT_SIZE,
            price=bid,
            sl=sl,
            tp=tp,
            comment=strategy.name,
            magic=strategy.magic,
        )
        if ticket:
            self._known_position_count[strategy.magic] = self._known_position_count.get(strategy.magic, 0) + 1
            logger.info(f"[{strategy.name}] 开空仓 Magic={strategy.magic} "
                        f"{settings.LOT_SIZE}手 @ {bid:.2f} SL={sl:.2f} TP={tp:.2f} Ticket={ticket}")
            self._entry_times[ticket] = time.time()
            if hasattr(strategy, 'mark_extreme_entry'):
                strategy.mark_extreme_entry(ticket)

    def _get_balance(self) -> float:
        info = self.bridge.get_account_info()
        return info.balance if info else 0.0

    def _get_equity(self) -> float:
        info = self.bridge.get_account_info()
        return info.equity if info else 0.0

    def _handle_news_risk(self, snapshot: list):
        """新闻事件三级风控：收紧 → 强平 → 封仓"""
        # ① 强平窗口：平所有持仓
        if self.news_filter.is_in_force_close():
            logger.warning("[新闻风控] 强制平仓窗口 (事件前15min)，平所有持仓")
            for strategy in snapshot:
                self._close_strategy_positions(strategy, "news_force_close")
            return

        # ② 收紧窗口：收紧止损
        if self.news_filter.is_in_pre_tighten():
            logger.info("[新闻风控] 收紧窗口 (事件前2h~15min)，收紧所有策略止损")
            for strategy in snapshot:
                strategy.tight_exit_mode = True
            return

        # ③ 正常模式：关闭收紧
        for strategy in snapshot:
            if strategy.tight_exit_mode:
                strategy.tight_exit_mode = False

    def _close_strategy_positions(self, strategy, reason: str):
        """平掉某个策略的所有持仓，记录指定出场原因"""
        positions = self.bridge.get_positions(settings.SYMBOL)
        my_positions = [p for p in positions if p.magic == strategy.magic]
        if not my_positions:
            return
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        for pos in my_positions:
            entry = pos.open_price
            if pos.order_type in ("OP_BUY", "BUY"):
                pnl = (bid - entry) * settings.LOT_SIZE * 100
                exit_price = bid
            else:
                pnl = (entry - ask) * settings.LOT_SIZE * 100
                exit_price = ask
            logger.warning(
                f"[新闻风控] 强制平仓 Ticket={pos.ticket} {pos.order_type} "
                f"入场={entry:.2f} 盈亏=${pnl:.2f} 原因={reason}"
            )
            self.bridge.close_order(pos.ticket)
            direction = "BUY" if pos.order_type in ("OP_BUY", "BUY") else "SELL"
            self._record_close(pos.ticket, pnl, strategy.magic, direction)
            # 记录已平仓明细
            close_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            hold_sec = int(time.time() - pos.open_time)
            record = dict(
                ticket=pos.ticket, symbol=pos.symbol,
                order_type=pos.order_type, volume=pos.volume,
                entry_price=entry, exit_price=exit_price,
                pnl=round(pnl, 2), stop_loss=pos.stop_loss,
                take_profit=pos.take_profit, swap=pos.swap,
                commission=pos.commission, magic=pos.magic,
                strategy=strategy.name, open_time=pos.open_time,
                close_time=close_time, hold_seconds=hold_sec,
                exit_reason=reason,
            )
            self._closed_trades.append(record)
            try:
                with open(self._trades_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError:
                pass

    def _check_news_blackout(self) -> bool:
        """检查是否在新闻禁售期，每次主循环检查"""
        blocked, reason = self.news_filter.is_in_blackout()
        if blocked:
            logger.info(f"[新闻过滤] 禁售时段: {reason}，跳过开仓")
            for _ in range(3):
                time.sleep(20)
                self.bridge.send_heartbeat()
            return True
        return False

    def _sync_market_data(self):
        """周期性同步 K 线数据到 SQLite，仅同步活跃策略的周期"""
        now = time.time()
        if now - self._last_data_sync < self._data_sync_interval:
            return
        self._last_data_sync = now

        active_tfs = set()
        with self._strategies_lock:
            for s in self.strategies:
                active_tfs.add(s.timeframe)
        if not active_tfs:
            return

        logger.info(f"[数据同步] 开始增量同步周期: {active_tfs}")
        for tf in sorted(active_tfs):
            try:
                n = download_timeframe(self.bridge, tf, settings.SYMBOL)
                if n > 0:
                    logger.info(f"[数据同步] {tf} 写入 {n} 条")
            except Exception as e:
                logger.warning(f"[数据同步] {tf} 失败: {e}")
        logger.info(f"[数据同步] 完成")

    def _check_status_report(self):
        now = time.time()
        if now - self._last_report_time < self._report_interval:
            return
        self._last_report_time = now
        self._status_report()

    def _status_report(self):
        info = self.bridge.get_account_info()
        if not info:
            return

        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        all_positions = self.bridge.get_positions(settings.SYMBOL)

        with self._strategies_lock:
            strategies_snapshot = list(self.strategies)
            strategy_magics = [s.magic for s in strategies_snapshot]

        report = (
            f"\n{'='*50}\n"
            f"  XAUUSD 多策略状态  {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"{'='*50}\n"
            f"  余额:     ${info.balance:.2f}\n"
            f"  净值:     ${info.equity:.2f}\n"
            f"{'='*50}\n"
        )

        total_pnl = 0.0
        for s in strategies_snapshot:
            my_pos = [p for p in all_positions if p.magic == s.magic]
            pnl = sum(p.profit for p in my_pos)
            total_pnl += pnl

            state = self._risk_states.get(s.magic)
            realized = state.realized_pnl if state else 0.0
            blocked = self._is_strategy_blocked(s.magic)

            report += (
                f"  [{s.name}] Magic={s.magic} TF={s.timeframe} "
                f"持仓={len(my_pos)} 浮动=${pnl:.2f} "
                f"已实现=${realized:.2f}"
            )
            if blocked:
                report += f" ⛔{blocked}"
            report += "\n"

        manual = [p for p in all_positions if p.magic not in strategy_magics]
        manual_pnl = sum(p.profit for p in manual)
        if manual:
            report += f"  [手工单] 持仓={len(manual)} 浮动=${manual_pnl:.2f}\n"

        report += (
            f"  ---\n"
            f"  总浮动盈亏: ${total_pnl + manual_pnl:.2f}\n"
            f"  当前价:     Bid={bid:.2f} Ask={ask:.2f}\n"
            f"{'='*50}\n"
        )
        logger.info(report)


def main():
    engine = TradingEngine()
    engine.start()


if __name__ == "__main__":
    main()
