"""
策略基类 - 所有策略继承此类
"""

import abc
import logging
from typing import Optional

from core.bridge import MT4BridgeBase, Candle, Position, OrderType
import config.settings as _settings
from core.runtime_config import RuntimeConfig as _RuntimeConfig

logger = logging.getLogger(__name__)


class BaseStrategy(abc.ABC):
    """策略基类"""

    name = "base"

    # 旧版 magic 列表：引擎在追踪持仓时会同时识别这些 magic，视为本策略的单子
    # 用于版本升级后自动接管旧 magic 的持仓，避免产生孤儿单
    legacy_magics: list[int] = []

    def __init__(self, bridge: MT4BridgeBase, magic: int = 0, timeframe: str = ""):
        self.bridge = bridge
        self.symbol = _settings.SYMBOL
        self.magic = magic or _settings.MAGIC_NUMBER
        self.timeframe = timeframe or _settings.TIMEFRAME
        self.candles: list[Candle] = []
        self._trail_sl: dict[int, float] = {}
        # 最近一次信号详情（供引擎写入 DB）
        self._last_signal: Optional[dict] = None
        self._m30_candles: list[Candle] = []

        # K-line filter parameters (from RuntimeConfig → runtime_config.json, hot-reloadable)
        _coord = _RuntimeConfig().get_coordinator_config()
        self.position_gate_enabled: bool = _coord.get('position_gate_enabled', True)
        self.position_gate_lookback: int = _coord.get('position_gate_lookback', 60)
        self.position_gate_bottom: float = _coord.get('position_gate_bottom', 0.10)
        self.position_gate_top: float = _coord.get('position_gate_top', 0.90)
        self.rally_drop_enabled: bool = _coord.get('rally_drop_enabled', True)
        self.rally_drop_lookback: int = _coord.get('rally_drop_lookback', 30)
        self.rally_drop_threshold: float = _coord.get('rally_drop_threshold', 1.5)
        self.profit_drawdown_enabled: bool = _coord.get('profit_drawdown_enabled', True)
        self.profit_drawdown_pct: float = _coord.get('profit_drawdown_pct', 0.25)

        # News-Bias 阻塞开关（每次信号动态读取 config_service，覆盖优先）
        self.block_long_when_bias_bearish: bool = _settings.BLOCK_LONG_WHEN_BIAS_BEARISH
        self.block_short_when_bias_bullish: bool = _settings.BLOCK_SHORT_WHEN_BIAS_BULLISH

    @property
    def all_magics(self) -> set[int]:
        """返回本策略所有 magic 号（主magic + 旧版legacy magic）"""
        return {self.magic} | set(self.legacy_magics)

    def refresh_data(self, count: int = 200):
        """刷新K线数据，转为时间顺序（旧→新）"""
        raw = self.bridge.get_candles(self.symbol, self.timeframe, count)
        self.candles = list(reversed(raw))

    def get_close_prices(self) -> list[float]:
        """获取收盘价序列"""
        return [c.close for c in self.candles]

    def _apply_kline_filters(self, result: tuple):
        """统一 K 线过滤器：位置门禁 + 急跌急涨惩罚。
        在 generate_signal() 之后调用，直接 nullify 信号（不操作评分过程）。"""
        signal, score_long, score_short, factors_long, factors_short, iv = result[:6]
        extra = result[6:] if len(result) > 6 else ()
        candles = self.candles
        if not candles:
            return result

        close = candles[-1].close

        # ── ① 位置门禁 ──
        if self.position_gate_enabled:
            lookback = min(self.position_gate_lookback, len(candles))
            if lookback >= 2:
                hi = max(c.high for c in candles[-lookback:])
                lo = min(c.low for c in candles[-lookback:])
                pos = (close - lo) / (hi - lo) if hi > lo else 0.5

                if signal == OrderType.SELL and pos < self.position_gate_bottom:
                    signal = None
                    score_short = 0
                    factors_short.append(f"BOTTOM-GATE({pos:.1%})")
                    logger.info(f"[{self.name}] 位置门禁: 区间底部 {pos:.1%}，禁SELL")
                elif signal == OrderType.BUY and pos > self.position_gate_top:
                    signal = None
                    score_long = 0
                    factors_long.append(f"TOP-GATE({pos:.1%})")
                    logger.info(f"[{self.name}] 位置门禁: 区间顶部 {pos:.1%}，禁BUY")

        # ── ② 急跌急涨惩罚（使用 M30 K 线） ──
        if self.rally_drop_enabled:
            self._load_m30_data()
            if self._m30_candles:
                rd_lookback = min(self.rally_drop_lookback, len(self._m30_candles))
                if rd_lookback >= 2:
                    m30_close = self._m30_candles[-1].close
                    rd_hi = max(c.high for c in self._m30_candles[-rd_lookback:])
                    rd_lo = min(c.low for c in self._m30_candles[-rd_lookback:])
                    drop_pct = (rd_hi - m30_close) / rd_hi * 100
                    rally_pct = (m30_close - rd_lo) / rd_lo * 100

                    if drop_pct > self.rally_drop_threshold and signal == OrderType.SELL:
                        signal = None
                        score_short = 0
                        factors_short.append(f"DROP-{drop_pct:.1f}%")
                        logger.info(f"[{self.name}] 急跌惩罚: 高点回落 {drop_pct:.1f}%，禁SELL")
                    elif rally_pct > self.rally_drop_threshold and signal == OrderType.BUY:
                        signal = None
                        score_long = 0
                        factors_long.append(f"RALLY-{rally_pct:.1f}%")
                        logger.info(f"[{self.name}] 急涨惩罚: 低点上涨 {rally_pct:.1f}%，禁BUY")

        # ── ③ News-Bias 阻塞（ADX 门禁在 bias_state 层面处理） ──
        # 每次信号动态读取 RuntimeConfig（覆盖优先），所以 UI 切换开关立即生效
        try:
            _cfg = _RuntimeConfig()
            _block_long = _cfg.get("block_long_when_bias_bearish")
            _block_short = _cfg.get("block_short_when_bias_bullish")
        except Exception:
            _block_long = self.block_long_when_bias_bearish
            _block_short = self.block_short_when_bias_bullish

        if signal is not None and (_block_long or _block_short):
            try:
                from core import bias_state
                bias_dir = bias_state.get()
            except Exception:
                bias_dir = None
            if bias_dir == "bearish" and _block_long and signal == OrderType.BUY:
                signal = None
                score_long = 0
                factors_long.append("BIAS-BEAR-BLOCK")
                logger.info(f"[{self.name}] News-Bias 阻塞: bias=bearish，禁BUY")
            elif bias_dir == "bullish" and _block_short and signal == OrderType.SELL:
                signal = None
                score_short = 0
                factors_short.append("BIAS-BULL-BLOCK")
                logger.info(f"[{self.name}] News-Bias 阻塞: bias=bullish，禁SELL")
        return (signal, score_long, score_short, factors_long, factors_short, iv) + extra

    def _load_m30_data(self):
        """加载 M30 K 线数据从本地 SQLite（供 H1 策略做急跌急涨检测）"""
        try:
            from data.database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM ohlcv WHERE timeframe='M30' ORDER BY timestamp"
            ).fetchall()
            conn.close()
            self._m30_candles = [
                Candle(time=str(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"[{self.name}] M30 data load failed: {e}")
            self._m30_candles = []

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
        # 统一 K 线过滤器（位置门禁 + 急跌急涨惩罚）
        if isinstance(result, tuple):
            result = self._apply_kline_filters(result)
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

        # 热重载 K 线过滤器参数（从 RuntimeConfig 读取，dashboard 保存优先）
        _coord = _RuntimeConfig().get_coordinator_config()
        self.position_gate_enabled = _coord.get('position_gate_enabled', True)
        self.position_gate_lookback = _coord.get('position_gate_lookback', 60)
        self.position_gate_bottom = _coord.get('position_gate_bottom', 0.10)
        self.position_gate_top = _coord.get('position_gate_top', 0.90)
        self.rally_drop_enabled = _coord.get('rally_drop_enabled', True)
        self.rally_drop_lookback = _coord.get('rally_drop_lookback', 30)
        self.rally_drop_threshold = _coord.get('rally_drop_threshold', 1.5)
        self.profit_drawdown_enabled = _coord.get('profit_drawdown_enabled', True)
        self.profit_drawdown_pct = _coord.get('profit_drawdown_pct', 0.25)

    def filter_positions(self, positions: list[Position]) -> dict:
        """统计当前品种的多空持仓"""
        longs = [p for p in positions if p.order_type in ("OP_BUY", "BUY")]
        shorts = [p for p in positions if p.order_type in ("OP_SELL", "SELL")]
        return {"longs": longs, "shorts": shorts, "total": len(positions)}
