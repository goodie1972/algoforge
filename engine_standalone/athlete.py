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
        self._max_age = 10.0  # 门票有效期 10 秒

    def submit(self, signal_id: int, direction: str, signal: dict):
        """策略员提交候选门票"""
        self._pending.append({
            "signal_id": signal_id,
            "direction": direction,
            "signal": signal,
            "time": time.time()
        })
        logger.info(f"[运动员] 收到候选门票 #{signal_id} {direction}")

    def run(self):
        """每 tick 执行一次"""
        now = time.time()
        valid = []
        for item in self._pending:
            if now - item["time"] > self._max_age:
                self._void(item, "candidate_timeout")
                logger.info(f"[运动员] 门票 #{item['signal_id']} 过期作废 (>10s)")
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
        """用实时 tick 重新验证关键入场条件

        验证内容：
        - 价格仍然在入场区间内（BB 极值 ±0.5%）
        - 实时 tick 方向与信号方向一致
        """
        direction = item["direction"]
        signal = item["signal"]
        indicators = signal.get("indicator_values", {})
        bb_lower = indicators.get("bb_lower")
        bb_upper = indicators.get("bb_upper")
        rsi = indicators.get("rsi")

        if direction == "BUY":
            if bb_lower and tick["ask"] > bb_lower * 1.005:
                return False
            if rsi and tick.get("bid", 0) > signal.get("entry_price", 0) * 1.003:
                return False
        else:  # SELL
            if bb_upper and tick["bid"] < bb_upper * 0.995:
                return False
            if rsi and tick.get("ask", 99999) < signal.get("entry_price", 99999) * 0.997:
                return False

        if tick.get("ask", 0) <= 0 or tick.get("bid", 0) <= 0:
            return False
        if tick["ask"] <= tick["bid"]:
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
