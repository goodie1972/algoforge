"""
数据工厂 — 三轨架构第1轨
- 独立线程从桥接增量拉取 K 线
- TA-Lib 预计算所有公共指标
- 全局缓存供策略和 Athlete 读取
"""
import logging
import threading
import time
import numpy as np

from core.bridge import Candle

logger = logging.getLogger(__name__)

# 全局缓存
_DATA_CACHE: dict = {}
_CACHE_LOCK = threading.RLock()

# 全局 tick 计数器：DataFactory 每收到一次 tick 报价就 +1
_TICK_COUNTER: int = 0

# DataFactory 健康状态（跨线程只读，线程安全通过 CACHE_LOCK 保障）
_HEALTH: dict = {
    "bridging": False,           # 桥接是否连接成功
    "started_at": 0.0,           # 启动时间戳
    "tfs": {},                   # {tf: {"last_sync": ts, "candles": n, "has_indicators": bool, "ok": bool}}
    "sync_errors": [],           # 最近的同步错误 [{"time": ts, "tf": str, "err": str}]
    "last_tick_time": 0.0,       # 最近一次报价时间
    "tick_count": 0,             # 总报价次数
}

# 限制 sync_errors 长度，防止无限增长
_SYNC_ERRORS_MAX = 20

def get_health() -> dict:
    """获取 DataFactory 健康状态快照（供外部监控/API 调用）"""
    with _CACHE_LOCK:
        return _HEALTH.copy()

def get_cache(timeframe: str) -> dict:
    """策略读取缓存"""
    with _CACHE_LOCK:
        return _DATA_CACHE.get(timeframe, {}).copy()

def get_tick() -> dict:
    """Athlete 读取 tick"""
    with _CACHE_LOCK:
        return _DATA_CACHE.get("tick", {}).copy()

def get_tick_count() -> int:
    """返回当前全局 tick 计数器值（DataFactory 每更新一次报价就 +1）"""
    with _CACHE_LOCK:
        return _TICK_COUNTER


def _get_candle_ts(c):
    """提取 candle 时间戳，优先 int 比较，回退 str"""
    t = getattr(c, 'time', '')
    try:
        return int(t)
    except (ValueError, TypeError):
        return str(t)


def _merge_candles(old: list, new: list, max_len=350) -> list:
    """增量合并K线，去重，保留最近max_len根"""
    if not new:
        return old
    if not old:
        return new[-max_len:]
    if _get_candle_ts(old[-1]) == _get_candle_ts(new[0]):
        merged = old[:-1] + new  # 替换最后一条未闭合K线
    else:
        merged = old + new
    return merged[-max_len:]


def _talib_indicators(candles: list, tf: str) -> dict:
    """精简版：只算 close/trend/bb_width/direction/ratio，其他由 F043 覆盖"""
    import numpy as np
    import talib
    closes = np.array([c.close for c in candles], dtype=float)
    if len(closes) < 30:
        return {}

    result = {}

    # BB(20,2) — 仅用于 bb_width / direction / ratio(SMA3)
    try:
        upper, mid, lower = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2)
        bb_width = float(upper[-1] - lower[-1])
        result["bb_width"] = bb_width
        if len(upper) > 2:
            _prev = float(upper[-2] - lower[-2])
            result["bb_width_direction"] = "up" if bb_width > _prev else ("down" if bb_width < _prev else "flat")
        else:
            result["bb_width_direction"] = "flat"
        # BB 宽度比率：当前 / 过去3根均值（SMA3，更快响应扩张）
        if len(upper) > 4:
            _widths_arr = upper - lower
            _avg3 = float(talib.SMA(_widths_arr, timeperiod=3)[-1])
            result["bb_width_ratio"] = round(bb_width / _avg3, 3) if _avg3 > 0 else 1.0
        else:
            result["bb_width_ratio"] = 1.0
    except Exception:
        pass

    # close + trend（SMA14）
    result["close"] = float(closes[-1])
    try:
        s14_v = float(talib.SMA(closes, timeperiod=14)[-1])
        result["trend"] = "UP" if closes[-1] > s14_v else "DOWN"
    except Exception:
        result["trend"] = "NEUTRAL"

    return result
