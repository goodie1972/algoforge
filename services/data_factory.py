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
    """用 TA-Lib 一次算完所有公共指标。
    返回 dict: rsi, rsi_5, rsi_10, mfi, mfi_direction, bb{upper,mid,lower},
               bb_width, bb_width_direction, bb_width_ratio,
               ema_9, ema_21, sma_14, sma_20, sma_50,
               atr, atr_20, atr_list, adx, pdi, ndi,
               macd{macd,signal}, stoch_5_3_3{k,d},
               volume_sma_20, close, trend, price_position
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

    # RSI(5/10/14)
    for p in [5, 10, 14]:
        try:
            r = talib.RSI(closes, timeperiod=p)
            key = "rsi" if p == 14 else f"rsi_{p}"
            result[key] = float(r[-1]) if r[-1] == r[-1] else 50.0
        except Exception:
            pass

    # MFI(14) + 方向
    try:
        m = talib.MFI(highs, lows, closes, vols, timeperiod=14)
        result["mfi"] = float(m[-1]) if m[-1] == m[-1] else 50.0
        if len(m) > 2:
            _prev = float(m[-2]) if m[-2] == m[-2] else 50.0
            result["mfi_direction"] = "up" if result["mfi"] > _prev else ("down" if result["mfi"] < _prev else "flat")
        else:
            result["mfi_direction"] = "flat"
    except Exception:
        pass

    # BB(20,2) + 带宽
    try:
        upper, mid, lower = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2)
        result["bb"] = {
            "upper": float(upper[-1]), "mid": float(mid[-1]), "lower": float(lower[-1])
        }
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

    # EMA(9/21)
    for p in [9, 21]:
        try:
            e = talib.EMA(closes, timeperiod=p)
            result[f"ema_{p}"] = float(e[-1]) if e[-1] == e[-1] else float(closes[-1])
        except Exception:
            pass

    # SMA(14/20/50)
    for p in [14, 20, 50]:
        try:
            s = talib.SMA(closes, timeperiod=p)
            result[f"sma_{p}"] = float(s[-1]) if s[-1] == s[-1] else float(closes[-1])
        except Exception:
            pass

    # ATR(14/20)
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

    # Stoch(5,3,3)
    try:
        sk, sd = talib.STOCH(highs, lows, closes, fastk_period=5, slowk_period=3, slowd_period=3)
        result["stoch_5_3_3"] = {"k": float(sk[-1]), "d": float(sd[-1])}
    except Exception:
        pass

    # 成交量
    try:
        result["volume_sma_20"] = float(talib.SMA(vols, timeperiod=20)[-1])
    except Exception:
        pass

    result["close"] = float(closes[-1])
    result["trend"] = "UP" if closes[-1] > result.get("sma_14", closes[-1]) else "DOWN"

    # 价格位置（20周期）
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

    def connect(self) -> bool:
        """连接数据桥接"""
        try:
            ok = self._bridge.connect()
            with _CACHE_LOCK:
                _HEALTH["bridging"] = ok
            return ok
        except Exception as e:
            logger.warning(f"[数据工厂] 桥接连接失败: {e}")
            with _CACHE_LOCK:
                _HEALTH["bridging"] = False
                _HEALTH["sync_errors"].append({"time": time.time(), "tf": "bridge", "err": str(e)})
                _HEALTH["sync_errors"] = _HEALTH["sync_errors"][-_SYNC_ERRORS_MAX:]
            return False

    def start(self):
        if self._running:
            return
        self._running = True
        with _CACHE_LOCK:
            _HEALTH["started_at"] = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True, name="data-factory")
        self._thread.start()
        logger.info("[数据工厂] 已启动")

    def stop(self):
        self._running = False
        logger.info("[数据工厂] 已停止")

    def _run(self):
        logger.info("[数据工厂] 开始首次全量加载...")
        for attempt in range(10):
            if self._initial_load():
                break
            logger.info(f"[数据工厂] 首次加载未完成({attempt+1}/10)，1秒后重试...")
            time.sleep(1)
        else:
            logger.warning("[数据工厂] 首次加载10次重试后仍有缺失，继续增量循环")
        logger.info("[数据工厂] 首次加载完成，进入增量循环")
        _last_validation = 0
        while self._running:
            for tf in ["M15", "M30", "H1", "H4"]:
                self._sync_tf(tf, self._bridge)
            self._sync_tick(self._bridge)
            self._sync_indicators(self._bridge)
            # 每 5 分钟做一次数据校验
            if time.time() - _last_validation > 300:
                _last_validation = time.time()
                self._validate_data()
            time.sleep(0.3)

    def _initial_load(self) -> bool:
        """初始全量加载，返回是否所有周期加载成功"""
        all_ok = True
        for tf in ["M15", "M30", "H1", "H4"]:
            ok = self._sync_tf(tf, self._bridge, full=True)
            if not ok:
                all_ok = False
        return all_ok

    def _sync_tf(self, tf: str, bridge, full: bool = False) -> bool:
        """同步一个周期，返回是否成功获取数据"""
        try:
            with _CACHE_LOCK:
                has_data = tf in _DATA_CACHE and _DATA_CACHE[tf].get("candles") and "rsi" in _DATA_CACHE[tf]
            needs_full = full or not has_data
            count = 350 if needs_full else 2
            raw = bridge.get_candles("XAUUSD", tf, count)
            new_candles = list(reversed(raw)) if raw else []

            # 如果桥接数据不足（<30根），从 SQLite 补充历史
            if needs_full and len(new_candles) < 30:
                try:
                    from data.database import get_conn
                    conn = get_conn()
                    rows = conn.execute(
                        "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
                        "WHERE timeframe=? ORDER BY timestamp DESC LIMIT 350",
                        (tf,),
                    ).fetchall()
                    conn.close()
                    if rows:
                        rows.reverse()
                        db_candles = [Candle(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]
                        if len(new_candles) > 0:
                            db_candles[-1] = new_candles[-1]
                        new_candles = db_candles
                except Exception:
                    if not new_candles:
                        return False

            if not new_candles:
                return False

            with _CACHE_LOCK:
                _old = _DATA_CACHE.get(tf, {}).get("candles", [])
                _candles_dict = {c.time: c for c in _old}
                for c in new_candles:
                    _candles_dict[c.time] = c
                merged = sorted(_candles_dict.values(), key=lambda x: x.time)[-350:]
                ta = _talib_indicators(merged, tf)
                _DATA_CACHE[tf] = {"candles": merged, **ta}
                _HEALTH["tfs"][tf] = {
                    "last_sync": time.time(),
                    "candles": len(merged),
                    "has_indicators": bool(ta),
                    "ok": True,
                }
            return True
        except Exception as e:
            with _CACHE_LOCK:
                _HEALTH["tfs"].setdefault(tf, {})
                _HEALTH["tfs"][tf].update({"ok": False, "last_sync": time.time()})
                _HEALTH["sync_errors"].append({"time": time.time(), "tf": tf, "err": str(e)[:100]})
                _HEALTH["sync_errors"] = _HEALTH["sync_errors"][-_SYNC_ERRORS_MAX:]
            if full:
                logger.warning(f"[数据工厂] 加载 {tf} 失败: {e}")
            return False

    def _validate_data(self):
        """校验 DataFactory 缓存与数据库的已闭合 K 线是否一致"""
        try:
            from data.database import get_conn
            conn = get_conn()
            for tf in ["M15", "M30", "H1", "H4"]:
                with _CACHE_LOCK:
                    cache = _DATA_CACHE.get(tf, {})
                    candles = cache.get("candles", [])
                if len(candles) < 7:
                    continue
                # 跳过最新2根（可能未闭合），取第3~7根
                check_ts = []
                for c in candles[-7:-2]:
                    ts = c.time
                    if isinstance(ts, (int, float)):
                        check_ts.append(int(ts))
                if not check_ts:
                    continue
                ph = ",".join("?" for _ in check_ts)
                rows = conn.execute(
                    f"SELECT timestamp, close FROM ohlcv WHERE timeframe=? AND timestamp IN ({ph})",
                    (tf, *check_ts)
                ).fetchall()
                db_map = {r["timestamp"]: r["close"] for r in rows}
                diff_sum = 0.0
                count = 0
                for ts in check_ts:
                    if ts in db_map:
                        df_c = next((c.close for c in candles if int(c.time) == ts), None)
                        if df_c is not None:
                            diff_sum += abs(df_c - db_map[ts])
                            count += 1
                if count >= 3:
                    avg_diff = diff_sum / count
                    if avg_diff > 5.0:
                        logger.warning(f"[数据工厂] {tf} 数据偏差 {avg_diff:.1f} 点（>5点），可能数据异常")
            conn.close()
        except Exception as e:
            logger.warning(f"[数据工厂] 数据校验失败: {e}")

    def _sync_tick(self, bridge):
        global _TICK_COUNTER
        try:
            bid, ask = bridge.get_tick_price("XAUUSD")
            with _CACHE_LOCK:
                _DATA_CACHE["tick"] = {"bid": bid, "ask": ask, "time": time.time()}
                _TICK_COUNTER += 1
                _HEALTH["last_tick_time"] = time.time()
                _HEALTH["tick_count"] = _TICK_COUNTER
        except Exception:
            pass

    def _sync_indicators(self, bridge):
        """从MT4直接获取指标值（F043），覆盖TA-Lib计算结果"""
        for tf in ["M15", "M30", "H1", "H4"]:
            try:
                mt4_ind = bridge.get_indicators("XAUUSD", tf)
                if not mt4_ind:
                    continue
                with _CACHE_LOCK:
                    if tf not in _DATA_CACHE:
                        _DATA_CACHE[tf] = {"candles": []}
                    cache = _DATA_CACHE[tf]
                    cache["rsi"] = mt4_ind["rsi"]
                    cache["rsi_5"] = mt4_ind["rsi_5"]
                    cache["rsi_10"] = mt4_ind["rsi_10"]
                    cache["mfi"] = mt4_ind["mfi"]
                    cache["bb"] = mt4_ind["bb"]
                    cache["bb_width"] = round(mt4_ind["bb"]["upper"] - mt4_ind["bb"]["lower"], 2)
                    cache["ema_9"] = mt4_ind["ema_9"]
                    cache["ema_21"] = mt4_ind["ema_21"]
                    cache["sma_14"] = mt4_ind["sma_14"]
                    cache["sma_20"] = mt4_ind["sma_20"]
                    cache["sma_50"] = mt4_ind["sma_50"]
                    cache["atr"] = mt4_ind["atr"]
                    cache["atr_20"] = mt4_ind["atr_20"]
                    cache["adx"] = mt4_ind["adx"]
                    cache["pdi"] = mt4_ind["pdi"]
                    cache["ndi"] = mt4_ind["ndi"]
                    cache["macd"] = mt4_ind["macd"]
                    cache["stoch_5_3_3"] = mt4_ind["stoch_5_3_3"]
                    cache["volume_sma_20"] = mt4_ind["volume_sma_20"]
                    cache["close"] = mt4_ind["close"]
                    cache["trend"] = "UP" if mt4_ind["close"] > mt4_ind["sma_14"] else "DOWN"
                    # MFI 方向
                    _prev_mfi = cache.get("_prev_mfi", mt4_ind["mfi"])
                    cache["mfi_direction"] = "up" if mt4_ind["mfi"] > _prev_mfi else ("down" if mt4_ind["mfi"] < _prev_mfi else "flat")
                    cache["_prev_mfi"] = mt4_ind["mfi"]
                    # BB 宽度方向
                    _prev_bw = cache.get("_prev_bb_width", cache["bb_width"])
                    cache["bb_width_direction"] = "up" if cache["bb_width"] > _prev_bw else ("down" if cache["bb_width"] < _prev_bw else "flat")
                    cache["_prev_bb_width"] = cache["bb_width"]
                    # BB 宽度比率（滚动14根均值）
                    _hist_widths = cache.get("_hist_widths", [])
                    _hist_widths.append(cache["bb_width"])
                    if len(_hist_widths) > 14:
                        _hist_widths = _hist_widths[-14:]
                    if len(_hist_widths) >= 2:
                        _avg = sum(_hist_widths) / len(_hist_widths)
                        cache["bb_width_ratio"] = round(cache["bb_width"] / _avg, 3) if _avg > 0 else 1.0
                    else:
                        cache["bb_width_ratio"] = 1.0
                    cache["_hist_widths"] = _hist_widths
            except Exception:
                pass