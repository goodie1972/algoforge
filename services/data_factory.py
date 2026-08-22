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
    "db_health": {               # DB 监督：写入/读取状态
        "last_write_time": 0.0,  # 最近一次 DB 写入时间戳
        "writes_total": 0,        # 累计写入次数
        "writes_failed": 0,       # 累计失败次数
        "reads_at_startup": 0,    # 启动时从 DB 读回条数
        "ok": True,               # 整体 DB 写入是否正常
    },
}

# 限制 sync_errors 长度，防止无限增长
_SYNC_ERRORS_MAX = 20

# EA(F043) 可提供的指标字段：_sync_indicators 用 EA 值覆盖这些；_sync_tf 重建缓存时保留 EA 值不被 TA-Lib 覆盖
_EA_CACHE_KEYS = frozenset({
    "rsi", "rsi_5", "rsi_10", "mfi", "bb", "bb_width",
    "ema_9", "ema_21", "ema_34", "ema_50", "ema_200",
    "sma_14", "sma_20", "sma_50",
    "atr", "atr_20", "adx", "pdi", "ndi",
    "macd", "stoch_5_3_3", "stoch_rsi", "linear_reg_slope",
    "volume_sma_20", "close",
})

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


def _ta_only_indicators(candles: list, tf: str) -> dict:
    """兜底所有指标：EA 拿不到时用 TA-Lib 算。

    返回结构：{timestamp: indicators_dict}，每根 K 线一条。
    _sync_indicators 会先用 EA 值覆盖到对应 timestamp，TA-Lib 是后备。
    """
    try:
        import talib
    except ImportError:
        return {}

    closes = np.array([c.close for c in candles], dtype=float)
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    vols = np.array([c.volume for c in candles], dtype=float)

    if len(closes) < 30:
        return {}

    # 返回结构：{c.time: {indicator_name: value, ...}}，每根 K 线一个 dict
    result = {c.time: {} for c in candles}

    # RSI
    for p in [5, 10, 14]:
        try:
            r = talib.RSI(closes, timeperiod=p)
            key = "rsi" if p == 14 else f"rsi_{p}"
            for i, c in enumerate(candles):
                if r[i] == r[i]:
                    result[c.time][key] = float(r[i])
        except Exception:
            pass

    # MFI + 方向
    try:
        m = talib.MFI(highs, lows, closes, vols, timeperiod=14)
        for i, c in enumerate(candles):
            if m[i] == m[i]:
                result[c.time]["mfi"] = float(m[i])
                if i > 0 and m[i-1] == m[i-1]:
                    cur, prv = float(m[i]), float(m[i-1])
                    result[c.time]["mfi_direction"] = "up" if cur > prv else ("down" if cur < prv else "flat")
                    result[c.time]["mfi_dir_50"] = 1 if cur >= 50 else -1
    except Exception:
        pass

    # BB
    try:
        upper, mid, lower = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2)
        widths = upper - lower
        for i, c in enumerate(candles):
            if upper[i] == upper[i]:
                result[c.time]["bb"] = {"upper": float(upper[i]), "mid": float(mid[i]), "lower": float(lower[i])}
                result[c.time]["bb_width"] = float(widths[i])
            if i > 0 and widths[i-1] == widths[i-1]:
                cur, prv = widths[i], widths[i-1]
                result[c.time]["bb_width_direction"] = "up" if cur > prv else ("down" if cur < prv else "flat")
            # BB 中轨方向（更快、比 bbi_direction 反应早）
            if i > 0 and mid[i] == mid[i] and mid[i-1] == mid[i-1]:
                cur_m, prv_m = float(mid[i]), float(mid[i-1])
                result[c.time]["bb_mid_direction"] = "up" if cur_m > prv_m else ("down" if cur_m < prv_m else "flat")
            if i >= 3:
                _avg3 = float(talib.SMA(widths, timeperiod=3)[i])
                result[c.time]["bb_width_ratio"] = round(widths[i] / _avg3, 3) if _avg3 > 0 else 1.0
    except Exception:
        pass

    # BBI = (SMA3 + SMA6 + SMA12 + SMA24) / 4
    try:
        bbi_periods = [3, 6, 12, 24]
        _bbi_smas = {p: talib.SMA(closes, timeperiod=p) for p in bbi_periods}
        for i, c in enumerate(candles):
            if i >= bbi_periods[-1] - 1 and all(_bbi_smas[p][i] == _bbi_smas[p][i] for p in bbi_periods):
                result[c.time]["bbi"] = float(sum(_bbi_smas[p][i] for p in bbi_periods) / len(bbi_periods))
    except Exception:
        pass

    # EMA(9/21/34/50/200)
    for p in [9, 21, 34, 50, 200]:
        try:
            e = talib.EMA(closes, timeperiod=p)
            for i, c in enumerate(candles):
                if e[i] == e[i]:
                    result[c.time][f"ema_{p}"] = float(e[i])
        except Exception:
            pass

    # SMA(14/20/50)
    for p in [14, 20, 50]:
        try:
            s = talib.SMA(closes, timeperiod=p)
            for i, c in enumerate(candles):
                if s[i] == s[i]:
                    result[c.time][f"sma_{p}"] = float(s[i])
        except Exception:
            pass

    # ATR(14/20)
    try:
        a14 = talib.ATR(highs, lows, closes, timeperiod=14)
        a20 = talib.ATR(highs, lows, closes, timeperiod=20)
        for i, c in enumerate(candles):
            if a14[i] == a14[i]:
                result[c.time]["atr"] = float(a14[i])
            if a20[i] == a20[i]:
                result[c.time]["atr_20"] = float(a20[i])
        atr_list = [float(x) for x in a14.tolist()]
        for i, c in enumerate(candles):
            if a14[i] == a14[i]:
                result[c.time]["atr_list_val"] = float(a14[i])  # 单值，DB 存单值
    except Exception:
        pass

    # ADX
    try:
        adx_v = talib.ADX(highs, lows, closes, timeperiod=14)
        pdi = talib.PLUS_DI(highs, lows, closes, timeperiod=14)
        ndi = talib.MINUS_DI(highs, lows, closes, timeperiod=14)
        for i, c in enumerate(candles):
            if adx_v[i] == adx_v[i]:
                result[c.time]["adx"] = float(adx_v[i])
                result[c.time]["pdi"] = float(pdi[i])
                result[c.time]["ndi"] = float(ndi[i])
    except Exception:
        pass

    # MACD
    try:
        macd, sig, _ = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
        for i, c in enumerate(candles):
            if macd[i] == macd[i]:
                result[c.time]["macd"] = {"macd": float(macd[i]), "signal": float(sig[i])}
    except Exception:
        pass

    # Stoch(5,3,3)
    try:
        sk, sd = talib.STOCH(highs, lows, closes, fastk_period=5, slowk_period=3, slowd_period=3)
        for i, c in enumerate(candles):
            if sk[i] == sk[i]:
                result[c.time]["stoch_5_3_3"] = {"k": float(sk[i]), "d": float(sd[i])}
    except Exception:
        pass

    # Stoch(14,3,3) — 黄金自动研究 v8 使用
    try:
        sk14, sd14 = talib.STOCH(highs, lows, closes, fastk_period=14, slowk_period=3, slowd_period=3)
        for i, c in enumerate(candles):
            if sk14[i] == sk14[i]:
                result[c.time]["stoch_14_3_3"] = {"k": float(sk14[i]), "d": float(sd14[i])}
    except Exception:
        pass

    # 成交量
    try:
        s20 = talib.SMA(vols, timeperiod=20)
        for i, c in enumerate(candles):
            if s20[i] == s20[i]:
                result[c.time]["volume_sma_20"] = float(s20[i])
    except Exception:
        pass

    # StochRSI(14,14,3,3)
    try:
        fastk, fastd = talib.STOCHRSI(closes, timeperiod=14, fastk_period=14, fastd_period=3, fastd_matype=0)
        for i, c in enumerate(candles):
            if fastk[i] == fastk[i]:
                result[c.time]["stoch_rsi"] = {"k": float(fastk[i]), "d": float(fastd[i])}
    except Exception:
        pass

    # 线性回归斜率(20)
    try:
        slope = talib.LINEARREG_SLOPE(closes, timeperiod=20)
        for i, c in enumerate(candles):
            if slope[i] == slope[i]:
                result[c.time]["linear_reg_slope"] = float(slope[i])
    except Exception:
        pass

    # close, trend, price_position（每根都算）
    for i, c in enumerate(candles):
        result[c.time]["close"] = float(closes[i])
        if i >= 14:
            result[c.time]["trend"] = "UP" if closes[i] > closes[i-14] else "DOWN"
        else:
            result[c.time]["trend"] = "DOWN"
        if i >= 20:
            hi20 = max(highs[max(0, i-19):i+1])
            lo20 = min(lows[max(0, i-19):i+1])
            result[c.time]["price_position"] = float((closes[i] - lo20) / (hi20 - lo20)) if hi20 > lo20 else 0.5

    return result


