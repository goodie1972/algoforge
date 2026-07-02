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

logger = logging.getLogger(__name__)

# 全局缓存
_DATA_CACHE: dict = {}
_CACHE_LOCK = threading.RLock()

def get_cache(timeframe: str) -> dict:
    """策略读取缓存"""
    with _CACHE_LOCK:
        return _DATA_CACHE.get(timeframe, {}).copy()

def get_tick() -> dict:
    """Athlete 读取 tick"""
    with _CACHE_LOCK:
        return _DATA_CACHE.get("tick", {}).copy()


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
    """用 TA-Lib 一次算完所有公共指标。
    返回 dict: rsi, mfi, bb{upper,mid,lower}, ema_10, ema_20, sma_14, sma_20,
               atr, atr_20, adx, pdi, ndi, macd, stoch_14_3_3, stoch_21_5_3,
               volume_sma_20, trend, h4_trend, atr_list, price_position
    """
    try:
        import talib
    except ImportError:
        logger.warning("[数据工厂] talib 未安装，部分指标跳过")
        return {}

    closes = np.array([c.close for c in candles], dtype=float)
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    vols = np.array([c.volume for c in candles], dtype=float)

    if len(closes) < 30:
        return {}  # 数据不足

    result = {}

    # RSI
    for p in [5, 10, 14]:
        try:
            r = talib.RSI(closes, timeperiod=p)
            key = "rsi" if p == 14 else f"rsi_{p}"
            result[key] = float(r[-1]) if r[-1] == r[-1] else 50.0
        except Exception:
            pass

    # MFI(14)
    try:
        m = talib.MFI(highs, lows, closes, vols, timeperiod=14)
        result["mfi"] = float(m[-1]) if m[-1] == m[-1] else 50.0
    except Exception:
        pass

    # BB(20,2)
    try:
        upper, mid, lower = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2)
        result["bb"] = {
            "upper": float(upper[-1]), "mid": float(mid[-1]), "lower": float(lower[-1])
        }
    except Exception:
        pass

    # EMA
    for p in [9, 21]:
        try:
            e = talib.EMA(closes, timeperiod=p)
            result[f"ema_{p}"] = float(e[-1]) if e[-1] == e[-1] else float(closes[-1])
        except Exception:
                pass

    # SMA
    for p in [14, 20]:
        try:
            s = talib.SMA(closes, timeperiod=p)
            result[f"sma_{p}"] = float(s[-1]) if s[-1] == s[-1] else float(closes[-1])
        except Exception:
                pass

    # ATR(14 和 20)
    try:
        a14 = talib.ATR(highs, lows, closes, timeperiod=14)
        result["atr"] = float(a14[-1]) if a14[-1] == a14[-1] else 0.0
        result["atr_list"] = [float(x) for x in a14.tolist()]
    except Exception:
        pass
    try:
        a20 = talib.ATR(highs, lows, closes, timeperiod=20)
        result["atr_20"] = float(a20[-1]) if a20[-1] == a20[-1] else 0.0
    except Exception:
        pass

    # ADX(14)
    try:
        adx_v = talib.ADX(highs, lows, closes, timeperiod=14)
        result["adx"] = float(adx_v[-1]) if adx_v[-1] == adx_v[-1] else 20.0
        result["pdi"] = float(talib.PLUS_DI(highs, lows, closes, timeperiod=14)[-1])
        result["ndi"] = float(talib.MINUS_DI(highs, lows, closes, timeperiod=14)[-1])
    except Exception:
        pass

    # MACD(12,26,9)
    try:
        macd, sig, hist = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
        result["macd"] = {"macd": float(macd[-1]), "signal": float(sig[-1])}
    except Exception:
        pass

    # Stoch(14,3,3)
    try:
        sk, sd = talib.STOCH(highs, lows, closes, fastk_period=14, slowk_period=3, slowd_period=3)
        result["stoch_14_3_3"] = {"k": float(sk[-1]), "d": float(sd[-1])}
    except Exception:
        pass

    # Stoch(21,5,3)
    try:
        sk2, sd2 = talib.STOCH(highs, lows, closes, fastk_period=21, slowk_period=5, slowd_period=3)
        result["stoch_21_5_3"] = {"k": float(sk2[-1]), "d": float(sd2[-1])}
    except Exception:
        pass

    # 成交量和价格位置
    try:
        result["volume_sma_20"] = float(talib.SMA(vols, timeperiod=20)[-1])
    except Exception:
        pass
    result["close"] = float(closes[-1])
    result["trend"] = "UP" if closes[-1] > result.get("sma_14", closes[-1]) else "DOWN"

    # SMA 50 for H4 (must compute before h4_trend check)
    try:
        s50 = talib.SMA(closes, timeperiod=50)
        result["sma_50"] = float(s50[-1]) if s50[-1] == s50[-1] else float(closes[-1])
    except Exception:
        pass

    if tf == "H4":
        result["h4_trend"] = "UP" if closes[-1] > result.get("sma_50", closes[-1]) else "DOWN"

    # 价格位置
    try:
        hi20 = max(highs[-20:])
        lo20 = min(lows[-20:])
        result["price_position"] = float((closes[-1] - lo20) / (hi20 - lo20)) if hi20 > lo20 else 0.5
    except Exception:
        pass

    return result


class DataFactory:
    """数据工厂 — 独立线程维护所有周期缓存"""

    def __init__(self, bridge):
        self._bridge = bridge
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="data-factory")
        self._thread.start()
        logger.info("[数据工厂] 已启动")

    def stop(self):
        self._running = False
        logger.info("[数据工厂] 已停止")

    def _run(self):
        logger.info("[数据工厂] 开始首次全量加载...")
        self._initial_load()
        logger.info("[数据工厂] 首次加载完成，进入增量循环")
        while self._running:
            for tf in ["M15", "M30", "H1", "H4"]:
                self._sync_tf(tf, self._bridge)
            self._sync_tick(self._bridge)
            time.sleep(0.3)

    def _initial_load(self):
        for tf in ["M15", "M30", "H1", "H4"]:
            self._sync_tf(tf, self._bridge, full=True)

    def _sync_tf(self, tf: str, bridge, full: bool = False):
        try:
            count = 350 if full else 2
            raw = bridge.get_candles("XAUUSD", tf, count)
            if not raw:
                return
            new_candles = list(reversed(raw))
            with _CACHE_LOCK:
                old = _DATA_CACHE.get(tf, {}).get("candles", [])
                merged = _merge_candles(old, new_candles, max_len=350)
                ta = _talib_indicators(merged, tf)
                _DATA_CACHE[tf] = {"candles": merged, **ta}
        except Exception as e:
            if full:
                logger.warning(f"[数据工厂] 初始加载 {tf} 失败: {e}")
            # 增量失败静默跳过

    def _sync_tick(self, bridge):
        try:
            bid, ask = bridge.get_tick_price("XAUUSD")
            with _CACHE_LOCK:
                _DATA_CACHE["tick"] = {"bid": bid, "ask": ask, "time": time.time()}
        except Exception:
            pass
