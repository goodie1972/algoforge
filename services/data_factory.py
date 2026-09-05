"""
数据工厂 — 三轨架构第1轨
- 独立线程从桥接增量拉取 K 线
- TA-Lib 预计算所有公共指标
- 全局缓存供策略和 Athlete 读取
"""
DATA_FACTORY_VERSION = "v5"

# 变更日志：框架层版本纪律见 docs/CODE_REVIEW_STANDARD.md 🔴「策略/框架模块版本号」
# 结构 {version, date, desc}（框架模块无 MT4 magic）
DATA_FACTORY_CHANGELOG = [
    {
        "version": "v5",
        "date": "2026-09-05",
        "desc": (
            "tick_data 表持久化清理（D1 优化）：DataFactory 在每 5 分钟 _validate_data() "
            "之后调用 prune_tick_data(max_rows=200000)，tick 表滚动窗口避免无限增长。"
            "（database.py 同步加了 idx_tick_data_ts 索引与 prune_tick_data 函数。）"
        ),
    },
    {
        "version": "v4",
        "date": "2026-09-05",
        "desc": (
            "暖启动门控（B 优化，加速重启）：新增本地 K 线缓存持久化 "
            "(data/cache/candles_cache.pkl)。启动时先加载上次缓存作为暖缓存，"
            "首轮 _initial_load 按「当前时间 − 缓存最后一根时间」估算缺口根数增量补齐"
            "(上限 2000)，不再无脑重拉 4×2000 根。桥接就绪时首轮拉取从 ~秒级降至毫秒级，"
            "引擎 start() 的 time.sleep 死等同时改为 _wait_data_factory_ready 有界等待(≤5s)。"
            "缓存每 5 分钟及首轮成功后落盘，异常自动回退全量拉取。"
        ),
    },
    {
        "version": "v3",
        "date": "2026-09-04",
        "desc": (
            "两处缓存正确性修复：(1) 修复顶层缓存被清空——_sync_tf 增量模式(need_full_calc=False)"
            "时 latest_ind 为空，new_cache 却只放 candles，导致全量计算得到的 45 个指标键在下一个"
            "0.3s 增量轮次被整体清零（实测 rsi/TA-Lib 键均变 None，仅 EA 键能靠 _sync_indicators "
            "补回）。改为先继承旧值再覆盖：bar1 在新 K 线出现前恒定，增量轮次保持原值语义正确。"
            "(2) 保护条件改为“EA 本轮确实提供过该键才保护”——新增 _EA_PROVIDED_TS{key:ts} 与 "
            "_EA_PROVIDED_TTL=30s，旧逻辑 `k in _EA_CACHE_KEYS and k in old_cache` 无条件保护，"
            "EA 掉线时所有 EA 键永久冻结在最后有效值；现超 TTL 即自动回退 TA-Lib 实时值。"
        ),
    },
    {
        "version": "v2",
        "date": "2026-09-04",
        "desc": (
            "修复 _EA_CACHE_KEYS 冻结 bug：原集合含 5 个 EA 从未发送的键(ema_34/ema_50/"
            "ema_200/stoch_rsi/linear_reg_slope)，导致 _sync_tf 保护逻辑把它们冻结为启动期旧值。"
            "现改为 ema_34/ema_50/ema_200/linear_reg_slope 改由 EA(F043) 真值提供"
            "(协同 tools/FreeMT4Bridge.mq4 + core/freemt4_bridge.py F043 扩展 6 字段)，"
            "stoch_rsi 与蜡烛图形态(candle_pattern_dir/name) 仍仅 TA-Lib 计算。"
            "新增 cci(iCCI(14)) 与 cci_direction（EA 真值，方向由当前/前一根 CCI 比较），"
            "_ta_only_indicators 保留 CCI 作为 EA 离线兜底。"
        ),
    },
    {
        "version": "v1",
        "date": "2026-09-03",
        "desc": (
            "建立版本基线。记录最近一次实质性改动（commit 15f0c80 重构）："
            "_ta_only_indicators 新增派生字段(rsi_dir_3bar/atr_ma_5/atr_sma20/"
            "atr_ratio_30/roc_10/stoch_k_prev/d_prev/candle_pattern_dir/name)，"
            "修复 CDLBEARISHENGULFING→CDLENGULFING 死分支；"
            "供策略经 get_indicator() 读取已闭合 bar1 缓存，消除重绘/双份真相源。"
        ),
    },
]

