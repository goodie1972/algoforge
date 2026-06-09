"""
策略基类 - 所有策略继承此类
"""

import abc
import logging
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, Position, OrderType
import config.settings as _settings

logger = logging.getLogger(__name__)


class BaseStrategy(abc.ABC):
    """策略基类"""

    name = "base"

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        self.bridge = bridge
        self.symbol = _settings.SYMBOL
        self.magic = magic or _settings.MAGIC_NUMBER
        self.timeframe = timeframe or _settings.TIMEFRAME
        self.candles: list[Candle] = []
        self._trail_sl: dict[int, float] = {}
        # 最近一次信号详情（供引擎写入 DB）
        self._last_signal: Optional[dict] = None

    def refresh_data(self, count: int = 200):
        """刷新K线数据，转为时间顺序（旧→新）"""
        raw = self.bridge.get_candles(self.symbol, self.timeframe, count)
        self.candles = list(reversed(raw))

    def get_close_prices(self) -> list[float]:
        """获取收盘价序列"""
        return [c.close for c in self.candles]

    @abc.abstractmethod
    def generate_signal(self):
        """
        生成交易信号。
        返回: tuple[Optional[OrderType], int, int, list, list, dict]
          - signal: BUY / SELL / None
          - score_long: 多头评分
          - score_short: 空头评分
          - factors_long: 多头因子列表
          - factors_short: 空头因子列表
          - indicator_values: 指标值字典（可 JSON 序列化）
        """
        ...

    def on_tick(self) -> Optional[str]:
        """
        主循环调用：检查信号并返回操作描述
        返回: 操作描述字符串，或 None
        """
        self.refresh_data()
        if len(self.candles) < 10:
            logger.warning(f"[{self.name}] K线数据不足: {len(self.candles)}")
            return None

        result = self.generate_signal()
        signal = result[0] if isinstance(result, tuple) else result

        # 存储信号详情（供引擎写入数据库）
        if isinstance(result, tuple):
            self._last_signal = {
                "signal": signal.value if signal else None,
                "score_long": result[1],
                "score_short": result[2],
                "factors_long": result[3],
                "factors_short": result[4],
                "indicator_values": result[5],
            }
            # 如果有额外项（confidence 等）
            if len(result) > 6:
                self._last_signal["confidence"] = result[6]
        else:
            # 向后兼容：旧策略只返回 OrderType
            self._last_signal = {
                "signal": signal.value if signal else None,
                "score_long": 0, "score_short": 0,
                "factors_long": [], "factors_short": [],
                "indicator_values": {},
            }

        if signal:
            return f"信号: {signal.value}"
        return None

    def reload_config(self):
        """热重载配置参数，子类覆盖（不覆盖 magic/timeframe，它们由 STRATEGY_POOL 管理）"""
        self.symbol = _settings.SYMBOL

    def filter_positions(self, positions: list[Position]) -> dict:
        """统计当前品种的多空持仓"""
        longs = [p for p in positions if p.order_type in ("OP_BUY", "BUY")]
        shorts = [p for p in positions if p.order_type in ("OP_SELL", "SELL")]
        return {"longs": longs, "shorts": shorts, "total": len(positions)}
