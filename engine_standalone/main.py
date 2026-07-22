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
from core.bridge import create_bridge_pair, OrderType
from services.news_filter import NewsFilter
from services.mtf_coordinator import MTFResonanceCoordinator
from services.supervisor import TradeSupervisor
from core.runtime_config import RuntimeConfig
from data.downloader import download_timeframe
from data import database as db
from strategies.scanner import scan_strategies

# 日志配置（仅在未配置时设置，避免被 Dashboard 引入重复 handler）
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[
            logging.FileHandler(f"{settings.LOG_DIR}/trading_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
logger = logging.getLogger(__name__)

SAFETY_LOCK_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "safety_lock.txt")
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


def create_strategies(bridge, pool=None):
    """从 STRATEGY_POOL 创建策略实例列表（enabled=false 或 max_positions=0 跳过）"""
    if pool is None:
        pool = settings.STRATEGY_POOL
    strategies = []
    for name, cfg in pool.items():
        cls = scan_strategies().get(name)
        if cls is None:
            logger.warning(f"未知策略: {name}，跳过")
            continue
        if not cfg.get("enabled", True):
            logger.info(f"[策略加载] {name} 已禁用，跳过")
            continue
        if cfg.get("max_positions", 1) == 0:
            logger.info(f"[策略加载] {name} 最大持仓为 0，跳过")
            continue
        strategy = cls(bridge, magic=cfg["magic"], timeframe=cfg["timeframe"])
        strategy.magic = cfg["magic"]
        strategy.double_first = cfg.get("double_first", False)
        strategy.max_positions = cfg.get("max_positions", 1)
        strategies.append(strategy)
        logger.info(f"[策略加载] {name} Magic={strategy.magic} TF={strategy.timeframe}")
    return strategies


class TradingEngine:
    """多策略交易引擎"""

    def __init__(self, config_service=None):
        self._config_service = config_service
        # 三轨架构：双桥接 + 数据工厂 + 运动员
        # 数据桥接(推送K线/报价) 和 执行桥接(下单)，纸面模式下执行桥接用PaperBridge包装
        from services.data_factory import DataFactory, get_cache, get_tick
        from engine_standalone.athlete import Athlete
        self._data_bridge, self._exec_bridge = create_bridge_pair()
        self.bridge = self._exec_bridge            # 引擎主桥接 = 执行通道
        self._data_factory = DataFactory(self._data_bridge)
        self._athlete = Athlete(self._exec_bridge)
        logger.info("[三轨] 双桥接 + DataFactory + Athlete 初始化成功，待连接")
        pool = self._get_strategy_pool()
        self.strategies = create_strategies(self.bridge, pool)
        self._strategies_lock = threading.Lock()
        self.news_filter = NewsFilter()
        self._mtf_coordinator = None  # lazy init
        self.running = False
        self._last_balance_check = 0
        self._daily_start_balance = 0.0
        self._last_snapshot_time = 0.0
        self._last_risk_save_time = 0.0
        self._global_loss_blocked = False
        self._last_report_time = 0
        self._report_interval = 4 * 3600
        self._config_mtime = 0.0
        self._rtconfig_mtime = 0.0
        self._last_news_check = 0.0
        self._last_data_sync = 0.0
        self._data_sync_interval = 300  # 每300秒（5分钟）同步一次数据
        self._last_recover_time = 0.0   # 上次成交恢复时间
        self._mt4_offset: float = 0.0                    # MT4 服务器 vs 本机 UTC 的偏移秒数
        self._last_reverse_tp_bar: dict[int, dict[str, int]] = {}  # magic → timeframe → 已止盈的 bar 起始时间
        self._entry_times: dict[int | str, float] = {}     # ticket → 开仓时间戳
        self._shutdown_requested = False                   # 优雅关闭标记
        self._entry_signal_data: dict[int | str, dict] = {}  # ticket → 开仓时信号数据
        self._risk_states: dict[int, StrategyRiskState] = {}  # magic → 风控状态
        self._known_position_count: dict[int, int] = {}    # magic → 本地跟踪持仓数（防桥接漏查）
        self._closed_trades: list[dict] = []               # 已平仓记录（内存）
        self._trades_file = os.path.join(settings.LOG_DIR, "closed_trades.jsonl")
        self._profit_exit_cooldown: dict[int, dict[str, float]] = {}  # magic → {方向 → 盈利平仓时间}
        self._load_closed_trades()
        # 监督者系统
        self.supervisor = TradeSupervisor()
        db.init_db()  # 确保所有表存在
        db.migrate_from_jsonl()  # 导入 JSONL 历史记录到 trades 表

    # ── 运行时配置读取（RuntimeConfig 优先，settings.py 回退）────────

    _RT_FALLBACK = {
        "lot_size": "LOT_SIZE",
        "stop_loss_pips": "STOP_LOSS_PIPS",
        "take_profit_pips": "TAKE_PROFIT_PIPS",
        "max_daily_loss_pct": "MAX_DAILY_LOSS_PCT",
        "floating_loss_warn_pct": "FLOATING_LOSS_WARN_PCT",
        "floating_loss_block_pct": "FLOATING_LOSS_BLOCK_PCT",
        "per_strategy_realized_loss_pct": "PER_STRATEGY_REALIZED_LOSS_PCT",
        "per_strategy_loss_block_hours": "PER_STRATEGY_LOSS_BLOCK_HOURS",
        "max_rapid_exits": "MAX_RAPID_EXITS",
        "rapid_exit_window_seconds": "RAPID_EXIT_WINDOW_SECONDS",
        "rapid_exit_cooldown_seconds": "RAPID_EXIT_COOLDOWN_SECONDS",
        "safety_lock_timeout_minutes": "SAFETY_LOCK_TIMEOUT_MINUTES",
        "per_strategy_realized_loss_amount": "PER_STRATEGY_REALIZED_LOSS_AMOUNT",
        "max_consecutive_losses": "MAX_CONSECUTIVE_LOSSES",
        "consecutive_loss_cooldown_hours": "CONSECUTIVE_LOSS_COOLDOWN_HOURS",
        "profit_exit_cooldown_hours": "PROFIT_EXIT_COOLDOWN_HOURS",
    }

    def _rt(self, key):
        """读取运行时配置（RuntimeConfig 优先），回退到 settings.py"""
        if self._config_service is not None:
            val = self._config_service.get(key)
            if val is not None:
                return val
        attr = self._RT_FALLBACK.get(key)
        if attr and hasattr(settings, attr):
            return getattr(settings, attr)
        return None

    def _get_strategy_pool(self):
        """获取策略池，RuntimeConfig 覆盖优先"""
        if self._config_service is not None:
            return self._config_service.get_strategy_pool()
        return dict(settings.STRATEGY_POOL)

    def _get_coordinator(self):
        """获取协调器配置，RuntimeConfig 覆盖优先"""
        try:
            return RuntimeConfig().get_coordinator_config()
        except Exception:
            return dict(settings.COORDINATOR_CONFIG)

    def _calibrate_mt4_time(self):
        """启动时校准 MT4 服务器时间 vs 本机 UTC 时间"""
        try:
            mt4_ts = self.bridge.get_server_time()
            if mt4_ts <= 0:
                logger.warning("[时间校准] MT4 服务器时间获取失败，跳过校准")
                return
            now_utc = int(time.time())
            self._mt4_offset = mt4_ts - now_utc
            sign = "+" if self._mt4_offset >= 0 else ""
            logger.info(f"[时间校准] MT4: {mt4_ts} | 本机UTC: {now_utc} | "
                       f"偏移: {sign}{self._mt4_offset/3600:.1f}h")
        except Exception as e:
            logger.warning(f"[时间校准] 失败: {e}")

    def _mt4_to_local(self, mt4_ts: int):
        """将 MT4 时间戳转为本地 datetime（UTC+5）"""
        from datetime import datetime
        from config.settings import LOCAL_TZ
        corrected = mt4_ts - self._mt4_offset
        return datetime.fromtimestamp(corrected, tz=LOCAL_TZ)

    @property
    def closed_trades(self) -> list[dict]:
        return list(self._closed_trades)

    # ── K 线获取（桥接优先 → 数据库补充）─────────────────────────

    @staticmethod
    def _pos_open_time(pos) -> tuple:
        """将 Position 的 open_time 转为 (格式化时间字符串, UNIX时间戳)"""
        from datetime import datetime
        from config.settings import LOCAL_TZ
        raw = str(pos.open_time)
        try:
            ts = int(raw)
            dt = datetime.fromtimestamp(ts, tz=LOCAL_TZ)
            return (dt.strftime("%Y-%m-%d %H:%M:%S"), ts)
        except (ValueError, OSError):
            # 可能是已格式化的时间字符串
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(raw, fmt)
                    return (raw, int(dt.timestamp()))
                except ValueError:
                    continue
            return (raw, 0)

    @staticmethod
    def _tf_to_seconds(tf: str) -> int:
        mapping = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}
        return mapping.get(tf, 0)

    @staticmethod
    def _parse_bridge_time(time_str: str) -> int:
        """将桥接 K 线时间字符串转为 UNIX 时间戳"""
        for fmt in ("%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S"):
            try:
                return int(datetime.strptime(time_str, fmt).timestamp())
            except ValueError:
                continue
        raise ValueError(f"无法解析桥接时间: {time_str}")

    def _db_to_candles(self, db_candles: list[dict]) -> list[Candle]:
        """将数据库 K 线 dict 转为 Candle 对象"""
        from config.settings import LOCAL_TZ
        result = []
        for c in db_candles:
            time_str = datetime.fromtimestamp(c["time"], tz=LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
            result.append(Candle(
                time=time_str,
                open=c["open"],
                high=c["high"],
                low=c["low"],
                close=c["close"],
                volume=c["volume"],
            ))
        return result

    def _get_candles(self, tf: str, count: int) -> list[Candle]:
        """获取 K 线，桥接优先 — 不足时从 market_data.db 补充"""
        # 1. 桥接优先
        try:
            candles = self.bridge.get_candles(settings.SYMBOL, tf, count)
        except Exception as e:
            logger.warning(f"[K线获取] {tf} 桥接失败: {e}")
            candles = []

        if len(candles) >= count:
            return candles

        # 2. 桥接数据不足 — 从数据库补充
        needed = count - len(candles)

        if not candles:
            db_raw = db.get_candles(tf, end_ts=int(time.time()), limit=count)
            if db_raw:
                logger.info(f"[K线获取] {tf} 桥接无数据，从数据库补充 {len(db_raw)} 条")
                return self._db_to_candles(db_raw)
            return []

        # 3. 桥接有部分数据 — 补充更早的
        try:
            oldest_ts = self._parse_bridge_time(candles[0].time)
        except Exception as e:
            logger.warning(f"[K线获取] {tf} 解析桥接头时间失败: {e}")
            return candles

        tf_sec = self._tf_to_seconds(tf)
        if tf_sec <= 0:
            return candles

        end_ts = oldest_ts - 1
        db_raw = db.get_candles(tf, end_ts=end_ts, limit=needed)
        if not db_raw:
            return candles

        db_candles = self._db_to_candles(db_raw)
        total = len(db_candles) + len(candles)
        logger.info(f"[K线获取] {tf} 桥接 {len(candles)} + 补充 {len(db_candles)} = {total}")

        return db_candles + candles

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

    def _recover_missing_trades(self):
        """启动时从 MT4 补充遗漏的历史成交记录"""
        try:
            orders = self.bridge.get_order_history(settings.SYMBOL)
        except Exception as e:
            logger.warning(f"[成交恢复] 获取历史失败: {e}")
            return
        if not orders:
            return

        existing_tickets = {t["ticket"] for t in self._closed_trades}
        missing = [o for o in orders if o["ticket"] not in existing_tickets]
        if not missing:
            logger.info(f"[成交恢复] 无需补充，已是最新")
            return

        records = []
        for order in missing:
            magic = order["magic"]
            strategy = f"magic_{magic}"
            # 尝试从策略池解析策略名
            for s in self.strategies:
                if s.magic == magic:
                    strategy = s.name
                    break
            open_dt = self._mt4_to_local(order["open_time"])
            close_dt = self._mt4_to_local(order["close_time"])
            hold_sec = int(order["close_time"] - order["open_time"])
            record = {
                "ticket": order["ticket"], "symbol": order["symbol"],
                "order_type": order["order_type"], "volume": order["volume"],
                "entry_price": order["open_price"], "exit_price": order["close_price"],
                "pnl": round(order["profit"], 2),
                "stop_loss": order["stop_loss"], "take_profit": order["take_profit"],
                "swap": round(order["swap"], 2), "commission": round(order["commission"], 2),
                "magic": magic, "strategy": strategy,
                "open_time": open_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "close_time": close_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "hold_seconds": hold_sec,
                "exit_reason": "mt4_history",
            }
            records.append(record)
            self._closed_trades.append(record)

        # 追加到 JSONL 文件 + 数据库
        try:
            with open(self._trades_file, "a", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning(f"[成交恢复] 写入文件失败: {e}")
        try:
            db.insert_trades_batch(records)
            for r in records:
                try:
                    sig = db.get_signal_by_ticket(r['ticket'])
                    if sig and sig.get('id'):
                        db.update_signal_status(sig['id'], {
                            'status': 'closed',
                            'exit_reason': 'mt4_hard_sl',
                            'exit_pnl': r['pnl'],
                            'exit_price': r['exit_price'],
                            'close_time': r['close_time'],
                        })
                except Exception:
                    pass
        except Exception:
            pass

        logger.info(f"[成交恢复] 补充 {len(records)} 条历史成交")

    # ======================== 成交同步监督 ========================

    def _check_trade_sync(self):
        """轻量监督：对比 MT4 历史与本地数据库的成交数量，不一致时告警"""
        try:
            orders = self.bridge.get_order_history(settings.SYMBOL)
            if not orders:
                return
        except Exception as e:
            logger.warning(f"[成交监督] 获取MT4历史失败: {e}")
            return

        mt4_count = len(orders)
        try:
            db_count = db.get_conn().execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        except Exception:
            return

        if mt4_count > db_count:
            missing = mt4_count - db_count
            logger.warning(
                f"[成交监督] MT4 有 {mt4_count} 笔，本地数据库 {db_count} 笔，"
                f"缺失 {missing} 笔，启动恢复..."
            )
            self._recover_missing_trades()
        elif mt4_count < db_count:
            logger.warning(
                f"[成交监督] 本地数据库 {db_count} 笔 > MT4 {mt4_count} 笔，"
                f"可能是 MT4 历史被清理"
            )
        else:
            logger.info(f"[成交监督] 数据一致 (MT4={mt4_count}, DB={db_count})")

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
            cls = scan_strategies().get(name)
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
                    if pos.magic in self._strategy_magics(strategy):
                        self.bridge.close_order(pos.ticket)
                        self._entry_times.pop(pos.ticket, None)
            self.strategies = [s for s in self.strategies if s.name != name]
            self._risk_states.pop(strategy.magic, None)
            logger.info(f"[策略动态移除] {name} Magic={strategy.magic}")
            return True

    def _sync_strategy_pool(self):
        """将 running strategy list 与 strategy_pool 配置同步（自动增删策略，无需重启）"""
        pool = self._get_strategy_pool()
        if pool is None:
            return

        with self._strategies_lock:
            current = {s.name: s for s in self.strategies}

        # 1. 移除：池中标记为禁用或 max_positions=0 的策略
        for name in list(current.keys()):
            cfg = pool.get(name)
            if cfg is None or not cfg.get("enabled", True) or cfg.get("max_positions", 1) == 0:
                if name in current:
                    self.remove_strategy(name, close_positions=True)
                    logger.info(f"[策略池同步] 已移除 {name}")

        # 重新获取快照（移除后 list 已变）
        with self._strategies_lock:
            current = {s.name: s for s in self.strategies}

        # 2. 添加：池中启用但未在运行中的策略
        for name, cfg in pool.items():
            if not cfg.get("enabled", True) or cfg.get("max_positions", 1) == 0:
                continue
            if name not in current:
                self.add_strategy(name, cfg)
                logger.info(f"[策略池同步] 已添加 {name}")

        # 3. 更新：参数变更（max_positions / double_first）
        with self._strategies_lock:
            for name, s in current.items():
                cfg = pool.get(name)
                if cfg is None:
                    continue
                if s.max_positions != cfg.get("max_positions", 1):
                    s.max_positions = cfg.get("max_positions", 1)
                    logger.info(f"[策略池同步] {name} max_positions → {s.max_positions}")
                if s.double_first != cfg.get("double_first", False):
                    s.double_first = cfg.get("double_first", False)
                    logger.info(f"[策略池同步] {name} double_first → {s.double_first}")

    @staticmethod
    def _strategy_magics(strategy) -> set[int]:
        """返回策略识别持仓的所有 magic 号（主 + legacy）"""
        return {strategy.magic} | set(getattr(strategy, 'legacy_magics', []))

    def _init_risk_state(self, name: str, magic: int):
        """初始化单策略风控状态"""
        if magic not in self._risk_states:
            self._risk_states[magic] = StrategyRiskState(name=name, magic=magic)

    def _update_floating_pnl(self):
        """更新所有策略的浮动盈亏（含 legacy magic 持仓）"""
        all_positions = self.bridge.get_positions(settings.SYMBOL)
        for state in self._risk_states.values():
            magics = {state.magic}
            for s in self.strategies:
                if s.magic == state.magic:
                    magics.update(self._strategy_magics(s))
                    break
            my_pos = [p for p in all_positions if p.magic in magics]
            state.floating_pnl = sum(p.profit for p in my_pos)

    def _record_close(self, ticket: int | str, pnl: float, magic: int, direction: str = ""):
        """记录平仓：更新已实现盈亏 + 快速出场检测（legacy magic 自动映射到主策略）"""
        # 如果 magic 是某个策略的 legacy，映射到主 magic
        for s in self.strategies:
            if magic in getattr(s, 'legacy_magics', []):
                magic = s.magic
                break
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
        while state.exit_timestamps and state.exit_timestamps[0] < now - self._rt('rapid_exit_window_seconds'):
            state.exit_timestamps.popleft()

        if len(state.exit_timestamps) >= self._rt('max_rapid_exits'):
            state.rapid_exit_blocked = True
            state.rapid_exit_blocked_at = now
            logger.error(
                f"[{state.name}] 快速出场阻断: {self._rt('rapid_exit_window_seconds')//60}min 内 "
                f"{len(state.exit_timestamps)} 次平仓（上限 {self._rt('max_rapid_exits')}），"
                f"冷却 {self._rt('rapid_exit_cooldown_seconds')//60}min"
            )

        # 连续亏损跟踪
        if pnl < 0:
            state.consecutive_losses += 1
            logger.info(
                f"[{state.name}] 连续亏损 {state.consecutive_losses} 次 "
                f"（上限 {self._rt('max_consecutive_losses')}）"
            )
            if state.consecutive_losses >= self._rt('max_consecutive_losses') and not state.consecutive_loss_blocked:
                state.consecutive_loss_blocked = True
                state.consecutive_loss_blocked_at = now
                logger.error(
                    f"[{state.name}] 连续亏损 {state.consecutive_losses} 次，"
                    f"冷却 {self._rt('consecutive_loss_cooldown_hours')}h"
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
                    f"{self._rt('profit_exit_cooldown_hours')}h 内不再开同向单"
                )

        # 绝对亏损阻断：已实现亏损 ≥$30 触发 12h 冷却
        if state.realized_pnl <= -self._rt('per_strategy_realized_loss_amount') and not state.realized_loss_amount_blocked:
            state.realized_loss_amount_blocked = True
            state.realized_loss_amount_blocked_at = now
            logger.error(
                f"[{state.name}] 已实现亏损 ${abs(state.realized_pnl):.2f} "
                f"（≥${self._rt('per_strategy_realized_loss_amount')}），"
                f"冷却 {self._rt('per_strategy_loss_block_hours')}h"
            )
        # 亏损回正自动解除
        if state.realized_pnl > 0 and state.realized_loss_amount_blocked:
            state.realized_loss_amount_blocked = False
            logger.info(f"[{state.name}] 已实现亏损回正，解除绝对亏损冷却")

        # 已实现亏损阻断检查（百分比）
        balance = self._get_balance()
        if balance > 0:
            loss_pct = abs(state.realized_pnl) / balance * 100
            threshold = self._rt('per_strategy_realized_loss_pct')
            if state.realized_pnl < 0 and loss_pct >= threshold and not state.realized_loss_blocked:
                state.realized_loss_blocked = True
                state.realized_loss_blocked_at = now
                logger.error(
                    f"[{state.name}] 已实现亏损 {loss_pct:.2f}%（≥{threshold}%），"
                    f"该策略暂停开仓 {self._rt('per_strategy_loss_block_hours')}h"
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
        if loss_pct >= self._rt('max_daily_loss_pct'):
            if not self._global_loss_blocked:
                logger.error(
                    f"[全局硬止损] 已实现亏损 {loss_pct:.2f}% "
                    f"（上限 {self._rt('max_daily_loss_pct')}%），全策略停开仓"
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
            if elapsed >= self._rt('per_strategy_loss_block_hours') * 3600:
                state.realized_loss_blocked = False
                logger.info(
                    f"[{state.name}] 已实现亏损阻断到期（{elapsed/3600:.1f}h），恢复开仓"
                )
            else:
                remain_h = (self._rt('per_strategy_loss_block_hours') * 3600 - elapsed) / 3600
                return f"已实现亏损阻断，剩余 {remain_h:.1f}h"

        # 浮动亏损阻断 — 降到 10% 以下自动恢复
        if state.floating_loss_blocked:
            balance = self._get_balance()
            if balance > 0:
                floating_pct = abs(state.floating_pnl) / balance * 100
                if floating_pct < self._rt('floating_loss_block_pct'):
                    state.floating_loss_blocked = False
                    logger.info(
                        f"[{state.name}] 浮动亏损已降至 {floating_pct:.2f}%，恢复开仓"
                    )
                else:
                    return f"浮动亏损阻断（{floating_pct:.2f}%）"

        # 绝对亏损阻断 — 12h 自动解
        if state.realized_loss_amount_blocked:
            elapsed = now - state.realized_loss_amount_blocked_at
            if elapsed >= self._rt('per_strategy_loss_block_hours') * 3600:
                state.realized_loss_amount_blocked = False
                logger.info(
                    f"[{state.name}] 绝对亏损冷却到期（{elapsed/3600:.1f}h），恢复开仓"
                )
            else:
                remain_h = (self._rt('per_strategy_loss_block_hours') * 3600 - elapsed) / 3600
                return f"绝对亏损冷却，剩余 {remain_h:.1f}h"

        # 连续亏损阻断 — 4h 自动解
        if state.consecutive_loss_blocked:
            elapsed = now - state.consecutive_loss_blocked_at
            if elapsed >= self._rt('consecutive_loss_cooldown_hours') * 3600:
                state.consecutive_loss_blocked = False
                logger.info(
                    f"[{state.name}] 连续亏损冷却到期（{elapsed/3600:.1f}h），恢复开仓"
                )
            else:
                remain_h = (self._rt('consecutive_loss_cooldown_hours') * 3600 - elapsed) / 3600
                return f"连续亏损冷却，剩余 {remain_h:.1f}h"

        # 快速出场阻断 — 2h 自动解
        if state.rapid_exit_blocked:
            elapsed = now - state.rapid_exit_blocked_at
            if elapsed >= self._rt('rapid_exit_cooldown_seconds'):
                state.rapid_exit_blocked = False
                logger.info(
                    f"[{state.name}] 快速出场冷却到期（{elapsed/60:.0f}min），恢复开仓"
                )
            else:
                remain_m = (self._rt('rapid_exit_cooldown_seconds') - elapsed) / 60
                return f"快速出场阻断，剩余 {remain_m:.0f}min"

        return None

    def _mtf_resonance_allowed(self, signal_dir: str) -> Optional[str]:
        """MTF 共振方向门禁: 返回当前允许的方向 (BUY/SELL) 或 None（不限制）"""
        coord_cfg = self._get_coordinator()
        if not coord_cfg.get("enabled", False) or not coord_cfg.get("mtf_resonance_enabled", False):
            return None
        if self._mtf_coordinator is None:
            self._mtf_coordinator = MTFResonanceCoordinator(self.bridge)
        return self._mtf_coordinator.get_allowed_direction()

    def start(self):
        logger.info("=" * 60)
        logger.info("XAUUSD 多策略交易系统 启动")
        logger.info(f"品种: {settings.SYMBOL} | 手数: {self._rt('lot_size')}")
        for s in self.strategies:
            logger.info(f"  策略: {s.name} | Magic={s.magic} | TF={s.timeframe} | "
                        f"双倍首单={s.double_first} | 最大仓位={s.max_positions}")
        logger.info("=" * 60)

        if not self.bridge.connect():
            logger.warning("无法连接 MT4，每 10 秒重试...")
            for attempt in range(30):  # 最多重试 5 分钟
                time.sleep(10)
                if self.bridge.connect():
                    logger.info(f"第 {attempt+1} 次重试后连接成功")
                    break
            else:
                logger.error("重试 30 次仍无法连接 MT4，退出")
                return

        # 初始化策略风控状态
        for s in self.strategies:
            self._init_risk_state(s.name, s.magic)

        # 从数据库恢复风控阻断状态
        try:
            saved_states = db.load_risk_states()
            for saved in saved_states:
                magic = saved["magic"]
                if magic in self._risk_states:
                    rs = self._risk_states[magic]
                    rs.realized_pnl = saved.get("realized_pnl", 0)
                    rs.consecutive_losses = saved.get("consecutive_losses", 0)
                    # 恢复快速出场计数器（重启不丢）
                    et_raw = saved.get("exit_timestamps", "[]")
                    try:
                        et_list = json.loads(et_raw) if isinstance(et_raw, str) else et_raw
                        now = time.time()
                        window = self._rt('rapid_exit_window_seconds')
                        # 只恢复窗口内的有效时间戳
                        valid = [t for t in et_list if now - t < window]
                        rs.exit_timestamps = deque(valid)
                    except (json.JSONDecodeError, TypeError):
                        pass
                    for flag in ("realized_loss_blocked", "floating_loss_blocked",
                                 "rapid_exit_blocked", "realized_loss_amount_blocked",
                                 "consecutive_loss_blocked"):
                        if saved.get(flag):
                            setattr(rs, flag, True)
                            setattr(rs, f"{flag}_at", time.time())
            if saved_states:
                logger.info(f"[风控恢复] 已恢复 {len(saved_states)} 个策略的风控状态")
        except Exception as e:
            logger.warning(f"[风控恢复] 加载失败: {e}")

        # 接管现有持仓（含 legacy magic）+ 填充 _entry_times
        for s in self.strategies:
            existing = []
            for magic in self._strategy_magics(s):
                existing.extend(self.bridge.takeover_existing_positions(settings.SYMBOL, magic))
            self._known_position_count[s.magic] = len(existing)
            for pos in existing:
                self._entry_times[pos.ticket] = time.time()
                logger.info(f"[接管] {s.name} Ticket={pos.ticket}(Magic={pos.magic}) 已记录入场时间")

        self._daily_start_balance = self._get_balance()
        self.running = True

        # 校准 MT4 服务器时间 vs 本机 UTC
        self._calibrate_mt4_time()

        # 自动补充遗漏历史成交
        self._recover_missing_trades()

        # 启动数据工厂独立线程（使用专用数据桥接）
        if self._data_factory:
            self._data_factory.start()
            time.sleep(5)

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

        # ★ 运动员先跑：处理上一轮遗留门票，避免策略处理耗时导致过期 ★
        if self._athlete:
            self._athlete.run()
            self._handle_athlete_opened()

        # 配置热重载
        try:
            mtime = os.path.getmtime(settings.__file__)
            if mtime > self._config_mtime:
                self._config_mtime = mtime
                importlib.reload(settings)
                RuntimeConfig().reload()
                logger.info("[热重载] RuntimeConfig 已重新加载，当前 active 配置已更新")
                for s in snapshot:
                    s.reload_config()
                logger.info("[热重载] 配置已更新")
        except OSError:
            pass

        # runtime_config.json 热重载（仪表盘配置变更时）
        try:
            from core.runtime_config import CONFIG_FILE
            rt_mtime = os.path.getmtime(CONFIG_FILE)
            if rt_mtime > self._rtconfig_mtime:
                self._rtconfig_mtime = rt_mtime
                RuntimeConfig().reload()
                for s in snapshot:
                    s.reload_config()
                logger.info("[RuntimeConfig] 热重载完成")
        except OSError:
            pass

        # 策略池热同步：自动增删策略（无需重启引擎）
        self._sync_strategy_pool()

        # 桥接连接保活：心跳失败时尝试重连
        try:
            self.bridge.send_heartbeat()
        except Exception:
            logger.warning("[桥接] 心跳失败，尝试重连...")
            try:
                self.bridge.disconnect()
                time.sleep(2)
                if self.bridge.connect():
                    logger.info("[桥接] 重连成功")
                else:
                    logger.error("[桥接] 重连失败")
            except Exception as e:
                logger.error(f"[桥接] 重连异常: {e}")

        # 周期性同步K线数据到SQLite
        self._sync_market_data()

        self._check_status_report()

        # ---- 日历定时拉取检查（24h 一次） ----
        self.news_filter.try_scheduled_fetch()

        # ---- 新闻风险处理：收紧止损 or 强制平仓 ----
        self._handle_news_risk(snapshot)

        # ---- 成交同步监督：每小时检查一次 MT4 与本地数据一致性 ----
        if time.time() - self._last_recover_time > 3600:
            self._check_trade_sync()
            self._last_recover_time = time.time()

        # ---- 止损平仓：所有风控/新闻禁售不限制平仓 ----
        for strategy in snapshot:
            self._run_exits(strategy)

        # ---- 多策略协调出场：信号盈利时联动平目标 ----
        self._coordinated_exits(snapshot)

        # ---- 短周期反向止盈：M15/M5 趋势反转时平盈利单 ----
        self._check_trend_reverse_tp()

        # 更新浮动盈亏
        self._update_floating_pnl()

        # 定期持久化账户快照和风控状态
        now = time.time()
        if now - self._last_snapshot_time >= 300:
            self._last_snapshot_time = now
            try:
                info = self.bridge.get_account_info()
                if info:
                    db.insert_account_snapshot({
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "balance": info.balance, "equity": info.equity,
                        "margin": info.margin, "free_margin": info.free_margin,
                        "leverage": info.leverage, "floating_pnl": info.equity - info.balance,
                    })
            except Exception:
                pass

        if now - self._last_risk_save_time >= 60:
            self._last_risk_save_time = now
            for magic, state in self._risk_states.items():
                try:
                    db.save_risk_state(magic, state.name, {
                        "realized_pnl": state.realized_pnl,
                        "consecutive_losses": state.consecutive_losses,
                        "exit_timestamps": json.dumps(list(state.exit_timestamps)),
                        "realized_loss_blocked": state.realized_loss_blocked,
                        "floating_loss_blocked": state.floating_loss_blocked,
                        "rapid_exit_blocked": state.rapid_exit_blocked,
                        "realized_loss_amount_blocked": state.realized_loss_amount_blocked,
                        "consecutive_loss_blocked": state.consecutive_loss_blocked,
                        "blocked_at": str(state.consecutive_loss_blocked_at) if state.consecutive_loss_blocked else "",
                    })
                except Exception:
                    pass

        # ---- 阻断检查（纸面模式全量测试，跳过所有风控） ----
        if not settings.PAPER_MODE:
            global_blocked = self._check_global_loss()

            news_blocked = False
            if not global_blocked:
                news_blocked = self._check_news_blackout()

            # ---- News-Bias 方向阻塞检查 ----
            bias_blocked = False
            if not global_blocked and not news_blocked:
                bias_blocked = self._check_news_bias_block()
                if bias_blocked:
                    logger.warning("[News-Bias] 方向阻塞触发，跳过开仓")

            safety_blocked = False
            if not global_blocked and not news_blocked:
                if self._is_safety_locked():
                    safety_blocked = True
                    logger.warning("[安全锁] 检测到锁文件，暂停开新仓")

            if global_blocked or news_blocked or safety_blocked or bias_blocked:
                # 有全局阻断时，跳过本轮开仓
                return

        # ---- 浮动亏损检查/阻断 ----
        self._check_floating_loss_blocks()

        # ---- 开仓：逐策略判断 ----
        for strategy in snapshot:
            if not settings.PAPER_MODE:
                block_reason = self._is_strategy_blocked(strategy.magic)
                if block_reason:
                    logger.info(f"[{strategy.name}] 跳过开仓: {block_reason}")
                    continue
            self._run_strategy(strategy)

        # 三轨：运动员验证（每 tick 轮询 + 处理回调）
        if self._athlete:
            self._athlete.run()
            self._handle_athlete_opened()

    def _handle_athlete_opened(self):
        """处理运动员开仓成功队列，回调策略的 mark_extreme_entry"""
        if not self._athlete._recently_opened:
            return
        opened = self._athlete._recently_opened
        self._athlete._recently_opened = []
        # 构建 strategy_name -> 实例 映射
        strat_map = {s.name: s for s in self.strategies}
        for ticket, strategy_name in opened:
            strategy = strat_map.get(strategy_name)
            if strategy and hasattr(strategy, "mark_extreme_entry"):
                try:
                    strategy.mark_extreme_entry(ticket)
                except Exception as e:
                    logger.warning(f"[运动员回调] {strategy_name}.mark_extreme_entry({ticket}) 失败: {e}")

    def _coordinated_exits(self, snapshot: list):
        """多策略协调出场：信号策略盈利时，联动关闭目标策略的同向盈利单"""
        coord = self._get_coordinator()
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
        for name, cfg in self._get_strategy_pool().items():
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
            net_profit = pos.profit - abs(pos.commission) - abs(pos.swap)
            if net_profit <= 0:
                continue

            logger.info(
                f"[协调器] {signal_name} {signal_dir}盈利 ${signal_profit:.2f} → "
                f"平 Magic={pos.magic} {target_dir} ticket={pos.ticket} "
                f"盈利=${net_profit:.2f}(毛={pos.profit:.2f})"
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
        """M15 反向止盈：短周期趋势反转时平盈利单（M5 过于敏感已移除）"""
        coord = self._get_coordinator()
        if not coord.get("enabled", False):
            return

        timeframes = []
        if coord.get("m15_reverse_tp_enabled", False):
            timeframes.append("M15")
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
        for name, cfg in self._get_strategy_pool().items():
            strategy_names[cfg["magic"]] = name

        closed_this_tick: set[int] = set()  # 防止同 tick 重复平仓

        for tf in timeframes:
            count = 60 if tf == "M15" else 120  # M15≈15h, M5≈10h
            try:
                candles = self._get_candles(tf, count)
            except Exception as e:
                logger.warning(f"[反向止盈] 获取{tf}数据失败: {e}")
                continue
            if not candles or len(candles) < count:
                continue

            closes = [c.close for c in candles[1:]]  # 排除当前未完成 bar (index 0)

            # 计算 EMA20 斜率（最近 3 根，仅已收盘 bar）
            k = 2.0 / 21
            ema = closes[0]
            ema_values = [ema]
            for p in closes[1:]:
                ema = (p - ema) * k + ema
                ema_values.append(ema)

            if len(ema_values) < 6:
                continue

            ema_slope = ema_values[-1] - ema_values[-4]  # 最近 3 根

            # 斜率归一化：用 ATR 衡量斜率大小，避免微小波动触发平仓
            sensitivity = coord.get('m15_reverse_tp_sensitivity', 0.5) if tf == 'M15' else coord.get('m5_reverse_tp_sensitivity', 0.5)
            if sensitivity > 0:
                tr_vals = []
                for i in range(1, len(candles[1:])):
                    c = candles[i]
                    pc = candles[i-1].close
                    tr_vals.append(max(c.high-c.low, abs(c.high-pc), abs(c.low-pc)))
                atr14 = sum(tr_vals[:14])/14 if len(tr_vals) >= 14 else 0
                if atr14 > 0:
                    trend_up = ema_slope > atr14 * sensitivity
                    trend_down = ema_slope < -atr14 * sensitivity
                else:
                    trend_up = ema_slope > 0
                    trend_down = ema_slope < 0
            else:
                trend_up = ema_slope > 0
                trend_down = ema_slope < 0

            # 确定当前 tf 的 bar 起始时间（同一根 bar 内不重复止盈）
            now_mt4 = int(time.time()) + int(self._mt4_offset)
            tf_sec = 900 if tf == "M15" else 300
            current_bar = (now_mt4 // tf_sec) * tf_sec

            for pos in positions:
                if pos.ticket in closed_this_tick:
                    continue
                # 同一根 bar 内每个 magic 只允许一次反向止盈
                if pos.magic in self._last_reverse_tp_bar:
                    last_bar = self._last_reverse_tp_bar[pos.magic].get(tf, 0)
                    if last_bar == current_bar:
                        continue

                net_profit = pos.profit - abs(pos.commission) - abs(pos.swap)
                if net_profit <= 0:
                    continue
                is_buy = pos.order_type in ("OP_BUY", "BUY")
                name = strategy_names.get(pos.magic, f"Magic={pos.magic}")

                # 空单但 M15/M5 趋势转多 → 止盈
                if not is_buy and trend_up:
                    logger.info(
                        f"[反向止盈] {name} {tf}转多 ticket={pos.ticket} "
                        f"净利=${net_profit:.2f}(毛={pos.profit:.2f}) → 平仓"
                    )
                    try:
                        self.bridge.close_order(pos.ticket)
                        self._record_close(pos.ticket, pos.profit, pos.magic, "SELL")
                        closed_this_tick.add(pos.ticket)
                        # 记录此 bar 已对本 magic 执行过止盈
                        if pos.magic not in self._last_reverse_tp_bar:
                            self._last_reverse_tp_bar[pos.magic] = {}
                        self._last_reverse_tp_bar[pos.magic][tf] = current_bar
                    except Exception as e:
                        logger.error(f"[反向止盈] 平仓失败 ticket={pos.ticket}: {e}")

                # 多单但 M15/M5 趋势转空 → 止盈
                elif is_buy and trend_down:
                    logger.info(
                        f"[反向止盈] {name} {tf}转空 ticket={pos.ticket} "
                        f"净利=${net_profit:.2f}(毛={pos.profit:.2f}) → 平仓"
                    )
                    try:
                        self.bridge.close_order(pos.ticket)
                        self._record_close(pos.ticket, pos.profit, pos.magic, "BUY")
                        closed_this_tick.add(pos.ticket)
                        if pos.magic not in self._last_reverse_tp_bar:
                            self._last_reverse_tp_bar[pos.magic] = {}
                        self._last_reverse_tp_bar[pos.magic][tf] = current_bar
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
            if loss_pct >= self._rt('floating_loss_block_pct'):
                if not state.floating_loss_blocked:
                    logger.warning(
                        f"[{state.name}] 浮动亏损 {loss_pct:.2f}% >= "
                        f"{self._rt('floating_loss_block_pct')}%，阻断开仓"
                    )
                state.floating_loss_blocked = True
            # 警告线
            elif loss_pct >= self._rt('floating_loss_warn_pct'):
                if not state.floating_loss_blocked:
                    logger.info(
                        f"[{state.name}] 浮动亏损 {loss_pct:.2f}% >= "
                        f"{self._rt('floating_loss_warn_pct')}%（仅警告，不阻断）"
                    )

    def _run_exits(self, strategy):
        """止损平仓 — 不受风控/新闻禁售限制，但记录试算日志"""
        positions = self.bridge.get_positions(settings.SYMBOL)
        my_positions = [p for p in positions if p.magic in self._strategy_magics(strategy)]
        # 检测 MT4 硬止损平仓（桥接消失但引擎没记录）
        prev_count = self._known_position_count.get(strategy.magic, 0)
        now_count = len(my_positions)
        if now_count < prev_count:
            logger.warning(f"[{strategy.name}] 检测到 {prev_count - now_count} 张持仓消失，启动成交恢复...")
            self._recover_missing_trades()
        # 同步本地持仓计数
        self._known_position_count[strategy.magic] = now_count
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
                pnl = (bid - entry) * self._rt('lot_size') * 100
            else:
                exit_price = ask
                pnl = (entry - ask) * self._rt('lot_size') * 100

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

            # 从 MT4 历史成交获取开平仓时间（同源，计算持仓时间准确）
            broker_open = 0
            broker_close = 0
            try:
                history = self.bridge.get_order_history(settings.SYMBOL)
                for o in history:
                    if o["ticket"] == pos.ticket:
                        broker_open = o["open_time"]
                        broker_close = o["close_time"]
                        break
            except Exception:
                pass

            direction = "BUY" if pos.order_type in ("OP_BUY", "BUY") else "SELL"
            self._record_close(pos.ticket, pnl, strategy.magic, direction)

            if broker_close > 0 and broker_open > 0:
                open_dt = self._mt4_to_local(broker_open)
                close_dt = self._mt4_to_local(broker_close)
                open_time_str = open_dt.strftime('%Y-%m-%d %H:%M:%S')
                close_time_str = close_dt.strftime('%Y-%m-%d %H:%M:%S')
                actual_hold = int(broker_close - broker_open)
            else:
                # 兜底：用本地时间
                close_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                entry_ts = self._entry_times.get(pos.ticket, 0)
                if entry_ts > 0:
                    from config.settings import LOCAL_TZ
                    open_time_str = datetime.fromtimestamp(entry_ts, tz=LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')
                    actual_hold = int(time.time() - entry_ts)
                else:
                    open_time_str, open_ts = self._pos_open_time(pos)
                    actual_hold = max(0, int(time.time() - open_ts)) if open_ts > 0 else round(hold_sec)

            # 组装入场/出场数据
            entry_data = self._entry_signal_data.pop(pos.ticket, {})
            exit_detail = getattr(strategy, "_last_exit_detail", None) or {}
            snapshot = {
                "entry_factors": entry_data.get("entry_factors", {}),
                "indicator_values": entry_data.get("indicator_values", {}),
                "scores": entry_data.get("scores", {}),
                "exit_detail": exit_detail,
            }

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
                open_time=open_time_str,
                close_time=close_time_str,
                hold_seconds=actual_hold,
                exit_reason="strategy_exit",
                indicator_snapshot=json.dumps(snapshot, ensure_ascii=False),
            )
            self._closed_trades.append(record)
            # 通知监督者
            if hasattr(self, 'supervisor'):
                exit_type = exit_detail.get("exit_type", "strategy_exit")
                self.supervisor.on_trade_close(record, exit_type)
            try:
                with open(self._trades_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError:
                pass
            try:
                db.insert_trade(record)
                try:
                    sig = db.get_signal_by_ticket(pos.ticket)
                    if sig and sig.get('id'):
                        db.update_signal_status(sig['id'], {
                            'status': 'closed',
                            'exit_reason': str(exit_detail.get('exit_type', 'strategy_exit')),
                            'exit_pnl': round(pnl, 2),
                        })
                except Exception:
                    pass
            except Exception:
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
                timeout = self._rt('safety_lock_timeout_minutes') * 60
                if time.time() - mtime > timeout:
                    os.remove(SAFETY_LOCK_FILE)
                    logger.info(f"[安全锁] 已自动清除（超过 {self._rt('safety_lock_timeout_minutes')}min）")
                    return False
                return True
        except OSError:
            pass
        return False

    # 纸面交易单策略最大持仓（防止单策略耗尽所有额度）
    _PAPER_MAX_POSITIONS = 10

    def _run_strategy(self, strategy):
        """单个策略的一次 tick — 信号生成 + 开仓"""
        # ── 纸面交易单策略持仓上限检查 ──
        if settings.PAPER_MODE and self._PAPER_MAX_POSITIONS > 0:
            _my_positions = [p for p in self.bridge.get_positions(settings.SYMBOL)
                             if p.magic in self._strategy_magics(strategy)]
            if len(_my_positions) >= self._PAPER_MAX_POSITIONS:
                return

        # ── 每 tick 计算并输出门禁状态（无论有无信号） ──
        try:
            adx_data = strategy.get_adx_data()
        except Exception:
            adx_data = None
        price = strategy.candles[-1].close if strategy.candles else 0
        gate_sell = strategy.calc_gate_state("SELL", price, adx_data)
        gate_buy = strategy.calc_gate_state("BUY", price, adx_data)
        if gate_sell.get("details") or gate_buy.get("details"):
            di = adx_data if adx_data else {}
            log_parts = []
            if di:
                log_parts.append(f"+DI={di.get('pdi',0):.1f} -DI={di.get('ndi',0):.1f} ADX={di.get('adx',0):.1f}")
            gs = gate_sell.get("details", {})
            gb = gate_buy.get("details", {})
            log_parts.append(f"SELL:{gs.get('pos_gate','?')} {gs.get('rally_drop','?')}")
            log_parts.append(f"BUY:{gb.get('pos_gate','?')} {gb.get('rally_drop','?')}")
            logger.info(f"[{strategy.name}] 门禁 | {' '.join(log_parts)}")

        # 获取该策略的持仓（含 legacy magic，桥接查询 + 本地跟踪双重校验防漏）
        positions = self.bridge.get_positions(settings.SYMBOL)
        my_positions = [p for p in positions if p.magic in self._strategy_magics(strategy)]
        n_bridge = len(my_positions)
        n_local = self._known_position_count.get(strategy.magic, 0)
        n_total = max(n_bridge, n_local)  # 取较大值防止桥接漏查
        n_longs = sum(1 for p in my_positions if p.order_type in ("OP_BUY", "BUY"))
        n_shorts = sum(1 for p in my_positions if p.order_type in ("OP_SELL", "SELL"))
        logger.info(f"[{strategy.name}] 持仓: {n_total} (多:{n_longs} 空:{n_shorts})")

        if n_bridge != n_local:
            logger.warning(f"[{strategy.name}] 持仓不一致: 桥接={n_bridge} 本地={n_local}，取较大值={n_total}")

        # 纸面交易不限仓，有多少信号开多少
        if not settings.PAPER_MODE:
            if n_total >= strategy.max_positions:
                return  # 已达上限

            # 已有持仓则不加仓
            if n_total > 0:
                return

        # 生成信号
        signal = strategy.on_tick()
        if not signal:
            return

        signal_dir = "BUY" if "BUY" in signal else "SELL"

        # ── BB扩张 + MFI方向拦截（纸面测试用） ──
        try:
            _bwr = strategy.get_indicator("bb_width_ratio")
            _mfi = strategy.get_indicator("mfi")
            _mfi_dir = strategy.get_indicator("mfi_direction")
            if _bwr and _bwr > 1.2 and _mfi is not None and _mfi_dir:
                if signal_dir == "SELL" and _mfi_dir in ("up", "flat"):
                    logger.info(f"[{strategy.name}] BB扩张+MFI上升({_mfi:.0f})，禁做空")
                    return
                if signal_dir == "BUY" and _mfi_dir in ("down", "flat"):
                    logger.info(f"[{strategy.name}] BB扩张+MFI下降({_mfi:.0f})，禁做多")
                    return
        except Exception:
            pass

        # ── 门禁拦截（使用顶部已计算的门禁数据） ──
        gate = gate_sell if signal_dir == "SELL" else gate_buy
        if gate["blocked"]:
            logger.info(f"[{strategy.name}] 门禁拦截 {signal_dir}: {gate['reason']}")
            return

        # 止盈冷却检查：盈利平仓后 N 小时内不再开同向单
        cool = self._profit_exit_cooldown.get(strategy.magic, {})
        if signal_dir in cool:
            elapsed = time.time() - cool[signal_dir]
            cooldown_sec = self._rt('profit_exit_cooldown_hours') * 3600
            if elapsed < cooldown_sec:
                remain_h = (cooldown_sec - elapsed) / 3600
                logger.info(f"[{strategy.name}] {signal_dir} 止盈冷却中（剩余 {remain_h:.1f}h），跳过开仓")
                return
            else:
                cool.pop(signal_dir, None)

        logger.info(f"[{strategy.name}] 收到信号: {signal}")

        # ---- 全局方向过滤器（优先级最高） ----
        dir_filter = getattr(settings, 'GLOBAL_DIRECTION_FILTER', 'BOTH')
        if dir_filter == 'SELL_ONLY' and signal_dir == 'BUY':
            logger.info(f"[方向过滤器] {dir_filter} 模式，跳过 {signal_dir} 信号 ({strategy.name})")
            return
        if dir_filter == 'BUY_ONLY' and signal_dir == 'SELL':
            logger.info(f"[方向过滤器] {dir_filter} 模式，跳过 {signal_dir} 信号 ({strategy.name})")
            return

        # ---- MTF 共振方向门禁检查 ----
        allowed = self._mtf_resonance_allowed(signal_dir)
        if allowed is not None and allowed not in ("BOTH", signal_dir):
            logger.info(f"[MTF协调器] 方向限制: 当前仅允许{allowed}，跳过 {signal_dir}")
            return

        # 先写入信号记录（status=pending），再执行开仓
        signal_id = 0
        last_sig = getattr(strategy, "_last_signal", None)
        if last_sig and last_sig.get("signal"):
            try:
                import json as _json
                sig_record = {
                    "strategy": strategy.name, "magic": strategy.magic,
                    "timeframe": strategy.timeframe,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "signal": last_sig.get("signal"),
                    "score_long": last_sig.get("score_long", 0),
                    "score_short": last_sig.get("score_short", 0),
                    "threshold": getattr(strategy, "score_threshold", 0),
                    "factors_long": _json.dumps(last_sig.get("factors_long", []), ensure_ascii=False),
                    "factors_short": _json.dumps(last_sig.get("factors_short", []), ensure_ascii=False),
                    "indicator_values": _json.dumps(last_sig.get("indicator_values", {}), ensure_ascii=False),
                    "confidence": last_sig.get("confidence"),
                    "status": "pending",
                }
                signal_id = db.insert_signal(sig_record)
            except Exception:
                pass

        # 执行开仓
        if signal_id > 0 and self._athlete:
            # 提交门票给运动员 — 带完整入场条件
            last_sig = getattr(strategy, '_last_signal', {})
            if last_sig and last_sig.get("signal"):
                direction = last_sig["signal"]
                entry_info = {
                    "strategy": strategy.name,
                    "magic": strategy.magic,
                    "timeframe": strategy.timeframe,
                    "direction": direction,
                    "indicator_values": last_sig.get("indicator_values", {}),
                    "score_long": last_sig.get("score_long", 0),
                    "score_short": last_sig.get("score_short", 0),
                    "factors_long": last_sig.get("factors_long", []),
                    "factors_short": last_sig.get("factors_short", []),
                    "entry_price": 0, "lot_size": self._rt('lot_size') or 0.01,
                    "sl": 0, "tp": 0,
                }
                # 计算 SL/TP
                bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
                entry_price = ask if direction == "BUY" else bid
                try:
                    if direction == "BUY":
                        sl, tp = strategy.get_dynamic_sl_tp(OrderType.BUY, entry_price)
                    else:
                        sl, tp = strategy.get_dynamic_sl_tp(OrderType.SELL, entry_price)
                    entry_info["sl"] = sl
                    entry_info["tp"] = tp
                except Exception:
                    sl_pips = self._rt('stop_loss_pips') or 300
                    tp_pips = self._rt('take_profit_pips') or 600
                    if direction == "BUY":
                        entry_info["sl"] = entry_price - sl_pips * 0.01 * 10
                        entry_info["tp"] = entry_price + tp_pips * 0.01 * 10
                    else:
                        entry_info["sl"] = entry_price + sl_pips * 0.01 * 10
                        entry_info["tp"] = entry_price - tp_pips * 0.01 * 10
                entry_info["entry_price"] = entry_price
                self._athlete.submit(signal_id, direction, entry_info)
                # ★ 提交后立即处理开仓成功回调 ★
                self._handle_athlete_opened()
        else:
            # 回退：旧模式直接开仓
            ticket = 0
            if signal == "信号: BUY":
                ticket = self._execute_buy(strategy, signal_id)
                if strategy.double_first and ticket:
                    self._execute_buy(strategy, 0)
            elif signal == "信号: SELL":
                ticket = self._execute_sell(strategy, signal_id)
                if strategy.double_first and ticket:
                    self._execute_sell(strategy, 0)

            # 更新信号状态
            if signal_id > 0:
                if ticket:  # ticket 可能是 str 或 int，非空/非0 即为成功
                    db.update_signal_status(signal_id, {"status": "opened", "ticket": ticket})
                else:
                    db.update_signal_status(signal_id, {"status": "voided", "void_reason": "订单发送失败"})

    def _execute_buy(self, strategy, signal_id=0):
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        if hasattr(strategy, 'get_dynamic_sl_tp'):
            sl, tp = strategy.get_dynamic_sl_tp(OrderType.BUY, ask)
            if sl is None or tp is None:
                sl = ask - self._rt('stop_loss_pips') * 0.01
                tp = ask + self._rt('take_profit_pips') * 0.01
        else:
            sl = ask - self._rt('stop_loss_pips') * 0.01
            tp = ask + self._rt('take_profit_pips') * 0.01

        ticket = self.bridge.open_order(
            symbol=settings.SYMBOL,
            order_type=OrderType.BUY,
            volume=self._rt('lot_size'),
            price=ask,
            sl=sl,
            tp=tp,
            comment=strategy.name,
            magic=strategy.magic,
        )
        if ticket:
            self._known_position_count[strategy.magic] = self._known_position_count.get(strategy.magic, 0) + 1
            logger.info(f"[{strategy.name}] 开多仓 Magic={strategy.magic} "
                        f"{self._rt('lot_size')}手 @ {ask:.2f} SL={sl:.2f} TP={tp:.2f} Ticket={ticket}")
            self._entry_times[ticket] = time.time()
            last_sig = getattr(strategy, "_last_signal", None) or {}
            self._entry_signal_data[ticket] = {
                "entry_factors": {
                    "long": last_sig.get("factors_long", []),
                    "short": last_sig.get("factors_short", []),
                },
                "indicator_values": last_sig.get("indicator_values", {}),
                "scores": {"long": last_sig.get("score_long", 0), "short": last_sig.get("score_short", 0)},
            }
            if hasattr(strategy, 'mark_extreme_entry'):
                strategy.mark_extreme_entry(ticket)
            # 通知监督者
            if hasattr(self, 'supervisor'):
                direction = "BUY"
                ed = self._entry_signal_data.get(ticket, {})
                self.supervisor.on_trade_open(
                    ticket=ticket, strategy=strategy.name,
                    direction=direction, price=ask,
                    magic=strategy.magic,
                    entry_data={
                        "entry_factors": ed.get("entry_factors", {}),
                        "indicator_values": ed.get("indicator_values", {}),
                        "scores": ed.get("scores", {}),
                    },
                )
        return ticket or 0

    def _execute_sell(self, strategy, signal_id=0):
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        if hasattr(strategy, 'get_dynamic_sl_tp'):
            sl, tp = strategy.get_dynamic_sl_tp(OrderType.SELL, bid)
            if sl is None or tp is None:
                sl = bid + self._rt('stop_loss_pips') * 0.01
                tp = bid - self._rt('take_profit_pips') * 0.01
        else:
            sl = bid + self._rt('stop_loss_pips') * 0.01
            tp = bid - self._rt('take_profit_pips') * 0.01

        ticket = self.bridge.open_order(
            symbol=settings.SYMBOL,
            order_type=OrderType.SELL,
            volume=self._rt('lot_size'),
            price=bid,
            sl=sl,
            tp=tp,
            comment=strategy.name,
            magic=strategy.magic,
        )
        if ticket:
            self._known_position_count[strategy.magic] = self._known_position_count.get(strategy.magic, 0) + 1
            logger.info(f"[{strategy.name}] 开空仓 Magic={strategy.magic} "
                        f"{self._rt('lot_size')}手 @ {bid:.2f} SL={sl:.2f} TP={tp:.2f} Ticket={ticket}")
            self._entry_times[ticket] = time.time()
            last_sig = getattr(strategy, "_last_signal", None) or {}
            self._entry_signal_data[ticket] = {
                "entry_factors": {
                    "long": last_sig.get("factors_long", []),
                    "short": last_sig.get("factors_short", []),
                },
                "indicator_values": last_sig.get("indicator_values", {}),
                "scores": {"long": last_sig.get("score_long", 0), "short": last_sig.get("score_short", 0)},
            }
            if hasattr(strategy, 'mark_extreme_entry'):
                strategy.mark_extreme_entry(ticket)
            # 通知监督者
            if hasattr(self, 'supervisor'):
                direction = "SELL"
                ed = self._entry_signal_data.get(ticket, {})
                self.supervisor.on_trade_open(
                    ticket=ticket, strategy=strategy.name,
                    direction=direction, price=bid,
                    magic=strategy.magic,
                    entry_data={
                        "entry_factors": ed.get("entry_factors", {}),
                        "indicator_values": ed.get("indicator_values", {}),
                        "scores": ed.get("scores", {}),
                    },
                )
        return ticket or 0

    def _get_balance(self) -> float:
        info = self.bridge.get_account_info()
        return info.balance if info else 0.0

    def _get_equity(self) -> float:
        info = self.bridge.get_account_info()
        return info.equity if info else 0.0

    def _handle_news_risk(self, snapshot: list):
        """新闻事件风控：强平窗口平所有持仓"""
        if self.news_filter.is_in_force_close():
            logger.warning("[新闻风控] 强制平仓窗口 (事件前15min)，平所有持仓")
            for strategy in snapshot:
                self._close_strategy_positions(strategy, "news_force_close")

    def _close_strategy_positions(self, strategy, reason: str):
        """平掉某个策略的所有持仓（含 legacy magic），记录指定出场原因"""
        positions = self.bridge.get_positions(settings.SYMBOL)
        my_positions = [p for p in positions if p.magic in self._strategy_magics(strategy)]
        if not my_positions:
            return
        bid, ask = self.bridge.get_tick_price(settings.SYMBOL)
        for pos in my_positions:
            entry = pos.open_price
            if pos.order_type in ("OP_BUY", "BUY"):
                pnl = (bid - entry) * self._rt('lot_size') * 100
                exit_price = bid
            else:
                pnl = (entry - ask) * self._rt('lot_size') * 100
                exit_price = ask
            logger.warning(
                f"[新闻风控] 强制平仓 Ticket={pos.ticket} {pos.order_type} "
                f"入场={entry:.2f} 盈亏=${pnl:.2f} 原因={reason}"
            )
            self.bridge.close_order(pos.ticket)

            # 从 MT4 历史成交获取开平仓时间
            broker_open = 0
            broker_close = 0
            try:
                history = self.bridge.get_order_history(settings.SYMBOL)
                for o in history:
                    if o["ticket"] == pos.ticket:
                        broker_open = o["open_time"]
                        broker_close = o["close_time"]
                        break
            except Exception:
                pass

            direction = "BUY" if pos.order_type in ("OP_BUY", "BUY") else "SELL"
            self._record_close(pos.ticket, pnl, strategy.magic, direction)

            if broker_close > 0 and broker_open > 0:
                open_dt = self._mt4_to_local(broker_open)
                close_dt = self._mt4_to_local(broker_close)
                open_time_str = open_dt.strftime('%Y-%m-%d %H:%M:%S')
                close_time_str = close_dt.strftime('%Y-%m-%d %H:%M:%S')
                hold_sec = int(broker_close - broker_open)
            else:
                close_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                entry_ts = self._entry_times.get(pos.ticket, 0)
                if entry_ts > 0:
                    from config.settings import LOCAL_TZ
                    open_time_str = datetime.fromtimestamp(entry_ts, tz=LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')
                    hold_sec = int(time.time() - entry_ts)
                else:
                    open_time_str, open_ts = self._pos_open_time(pos)
                    hold_sec = max(0, int(time.time() - open_ts)) if open_ts > 0 else 0

            entry_data = self._entry_signal_data.pop(pos.ticket, {})
            snapshot = {
                "entry_factors": entry_data.get("entry_factors", {}),
                "indicator_values": entry_data.get("indicator_values", {}),
                "scores": entry_data.get("scores", {}),
                "exit_detail": {"exit_type": reason},
            }

            record = dict(
                ticket=pos.ticket, symbol=pos.symbol,
                order_type=pos.order_type, volume=pos.volume,
                entry_price=entry, exit_price=exit_price,
                pnl=round(pnl, 2), stop_loss=pos.stop_loss,
                take_profit=pos.take_profit, swap=pos.swap,
                commission=pos.commission, magic=pos.magic,
                strategy=strategy.name, open_time=open_time_str,
                close_time=close_time_str, hold_seconds=hold_sec,
                exit_reason=reason,
                indicator_snapshot=json.dumps(snapshot, ensure_ascii=False),
            )
            self._closed_trades.append(record)
            # 通知监督者
            if hasattr(self, 'supervisor'):
                self.supervisor.on_trade_close(record, reason)
            try:
                with open(self._trades_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError:
                pass
            try:
                db.insert_trade(record)
            except Exception:
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

    def _check_news_bias_block(self) -> bool:
        """检查 News-Bias 方向阻塞"""
        try:
            if not self._rt('news_bias_enabled'):
                return False

            if not hasattr(self.news_filter, 'get_current_bias'):
                return False
            bias = self.news_filter.get_current_bias()
            if not bias:
                return False

            bearish = self._rt('block_long_when_bias_bearish')
            bullish = self._rt('block_short_when_bias_bullish')

            # 从 RuntimeConfig 读取 DI 差值门限（0=关闭绕过）
            _di_gap_threshold = 0
            try:
                _rc = self._config_service.get_coordinator_config()
                _di_gap_threshold = _rc.get('news_bias_di_gap', 0) or 0
            except Exception:
                pass

            # M30 DI 差值判断：M30 |+DI - -DI| < 阈值时绕过新闻阻塞
            _m30_gap = None
            if _di_gap_threshold > 0:
                for _s in getattr(self, 'strategies', []) or []:
                    if getattr(_s, 'timeframe', '') == 'M30':
                        _ax = _s.get_adx_data()
                        if _ax and 'pdi' in _ax and 'ndi' in _ax:
                            _m30_gap = abs(_ax['pdi'] - _ax['ndi'])
                            break

            if bearish and bias.get('overall') == 'BEARISH':
                if _m30_gap is not None and _m30_gap < _di_gap_threshold:
                    logger.info(f"[News-Bias] M30 DI差={_m30_gap:.1f} < {_di_gap_threshold}，市场均衡，跳过看跌阻塞")
                else:
                    logger.info("[News-Bias] 看跌 → 阻止开多")
                    return True

            if bullish and bias.get('overall') == 'BULLISH':
                if _m30_gap is not None and _m30_gap < _di_gap_threshold:
                    logger.info(f"[News-Bias] M30 DI差={_m30_gap:.1f} < {_di_gap_threshold}，市场均衡，跳过看涨阻塞")
                else:
                    logger.info("[News-Bias] 看涨 → 阻止开空")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"[News-Bias] 方向阻塞检查异常: {e}")
            return False

    def _sync_market_data(self):
        """周期性同步 K 线数据到 SQLite（含交易终端展示周期）"""
        now = time.time()
        if now - self._last_data_sync < self._data_sync_interval:
            return
        self._last_data_sync = now

        active_tfs = set()
        with self._strategies_lock:
            for s in self.strategies:
                active_tfs.add(s.timeframe)
        # 协调器反向止盈需要的短周期
        coord = self._get_coordinator()
        if coord.get("m15_reverse_tp_enabled", False):
            active_tfs.add("M15")
        if coord.get("m5_reverse_tp_enabled", False):
            active_tfs.add("M5")
        # 交易终端展示需要的周期（确保 DB 中有数据，避免不同周期显示相同的 K 线图）
        DISPLAY_TFS = {"M5", "M15", "H4", "D1", "W1"}
        active_tfs.update(DISPLAY_TFS)
        if not active_tfs:
            return

        logger.info(f"[数据同步] 开始增量同步周期: {sorted(active_tfs)}")
        all_empty = True
        # 使用 MT4 服务器时间计算缺口
        mt4_now = int(time.time()) + int(self._mt4_offset)
        for tf in sorted(active_tfs):
            try:
                n = download_timeframe(self.bridge, tf, settings.SYMBOL, now_ts=mt4_now)
                if n > 0:
                    logger.info(f"[数据同步] {tf} 写入 {n} 条")
                    all_empty = False
            except Exception as e:
                logger.warning(f"[数据同步] {tf} 失败: {e}")
        # 如果所有周期都未写入任何数据，检查数据库是否真为空
        if all_empty:
            try:
                stats = db.get_db_stats()
                if not stats:
                    logger.error(f"[数据同步] 所有周期均未写入数据，数据库可能为空或未初始化")
                else:
                    logger.info(f"[数据同步] 完成，已有数据: {list(stats.keys())}")
            except Exception as e:
                logger.error(f"[数据同步] 数据库异常: {e}")
        else:
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
            strategy_magics = set()
            for s in strategies_snapshot:
                strategy_magics.update(self._strategy_magics(s))

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
            my_pos = [p for p in all_positions if p.magic in self._strategy_magics(s)]
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
