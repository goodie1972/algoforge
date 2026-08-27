"""
运动员 — tick 验证层（三轨架构的轨3）
收到门票后最多验证 3 个 tick，任一 tick 通过即开仓，3 次不过就废。
"""
import logging
from core.bridge import MT4BridgeBase, OrderType
from data import database as db
from services.data_factory import get_tick, get_cache

logger = logging.getLogger(__name__)

_MAX_TICKS = 3  # 最多验证 3 个 tick


class Athlete:
    """信号 → 持续 tick 验证 → 开仓"""

    def __init__(self, exec_bridge):
        self._bridge = exec_bridge
        self._pending: list[dict] = []
        self._recently_opened: list[tuple] = []  # (ticket, strategy_name)

    def submit(self, signal_id: int, direction: str, signal: dict, strategy_cls=None):
        """策略员提交候选门票 — 重复的策略+方向不再提交"""
        strategy_name = signal.get("strategy", "")
        for item in self._pending:
            if item["signal"].get("strategy") == strategy_name and item["direction"] == direction:
                logger.debug(f"[Athlete] Duplicate ticket #{signal_id} {direction}, skipped (#{item['signal_id']} already pending)")
                return
        self._pending.append({
            "signal_id": signal_id,
            "direction": direction,
            "signal": signal,
            "ticks_left": _MAX_TICKS,  # 从 _MAX_TICKS 开始
            "strategy_cls": strategy_cls,  # 缓存策略类引用，避免每 tick 重新扫描
        })
        logger.info(f"[Athlete] Received candidate ticket #{signal_id} {direction}, {_MAX_TICKS} ticks remaining")
        # 提交后立即验证一轮
        self.run()

    def run(self):
        """每 tick 执行一次：验证所有 pending 门票（扣 tick 次数）"""
        valid = []
        for item in self._pending:
            item["ticks_left"] -= 1
            if item["ticks_left"] < 0:
                self._void(item, "tick_expired")
                logger.info(f"[Athlete] Ticket #{item['signal_id']} voided (all {_MAX_TICKS} ticks failed)")
                continue
            tick = get_tick()
            if not tick:
                valid.append(item)
                continue
            if self._verify(item, tick):
                self._execute(item, tick)
            else:
                valid.append(item)
        self._pending = valid

    # ═══════════════ 验证 ═══════════════

    def _verify(self, item: dict, tick: dict) -> bool:
        """委托策略自己的 _verify_entry 方法，用最新 tick + 工厂缓存重算。"""
        signal = item["signal"]
        direction = item["direction"]

        if tick.get("ask", 0) <= 0 or tick.get("bid", 0) <= 0:
            return False
        if tick["ask"] <= tick["bid"]:
            return False

        tick_price = tick["ask"] if direction == "BUY" else tick["bid"]
        tf = signal.get("timeframe", "M30")
        latest = get_cache(tf)
        if not latest:
            latest = signal.get("indicator_values", {})

        # 使用缓存的策略类引用，避免每 tick 重新扫描所有策略文件
        cls = item.get("strategy_cls")
        if cls and hasattr(cls, '_verify_entry'):
            try:
                return cls._verify_entry(signal, tick_price, latest, item)
            except TypeError:
                return cls._verify_entry(signal, tick_price, latest)

        # 默认：新策略无需验票，直接通过（有 _verify_entry 的走自定义验证）
        return True

    # ═══════════════ 执行 ═══════════════

    def _execute(self, item: dict, tick: dict):
        """开仓"""
        # 执行前复查：新闻禁售窗口内拒绝开仓（防主循环检查后进入窗口的竞态）
        try:
            from services.news_filter import NewsFilter
            blocked, news_reason = NewsFilter().is_in_blackout()
            if blocked:
                logger.warning(f"[Athlete] News blackout ({news_reason}), reject open #{item['signal_id']} {item['direction']}")
                self._void(item, "news_blackout")
                return
        except Exception as e:
            logger.warning(f"[Athlete] NewsFilter recheck failed: {e}")
        direction = item["direction"]
        order_type = OrderType.BUY if direction == "BUY" else OrderType.SELL
        signal = item["signal"]
        price = tick["ask"] if direction == "BUY" else tick["bid"]
        strategy = signal.get("strategy", "unknown")
        magic = signal.get("magic", 0)
        # 兜底 SL/TP：如果信号没传，用 ATR 硬止损
        _sl = signal.get("sl")
        _tp = signal.get("tp")
        if not _sl or not _tp:
            _atr = signal.get("indicator_values", {}).get("atr", 15)
            _sl = price - _atr * 2 if direction == "BUY" else price + _atr * 2
            _tp = price + _atr * 4 if direction == "BUY" else price - _atr * 4
        try:
            ticket = self._bridge.open_order(
                symbol="XAUUSD",
                order_type=order_type,
                volume=signal.get("lot_size", 0.01),
                price=price,
                sl=_sl,
                tp=_tp,
                magic=magic,
                comment=f"{strategy}_{direction}",
            )
            if ticket:
                db.update_signal_status(item["signal_id"], {"status": "opened", "ticket": ticket})
                logger.info(f"[Athlete] Order opened successfully #{ticket} {direction} @ {price:.2f}")
                self._recently_opened.append((ticket, strategy))
            else:
                self._void(item, "order_failed")
        except Exception as e:
            logger.error(f"[Athlete] Order failed: {e}")
            self._void(item, f"order_error:{e}")

    def _void(self, item: dict, reason: str):
        try:
            db.update_signal_status(item["signal_id"], {"status": "voided", "void_reason": reason})
        except Exception:
            pass