import logging
import os
import threading
import time
import numpy as np
import pickle

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
# 注：stoch_rsi 与蜡烛图形态(candle_pattern_dir/name) 仅由 TA-Lib 计算，不在此集合——放入会被 _sync_tf 保护逻辑冻结为旧值。
_EA_CACHE_KEYS = frozenset({
    "rsi", "rsi_5", "rsi_10", "mfi", "bb", "bb_width",
    "ema_9", "ema_21", "ema_34", "ema_50", "ema_200",
    "sma_14", "sma_20", "sma_50",
    "atr", "atr_20", "adx", "pdi", "ndi",
    "macd", "stoch_5_3_3", "linear_reg_slope",
    "volume_sma_20", "close", "cci", "cci_direction",
})

# EA 实际提供时间戳：{tf: {key: 最近一次 EA 提供该键的 time.time()}}。
# 语义：只有 EA 在 _EA_PROVIDED_TTL 秒内确实提供过该键，_sync_tf 才保护其不被 TA-Lib 覆盖。
# 否则（EA 掉线 / 该字段缺失 / 超时未刷新）视为"本轮未提供"，自动回退 TA-Lib 实时值，
# 避免旧实现"无条件保护"导致的冻结（EA 掉线时所有 EA 键永久停在最后有效值）。
# TTL 需 >> 正常一个 F043 轮询周期(约 1~3s，4 个周期各一次) 以避免 EA/TA 值来回跳变，
# 又要足够短以便掉线后及时回退；30s 兼顾两者。
_EA_PROVIDED_TS: dict = {}
_EA_PROVIDED_TTL = 30.0

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

    # Stoch(5,3,3) —— 同时存前一根(prev)供策略穿越检测，避免策略内自算
    try:
        sk, sd = talib.STOCH(highs, lows, closes, fastk_period=5, slowk_period=3, slowd_period=3)
        for i, c in enumerate(candles):
            if sk[i] == sk[i]:
                result[c.time]["stoch_5_3_3"] = {"k": float(sk[i]), "d": float(sd[i])}
                if i >= 1:
                    # prev = 前一根已闭合 K 线的 K/D（穿越检测用）
                    result[c.time]["stoch_k_prev"] = float(sk[i-1])
                    result[c.time]["stoch_d_prev"] = float(sd[i-1])
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

    # CCI(14) + 方向（EA 离线兜底；EA 在线时由 _sync_indicators 用 EA 真值覆盖）
    try:
        cci = talib.CCI(highs, lows, closes, timeperiod=14)
        for i in range(1, len(candles)):
            if cci[i] == cci[i]:
                result[candles[i].time]["cci"] = float(cci[i])
                if cci[i-1] == cci[i-1]:
                    _cur, _prv = float(cci[i]), float(cci[i-1])
                    result[candles[i].time]["cci_direction"] = "up" if _cur > _prv else ("down" if _cur < _prv else "flat")
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

    # ───────────────────────────────────────────────────────────────
    # 派生字段：供策略经 get_indicator() 读取，统一在 DataFactory 计算。
    # 不在 _EA_CACHE_KEYS 中，不会被 EA 值覆盖；_sync_tf 仅暴露 bar1(已闭合)。
    # 目的：消除策略内 talib/numpy 自算（重绘 + 双份真相源），详见
    # docs/CODE_REVIEW_STANDARD.md 🔴「禁止在策略内自算买卖指标」。
    # ───────────────────────────────────────────────────────────────

    # RSI(14) 连续 3 根方向（仅用已闭合 K 线）
    try:
        r = talib.RSI(closes, timeperiod=14)
        for i in range(2, len(candles)):
            if r[i] == r[i] and r[i-1] == r[i-1] and r[i-2] == r[i-2]:
                if r[i-2] < r[i-1] < r[i]:
                    result[candles[i].time]["rsi_dir_3bar"] = "up"
                elif r[i-2] > r[i-1] > r[i]:
                    result[candles[i].time]["rsi_dir_3bar"] = "down"
                else:
                    result[candles[i].time]["rsi_dir_3bar"] = "flat"
    except Exception:
        pass

    # ATR(14) 派生：近 5 根均值 / SMA20 / 与 30 根前之比
    try:
        a14 = talib.ATR(highs, lows, closes, timeperiod=14)
        for i in range(len(candles)):
            if a14[i] != a14[i]:
                continue
            if i >= 4:
                _w = [a14[j] for j in range(i-4, i+1) if a14[j] == a14[j]]
                if len(_w) >= 5:
                    result[candles[i].time]["atr_ma_5"] = float(sum(_w) / len(_w))
            if i >= 19:
                _w = [a14[j] for j in range(i-19, i+1) if a14[j] == a14[j]]
                if len(_w) >= 20:
                    result[candles[i].time]["atr_sma20"] = float(sum(_w) / len(_w))
            if i >= 30 and a14[i-30] == a14[i-30] and a14[i-30] > 0:
                result[candles[i].time]["atr_ratio_30"] = float(a14[i] / a14[i-30])
    except Exception:
        pass

    # ROC(10)
    try:
        roc = talib.ROC(closes, timeperiod=10)
        for i in range(10, len(candles)):
            if roc[i] == roc[i]:
                result[candles[i].time]["roc_10"] = float(roc[i])
    except Exception:
        pass

    # K 线形态（仅基于已闭合 K 线，剔除 forming bar0；优先级同原策略）
    try:
        _o = np.array([c.open for c in candles], dtype=float)
        _arrays = [
            ("long", "MORNING", talib.CDLMORNINGSTAR(_o, highs, lows, closes, penetration=0.3)),
            ("short", "EVENING", talib.CDLEVENINGSTAR(_o, highs, lows, closes, penetration=0.3)),
            ("long", "HAMMER", talib.CDLHAMMER(_o, highs, lows, closes)),
            ("long", "PIERCE", talib.CDLPIERCING(_o, highs, lows, closes)),
            ("short", "SHOOT", talib.CDLSHOOTINGSTAR(_o, highs, lows, closes)),
            ("short", "CLOUD", talib.CDLDARKCLOUDCOVER(_o, highs, lows, closes)),
            ("short", "ENGULF", talib.CDLENGULFING(_o, highs, lows, closes)),
            ("short", "HANG", talib.CDLHANGINGMAN(_o, highs, lows, closes)),
        ]
        for i in range(len(candles)):
            _dir, _name = "none", None
            for direction, name, arr in _arrays:
                val = arr[i]
                if direction == "long" and val > 0:
                    _dir, _name = "long", name
                    break
                if direction == "short" and val < 0:
                    _dir, _name = "short", name
                    break
            result[candles[i].time]["candle_pattern_dir"] = _dir
            if _name:
                result[candles[i].time]["candle_pattern_name"] = _name
    except Exception:
        pass

    return result


