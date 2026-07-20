"""
运动员 — 三轨架构第3轨
- 策略员提交候选门票
- tick 实时验证后开仓或弃票
- 10 秒过期自动作废
"""
import logging
import time
from typing import Optional

from core.bridge import OrderType
from data import database as db
from services.data_factory import get_tick, get_cache

logger = logging.getLogger(__name__)


class Athlete:
    """信号 → tick 验证 → 开仓"""

    def __init__(self, exec_bridge):
        self._bridge = exec_bridge
        self._pending: list[dict] = []
        self._max_age = 8.0  # 门票有效期 8 秒
        self._recently_opened: list[tuple] = []  # (ticket, strategy_name) 开仓成功队列

    def submit(self, signal_id: int, direction: str, signal: dict):
        """策略员提交候选门票 — 重复的策略+方向不再提交"""
        strategy_name = signal.get("strategy", "")
        for item in self._pending:
            if item["signal"].get("strategy") == strategy_name and item["direction"] == direction:
                logger.debug(f"[运动员] 重复门票 #{signal_id} {direction}，跳过（已有 #{item['signal_id']} 在等待）")
                return
        self._pending.append({
            "signal_id": signal_id,
            "direction": direction,
            "signal": signal,
            "time": time.time(),
        })
        logger.info(f"[运动员] 收到候选门票 #{signal_id} {direction}")

    def run(self):
        """每 tick 执行一次"""
        now = time.time()
        valid = []
        for item in self._pending:
            if now - item["time"] > self._max_age:
                self._void(item, "candidate_timeout")
                logger.info(f"[运动员] 门票 #{item['signal_id']} 过期作废 (>8s)")
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

        # 策略自己有 _verify_entry 就用，没有就走基础 BB 校验
        strategy_name = signal.get("strategy", "")
        from strategies.base import BaseStrategy
        try:
            from strategies.scanner import scan_strategies, clear_cache
            clear_cache()  # 清除扫描器缓存，确保加载最新策略代码
            cls = scan_strategies().get(strategy_name)
            if cls and hasattr(cls, '_verify_entry'):
                try:
                    # v7+ 策略可能需要 item dict 做跨 tick 跟踪
                    return cls._verify_entry(signal, tick_price, latest, item)
                except TypeError:
                    return cls._verify_entry(signal, tick_price, latest)
        except Exception:
            pass

        # 默认 fallback: tick 不能跑出 BB 边界
        bb = latest.get("bb") or signal.get("indicator_values", {}).get("bb") or {}
        if direction == "BUY":
            if bb.get("lower") and tick_price > bb["lower"] * 1.005:
                return False
        else:
            if bb.get("upper") and tick_price < bb["upper"] * 0.995:
                return False
        return True

    def _execute(self, item: dict, tick: dict):
        """开仓"""
        direction = item["direction"]
        order_type = OrderType.BUY if direction == "BUY" else OrderType.SELL
        signal = item["signal"]
        price = tick["ask"] if direction == "BUY" else tick["bid"]
        strategy = signal.get("strategy", "unknown")
        magic = signal.get("magic", 0)
        try:
            ticket = self._bridge.open_order(
                symbol="XAUUSD",
                order_type=order_type,
                volume=signal.get("lot_size", 0.01),
                price=price,
                sl=signal.get("sl", 0),
                tp=signal.get("tp", 0),
                magic=magic,
                comment=f"{strategy}_{direction}",
            )
            if ticket:
                db.update_signal_status(item["signal_id"], {"status": "opened", "ticket": ticket})
                logger.info(f"[运动员] 开仓成功 #{ticket} {direction} @ {price:.2f}")
                # 记录开仓成功的 (ticket, strategy_name)，供引擎回调策略的 mark_extreme_entry
                self._recently_opened.append((ticket, signal.get("strategy", "")))
            else:
                self._void(item, "order_failed")
        except Exception as e:
            logger.error(f"[运动员] 开仓失败: {e}")
            self._void(item, f"order_error:{e}")

    def _void(self, item: dict, reason: str):
        try:
            db.update_signal_status(item["signal_id"], {"status": "voided", "void_reason": reason})
        except Exception:
            pass
