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
        """用实时 tick 价 + 数据工厂最新缓存指标，重新验证入场条件。

        策略出的门票只是候选，运动员用最新数据独立判断。
        """
        direction = item["direction"]
        signal = item["signal"]
        tf = signal.get("timeframe", "M30")
        factors = signal.get("factors_long", []) if direction == "BUY" else signal.get("factors_short", [])
        old_iv = signal.get("indicator_values", {})

        # 从工厂拿最新预计算指标（比信号时新了 0.3~3 秒）
        latest = get_cache(tf)
        if not latest:
            latest = old_iv  # 工厂不干活时回退

        tick_price = tick["ask"] if direction == "BUY" else tick["bid"]
        bb = latest.get("bb") or old_iv.get("bb") or {}
        bb_lower = bb.get("lower", 0)
        bb_upper = bb.get("upper", 0)
        latest_rsi = latest.get("rsi", 50)
        latest_mfi = latest.get("mfi", 50)
        latest_adx = latest.get("adx", 20)
        latest_pdi = latest.get("pdi", 15)
        latest_ndi = latest.get("ndi", 15)

        # ── 基础校验：spread 正常 ──
        if tick.get("ask", 0) <= 0 or tick.get("bid", 0) <= 0:
            return False
        if tick["ask"] <= tick["bid"]:
            return False

        # ── 方向校验：按入场因子逐条验证 ──
        if direction == "BUY":
            # BB下轨: tick 价不能跑离下轨超过 0.5%
            if bb_lower and tick_price > bb_lower * 1.005:
                return False
            # RSI: 不能反弹超过 45（超卖区已失效）
            for f in factors:
                if f.startswith("RSI-") and latest_rsi > 45:
                    return False
                if f.startswith("MFI-") and latest_mfi > 45:
                    return False
            # DI方向: +DI 必须仍 > -DI
            for f in factors:
                if f.startswith("DI+"):
                    if latest_pdi <= latest_ndi:
                        return False
                    break
            # trend: MA20必须仍为UP
            for f in factors:
                if f == "MA20-UP" and latest.get("trend") != "UP":
                    return False
                if f == "M30-UP" and latest.get("trend") != "UP":
                    return False
        else:  # SELL
            # BB上轨: tick 价不能跌回上轨内 0.5%
            if bb_upper and tick_price < bb_upper * 0.995:
                return False
            # RSI: 不能跌回 55 以下
            for f in factors:
                if f.startswith("RSI-") and latest_rsi < 55:
                    return False
                if f.startswith("MFI-") and latest_mfi < 55:
                    return False
            # DI方向: -DI 必须仍 > +DI
            for f in factors:
                if f.startswith("DI-") or f.startswith("DI"):
                    if latest_ndi <= latest_pdi:
                        return False
                    break
            # trend: MA20必须仍为DOWN
            for f in factors:
                if f == "MA20-DN" and latest.get("trend") != "DOWN":
                    return False
                if f == "M30-DN" and latest.get("trend") != "DOWN":
                    return False

        # ── ADX 崩溃校验: 趋势突然消失则放弃 ──
        old_adx = old_iv.get("adx", 20)
        if old_adx > 25 and latest_adx < 18:
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