# ---- 暖启动 K 线缓存（B 优化）----
# 持久化上次的 K 线缓存，重启时按「当前时间 − 缓存最后一根时间」增量补齐，
# 避免无脑重拉 4×2000 根，引擎重启首轮拉取从秒级降至毫秒级。
_TF_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800,
}

_CANDLE_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "cache", "candles_cache.pkl",
)


def _save_candle_cache() -> None:
    """将各周期 candles 落盘（pickle），供下次重启暖启动。"""
    try:
        os.makedirs(os.path.dirname(_CANDLE_CACHE_PATH), exist_ok=True)
        snapshot = {}
        with _CACHE_LOCK:
            for tf in ("M15", "M30", "H1", "H4"):
                candles = _DATA_CACHE.get(tf, {}).get("candles", [])
                if candles:
                    snapshot[tf] = [
                        {"time": c.time, "open": c.open, "high": c.high,
                         "low": c.low, "close": c.close, "volume": c.volume}
                        for c in candles
                    ]
        if not snapshot:
            return
        with open(_CANDLE_CACHE_PATH, "wb") as f:
            pickle.dump(snapshot, f)
    except Exception as e:
        logger.warning(f"[DataFactory] save candle cache failed: {e}")


def _load_candle_cache() -> None:
    """加载上次落盘的 K 线缓存到内存（暖缓存）；失败或无文件则忽略。"""
    try:
        if not os.path.exists(_CANDLE_CACHE_PATH):
            return
        with open(_CANDLE_CACHE_PATH, "rb") as f:
            snapshot = pickle.load(f)
        if not isinstance(snapshot, dict):
            return
        loaded = {}
        with _CACHE_LOCK:
            for tf, rows in snapshot.items():
                if tf not in ("M15", "M30", "H1", "H4"):
                    continue
                if not rows:
                    continue
                _DATA_CACHE.setdefault(tf, {"candles": []})["candles"] = [
                    Candle(r["time"], r["open"], r["high"], r["low"], r["close"], r["volume"])
                    for r in rows
                ]
                loaded[tf] = len(rows)
        if loaded:
            logger.info(f"[DataFactory] candle cache loaded (warm-start): {loaded}")
    except Exception as e:
        logger.warning(f"[DataFactory] load candle cache failed: {e}")


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
        # 暖启动：加载上次落盘的 K 线缓存，使首轮只需增量补齐
        self._load_candle_cache()
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
                rows = get_recent_indicators(tf, limit=2000)
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
        # 落盘暖启动缓存（供下次重启增量补齐）
        self._save_candle_cache()
        _last_validation = 0
        _last_tick_persist = 0.0
        _last_cache_persist = time.time()
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
                # 同时清理 tick_data 表（避免无限增长，1-2 周滚动）
                try:
                    from data.database import prune_tick_data
                    deleted = prune_tick_data()
                    if deleted:
                        logger.info(f"[DataFactory] tick_data pruned {deleted} rows")
                except Exception as e:
                    logger.warning(f"[DataFactory] prune_tick_data failed: {e}")
            # 每 5 分钟落盘一次暖启动缓存
            if time.time() - _last_cache_persist > 300:
                _last_cache_persist = time.time()
                self._save_candle_cache()
            time.sleep(0.3)

    def _initial_load(self) -> bool:
        """初始加载：有暖缓存则按时间差增量补齐（极快），否则全量 2000 根。"""
        all_ok = True
        for tf in ["M15", "M30", "H1", "H4"]:
            with _CACHE_LOCK:
                candles = _DATA_CACHE.get(tf, {}).get("candles", [])
                last_t = candles[-1].time if candles else 0
            if last_t:
                # 按时间差估算需补齐的 K 线根数（含 10 根余量），上限 2000
                gap = int((time.time() - last_t) / _TF_SECONDS[tf]) + 10
                cnt = min(2000, max(2, gap))
                ok = self._sync_tf(tf, self._bridge, full=False, count=cnt)
            else:
                ok = self._sync_tf(tf, self._bridge, full=True)
            if not ok:
                all_ok = False
        return all_ok

    def _sync_tf(self, tf: str, bridge, full: bool = False, count: int = None) -> bool:
        """同步一个周期，返回是否成功获取数据。

        count 可显式指定拉取根数（暖启动按时间差计算缺口）；为 None 时
        全量用 2000、增量用 2。
        """
        try:
            with _CACHE_LOCK:
                has_data = tf in _DATA_CACHE and _DATA_CACHE[tf].get("candles") and "rsi" in _DATA_CACHE[tf]
            needs_full = full or not has_data
            if count is None:
                count = 2000 if needs_full else 2
            raw = bridge.get_candles("XAUUSD", tf, count)
            new_candles = list(reversed(raw)) if raw else []

            # 如果桥接数据不足（<30根），从 SQLite 补充历史
            if needs_full and len(new_candles) < 30:
                try:
                    from data.database import get_conn
                    conn = get_conn()
                    rows = conn.execute(
                        "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
                        "WHERE timeframe=? ORDER BY timestamp DESC LIMIT 2000",
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
                merged = sorted(_candles_dict.values(), key=lambda x: x.time)[-2000:]
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
                # 增量模式：只标记最新一根 K 线，不触发 talib 重算
                latest_candle = merged[-1]
                ta = {latest_candle.time: {}}
            # 策略基于已完成 K 线(bar1)做决策：取倒数第二根作为顶层缓存
            # merged[-1]=bar0(未完成,tick级), merged[-2]=bar1(已完成,固定)
            bar1_candle = merged[-2] if len(merged) >= 2 else merged[-1]
            latest_ind = ta.get(bar1_candle.time, {}) if merged else {}
            # 缓存扁平：最新一根 TA-Lib 展开顶层，保留 _sync_indicators 已覆盖的 EA 字段
            #
            # 两处关键修正（v3）：
            # 1) 增量模式(need_full_calc=False)时 latest_ind 为空，若 new_cache 只放 candles
            #    会把全部指标键清空 → 顶层缓存 45 键瞬间归零，策略读到 None。
            #    先继承旧值：bar1 在新 K 线出现前本就固定不变，增量轮次保持原值语义正确。
            # 2) 保护条件由"k in _EA_CACHE_KEYS and k in old_cache"改为
            #    "EA 本轮确实提供过该键(时间戳在 TTL 内)"，EA 掉线超过 TTL 即回退 TA-Lib。
            with _CACHE_LOCK:
                old_cache = _DATA_CACHE.get(tf, {})
                prov = _EA_PROVIDED_TS.get(tf, {})
                new_cache = {"candles": merged}
                # (1) 继承：保留上一轮的指标值，避免增量轮次清空
                for k, v in old_cache.items():
                    if k != "candles":
                        new_cache[k] = v
                # (2) 覆盖：本轮 TA-Lib 值写入，但 EA 近期确实提供过的键保留 EA 值
                for k, v in latest_ind.items():
                    ea_provided = (k in _EA_CACHE_KEYS
                                   and (now - prov.get(k, 0.0)) <= _EA_PROVIDED_TTL)
                    new_cache[k] = old_cache[k] if (ea_provided and k in old_cache) else v
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
                   "ema_9", "ema_21", "ema_34", "ema_50", "ema_200",
                   "sma_14", "sma_20", "sma_50",
                   "atr", "atr_20", "adx", "pdi", "ndi",
                   "macd", "stoch_5_3_3", "linear_reg_slope",
                   "volume_sma_20", "close", "cci")
        for tf in ["M15", "M30", "H1", "H4"]:
            try:
                mt4_ind = bridge.get_indicators("XAUUSD", tf, shift=1) if hasattr(bridge, "get_indicators") else {}
            except Exception as _e:
                logger.warning(f"[DataFactory] F043 tf={tf} exception: {_e}")
                mt4_ind = {}
            if not mt4_ind:
                logger.warning(f"[DataFactory] F043 tf={tf} returned shorts(hasattr={hasattr(bridge,'get_indicators')})")
                continue
            ea_ts = mt4_ind.get("time")
            with _CACHE_LOCK:
                cache = _DATA_CACHE.setdefault(tf, {"candles": []})
                prov = _EA_PROVIDED_TS.setdefault(tf, {})
                _now = time.time()
                for k in ea_keys:
                    if k in mt4_ind and mt4_ind[k] is not None:
                        cache[k] = mt4_ind[k]
                        prov[k] = _now  # 记录"EA 本轮确实提供了该键"
                if mt4_ind.get("bb"):
                    bb = mt4_ind["bb"]
                    cache["bb_width"] = round(bb["upper"] - bb["lower"], 2)
                    prov["bb_width"] = _now
                # CCI 值与方向（方向由 EA 提供的当前/前一根 CCI 比较，保证图表一致真值）
                if "cci" in mt4_ind and mt4_ind["cci"] is not None:
                    cache["cci"] = mt4_ind["cci"]
                    prov["cci"] = _now
                    _cci_prev = mt4_ind.get("cci_prev")
                    if _cci_prev is not None:
                        _cur, _prv = float(mt4_ind["cci"]), float(_cci_prev)
                        cache["cci_direction"] = "up" if _cur > _prv else ("down" if _cur < _prv else "flat")
                        prov["cci_direction"] = _now
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