class DataFactory:
    """数据工厂 — 独立线程维护所有周期缓存"""

    def __init__(self, bridge):
        self._bridge = bridge
        self._running = False
        self._thread = None
        self._last_db_ts: dict = {}  # 各周期已写 DB 的最大 K 线 ts，增量写用
        self._last_ta_calc_time: dict = {}  # 各周期上次 TA-Lib 全量计算时间
        self._ta_calc_interval = 5.0  # TA-Lib 全量计算间隔（秒），减少 CPU 负载

    def connect(self) -> bool:
        """连接数据桥接"""
        try:
            ok = self._bridge.connect()
            with _CACHE_LOCK:
                _HEALTH["bridging"] = ok
            return ok
        except Exception as e:
            logger.warning(f"[DataFactory] bridge connect failed: {e}")
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
        # 启动时从 DB 恢复指标（保证 EA 死 / 重启时数据不丢）
        self._init_indicators_from_db()
        self._thread = threading.Thread(target=self._run, daemon=True, name="data-factory")
        self._thread.start()
        logger.info("[DataFactory] started")

    def _init_indicators_from_db(self):
        """从 DB 读最近 500 根 K 线的指标填充内存缓存（启动恢复）。
        取最新一根的指标展开到缓存顶层（扁平结构，策略 get_indicator 直接读）。
        """
        from data.database import get_recent_indicators
        with _CACHE_LOCK:
            for tf in ["M15", "M30", "H1", "H4"]:
                _DATA_CACHE.setdefault(tf, {"candles": []})
                rows = get_recent_indicators(tf, limit=500)
                if not rows:
                    continue
                # rows 已按时间戳升序，取最新一根的指标展开顶层
                _DATA_CACHE[tf].update(rows[-1]["indicators"])
                self._last_db_ts[tf] = int(rows[-1]["timestamp"])
                _HEALTH["db_health"]["reads_at_startup"] += len(rows)
        logger.info("[DataFactory] started, indicators recovered from DB (Strategy can run before EA F043)")

    def stop(self):
        self._running = False
        logger.info("[DataFactory] stopped")

    def _run(self):
        logger.info("[DataFactory] First full load started...")
        for attempt in range(10):
            if self._initial_load():
                break
            logger.info(f"[DataFactory] First load not done ({attempt+1}/10), retry in 1s...")
            time.sleep(1)
        else:
            logger.warning("[DataFactory] After 10 retries still missing, resuming incremental loop")
        logger.info("[DataFactory] First load done, entering incremental loop")
        _last_validation = 0
        _last_tick_persist = 0.0
        while self._running:
            for tf in ["M15", "M30", "H1", "H4"]:
                self._sync_tf(tf, self._bridge)
            self._sync_tick(self._bridge)
            self._sync_indicators(self._bridge)
            # 每 60s 把最新 tick 持久化到 DB（时间序列存档）
            if time.time() - _last_tick_persist > 60:
                _last_tick_persist = time.time()
                self._sync_tick_persist()
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
            # TA-Lib 计算 + DB 写在锁外（慢操作不持锁，避免阻塞 get_cache 读）
            # 策略：有新 K 线时立即计算，否则每 5 秒全量重算一次保证数据新鲜度
            now = time.time()
            last_calc = self._last_ta_calc_time.get(tf, 0)
            has_new_candle = (len(merged) > len(_old)) if _old else bool(new_candles)
            need_full_calc = has_new_candle or (now - last_calc > self._ta_calc_interval)

            ta = {}
            if need_full_calc:
                ta = _ta_only_indicators(merged, tf)
                self._last_ta_calc_time[tf] = now
            else:
                # 增量模式：只计算最新一根 K 线的指标
                latest_candle = merged[-1]
                ta = {latest_candle.time: {}}
            latest_ind = ta.get(merged[-1].time, {}) if merged else {}
            # 缓存扁平：最新一根 TA-Lib 展开顶层，保留 _sync_indicators 已覆盖的 EA 字段
            with _CACHE_LOCK:
                old_cache = _DATA_CACHE.get(tf, {})
                new_cache = {"candles": merged}
                for k, v in latest_ind.items():
                    new_cache[k] = old_cache[k] if (k in _EA_CACHE_KEYS and k in old_cache) else v
                _DATA_CACHE[tf] = new_cache
            # DB 增量写：新 K 线 + 最新一根(未闭合更新)，历史已闭合跳过(1400->2根/轮)
            from data.database import upsert_indicators
            last_ts = self._last_db_ts.get(tf, 0)
            latest_time = merged[-1].time if merged else None
            write_ok, write_fail, write_count = 0, 0, 0
            for c in merged:
                try:
                    ct_i = int(c.time)
                except (ValueError, TypeError):
                    ct_i = 0
                if not (ct_i > last_ts or c.time == latest_time):
                    continue
                # 最新一根用缓存值(含EA字段), 历史新K线用TA-Lib(兜底)
                if c.time == latest_time:
                    _c = _DATA_CACHE.get(tf, {})
                    ind = {k: v for k, v in _c.items() if k != "candles"}
                else:
                    ind = ta.get(c.time)
                if isinstance(ind, dict) and ind:
                    if upsert_indicators(tf, c.time, ind):
                        write_count += 1
                        if ct_i > last_ts:
                            last_ts = ct_i
                            self._last_db_ts[tf] = ct_i
                    else:
                        write_fail += 1
            with _CACHE_LOCK:
                _HEALTH["db_health"]["writes_total"] += write_count
                _HEALTH["db_health"]["writes_failed"] += write_fail
                _HEALTH["db_health"]["last_write_time"] = time.time()
                _HEALTH["db_health"]["ok"] = write_fail == 0
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
                logger.warning(f"[DataFactory] load {tf} failed: {e}")
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
                        logger.warning(f"[DataFactory] {tf} data deviation {avg_diff:.1f}  points (>5), possible data exception")
            conn.close()
        except Exception as e:
            logger.warning(f"[DataFactory] data validation failed: {e}")

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

    def _sync_tick_persist(self):
        """每 60s 调一次（独立于 _sync_tick 的高频报价），把最新 tick 写 DB。
        tick_data 表做时间序列存档，DB 唯一真理源保证持久性。
        """
        from data.database import upsert_tick
        with _CACHE_LOCK:
            tick = _DATA_CACHE.get("tick", {})
        if not tick or "bid" not in tick:
            return
        try:
            upsert_tick(int(tick.get("time", time.time())), tick.get("bid", 0), tick.get("ask", 0))
        except Exception as e:
            logger.warning(f"[DataFactory] tick write to DB failed: {e}")

    def _sync_indicators(self, bridge):
        """从 MT4 EA 直接获取指标值 (F043)。

        原则：EA 提供的字段用 EA 值（与图表完全一致），覆盖内存缓存顶层 + 持久化到 DB。
        兜底：EA 拿不到（None 或空 dict），字段由 _ta_only_indicators（_sync_tf 调）算。
        EA 没提供的字段（bb_width_direction / bb_width_ratio / bb_mid_direction /
        bbi / mfi_direction / mfi_dir_50 / trend / price_position）一律由 _ta_only_indicators 算。
        """
        from data.database import upsert_indicators
        ea_keys = ("rsi", "rsi_5", "rsi_10", "mfi", "bb",
                   "ema_9", "ema_21", "sma_14", "sma_20", "sma_50",
                   "atr", "atr_20", "adx", "pdi", "ndi",
                   "macd", "stoch_5_3_3", "volume_sma_20", "close")
        for tf in ["M15", "M30", "H1", "H4"]:
            try:
                mt4_ind = bridge.get_indicators("XAUUSD", tf) if hasattr(bridge, "get_indicators") else {}
            except Exception as _e:
                logger.warning(f"[DataFactory] F043 tf={tf} exception: {_e}")
                mt4_ind = {}
            if not mt4_ind:
                logger.warning(f"[DataFactory] F043 tf={tf} returned shorts(hasattr={hasattr(bridge,'get_indicators')})")
                continue
            ea_ts = mt4_ind.get("time")
            with _CACHE_LOCK:
                cache = _DATA_CACHE.setdefault(tf, {"candles": []})
                for k in ea_keys:
                    if k in mt4_ind and mt4_ind[k] is not None:
                        cache[k] = mt4_ind[k]
                if mt4_ind.get("bb"):
                    bb = mt4_ind["bb"]
                    cache["bb_width"] = round(bb["upper"] - bb["lower"], 2)
            # EA 值持久化到 DB：覆盖该 bar 的 TA-Lib 值，合并完整指标后写回（DB=EA 真理源）
            if ea_ts:
                with _CACHE_LOCK:
                    full = {k: v for k, v in _DATA_CACHE.get(tf, {}).items() if k != "candles"}
                if full:
                    try:
                        upsert_indicators(tf, ea_ts, full)
                        with _CACHE_LOCK:
                            _HEALTH["db_health"]["writes_total"] += 1
                            _HEALTH["db_health"]["last_write_time"] = time.time()
                    except Exception:
                        pass