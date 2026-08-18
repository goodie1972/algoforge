"""
共享技术指标计算 — 与 DataFactory (TA-Lib) 口径一致
==================================================
- 优先使用 TA-Lib（与 data_factory.py 完全一致）
- TA-Lib 不可用时回退纯 numpy 实现
- 所有函数支持两种调用方式：
    calc_xxx(closes, ...)          → 返回当前值（最后一个）
    calc_xxx_series(closes, ...)   → 返回全序列数组

兼容旧调用签名，方便现有回测脚本迁移。
"""
import math
import numpy as np

# 尝试导入 TA-Lib；失败时使用 numpy 回退
try:
    import talib as _talib
    _HAS_TALIB = True
except ImportError:
    _talib = None
    _HAS_TALIB = False


# ============================================================
# 工具函数
# ============================================================

def _to_array(data):
    """安全转换为 numpy float64 数组"""
    if isinstance(data, (list, tuple)):
        return np.array(data, dtype=np.float64)
    return np.asarray(data, dtype=np.float64)


def _last_valid(arr):
    """返回数组最后一个有效值（非 NaN）"""
    arr = np.asarray(arr, dtype=float)
    for v in arr[::-1]:
        if not np.isnan(v):
            return float(v)
    return float('nan')


def calc_wildersmooth(values, period):
    """Wilder 平滑（用于 ATR/ADX 等指标的回退实现）"""
    arr = _to_array(values)
    n = len(arr)
    if n < period:
        return arr
    result = np.full(n, np.nan)
    result[period - 1] = np.mean(arr[:period])
    for i in range(period, n):
        result[i] = (result[i - 1] * (period - 1) + arr[i]) / period
    return result


# ============================================================
# EMA (指数移动平均)
# ============================================================

def calc_ema(closes, period):
    """返回最后一个 EMA 值"""
    arr = _to_array(closes)
    if _HAS_TALIB:
        r = _talib.EMA(arr, timeperiod=period)
        return _last_valid(r)
    return _calc_ema_numpy(arr, period)


def calc_ema_series(closes, period):
    """返回完整 EMA 序列"""
    arr = _to_array(closes)
    if _HAS_TALIB:
        return _talib.EMA(arr, timeperiod=period)
    return _calc_ema_series_numpy(arr, period)


def _calc_ema_numpy(closes, period):
    arr = _to_array(closes)
    n = len(arr)
    if n < period:
        return float('nan')
    k = 2.0 / (period + 1)
    ema = arr[0]
    for p in arr[1:]:
        ema = (p - ema) * k + ema
    return float(ema)


def _calc_ema_series_numpy(closes, period):
    arr = _to_array(closes)
    n = len(arr)
    if n < period:
        return arr.copy()
    k = 2.0 / (period + 1)
    result = np.full(n, np.nan)
    ema = arr[0]
    result[0] = ema
    for i in range(1, n):
        ema = (arr[i] - ema) * k + ema
        result[i] = ema
    return result


# ============================================================
# SMA (简单移动平均)
# ============================================================

def calc_sma(closes, period):
    """返回最后一个 SMA 值"""
    arr = _to_array(closes)
    if _HAS_TALIB:
        r = _talib.SMA(arr, timeperiod=period)
        return _last_valid(r)
    n = len(arr)
    if n < period:
        return float('nan')
    return float(np.mean(arr[-period:]))


def calc_sma_series(closes, period):
    """返回完整 SMA 序列"""
    arr = _to_array(closes)
    if _HAS_TALIB:
        return _talib.SMA(arr, timeperiod=period)
    n = len(arr)
    if n < period:
        return arr.copy()
    cumsum = np.cumsum(arr)
    result = np.full(n, np.nan)
    result[period - 1:] = (cumsum[period - 1:] - np.concatenate([[0], cumsum[:-period]])) / period
    return result


# ============================================================
# RSI (相对强弱指标)
# ============================================================

def calc_rsi(closes, period=14):
    """返回最后一个 RSI 值"""
    arr = _to_array(closes)
    if _HAS_TALIB:
        r = _talib.RSI(arr, timeperiod=period)
        return _last_valid(r)
    n = len(arr)
    if n < period + 1:
        return float('nan')
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = arr[i] - arr[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period + 1, n):
        diff = arr[i] - arr[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(diff, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-diff, 0)) / period
    if avg_loss == 0:
        return 100.0
    return float(100.0 - 100.0 / (1.0 + avg_gain / avg_loss))


def calc_rsi_series(closes, period=14):
    """返回完整 RSI 序列"""
    arr = _to_array(closes)
    if _HAS_TALIB:
        return _talib.RSI(arr, timeperiod=period)
    n = len(arr)
    if n < period + 1:
        return np.full(n, 50.0)
    result = np.full(n, np.nan)
    gains = np.diff(arr)
    gains = np.maximum(gains, 0)
    losses = np.maximum(-gains, 0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    result[period - 1] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss) if avg_loss > 0 else 100.0
    for i in range(period, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss) if avg_loss > 0 else 100.0
    return result


# ============================================================
# ATR (平均真实波幅)
# ============================================================

def calc_atr(highs, lows, closes, period=14):
    """返回最后一个 ATR 值"""
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)
    if _HAS_TALIB:
        r = _talib.ATR(h, l, c, timeperiod=period)
        return _last_valid(r)
    n = len(c)
    if n < period + 2:
        return float('nan')
    tr_list = []
    for i in range(1, n):
        tr_list.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    if len(tr_list) < period:
        return float('nan')
    atr = sum(tr_list[:period]) / period
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
    return float(atr)


def calc_atr_series(highs, lows, closes, period=14):
    """返回完整 ATR 序列"""
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)
    if _HAS_TALIB:
        return _talib.ATR(h, l, c, timeperiod=period)
    n = len(c)
    if n < period + 2:
        return np.full(n, np.nan)
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    result = np.full(n, np.nan)
    result[period] = np.mean(tr[1:period + 1])
    for i in range(period + 1, n):
        result[i] = (result[i - 1] * (period - 1) + tr[i]) / period
    return result


# ============================================================
# Bollinger Bands (布林带)
# ============================================================

def calc_bb(closes, period=20, std_mul=2.0):
    """返回 {"sma", "upper", "lower", "width"} 或 None"""
    arr = _to_array(closes)
    n = len(arr)
    if n < period:
        return None
    if _HAS_TALIB:
        upper, mid, lower = _talib.BBANDS(arr, timeperiod=period, nbdevup=std_mul, nbdevdn=std_mul)
        u = _last_valid(upper)
        m = _last_valid(mid)
        l = _last_valid(lower)
        if np.isnan(u):
            return None
        return {"sma": m, "upper": u, "lower": l, "width": (u - l) / m if m != 0 else 0}
    recent = arr[-period:]
    sma = float(np.mean(recent))
    std = float(np.std(recent, ddof=0))
    upper = sma + std_mul * std
    lower = sma - std_mul * std
    return {"sma": sma, "upper": upper, "lower": lower, "width": (upper - lower) / sma if sma != 0 else 0}


def calc_bb_series(closes, period=20, std_mul=2.0):
    """返回 (upper, mid, lower) 序列"""
    arr = _to_array(closes)
    if _HAS_TALIB:
        return _talib.BBANDS(arr, timeperiod=period, nbdevup=std_mul, nbdevdn=std_mul)
    n = len(arr)
    if n < period:
        return arr.copy(), arr.copy(), arr.copy()
    sma = calc_sma_series(arr, period)
    result_upper = np.full(n, np.nan)
    result_lower = np.full(n, np.nan)
    for i in range(period - 1, n):
        window = arr[i - period + 1:i + 1]
        sd = float(np.std(window, ddof=0))
        result_upper[i] = sma[i] + std_mul * sd
        result_lower[i] = sma[i] - std_mul * sd
    return result_upper, sma, result_lower


# ============================================================
# MACD
# ============================================================

def calc_macd(closes, fast=12, slow=26, signal=9):
    """返回 {"macd", "signal", "hist"} 或 None"""
    arr = _to_array(closes)
    if _HAS_TALIB:
        macd, sig, hist = _talib.MACD(arr, fastperiod=fast, slowperiod=slow, signalperiod=signal)
        m = _last_valid(macd)
        s = _last_valid(sig)
        h = _last_valid(hist)
        if np.isnan(m):
            return None
        return {"macd": m, "signal": s, "hist": h}
    n = len(arr)
    if n < slow + signal:
        return None
    k12, k26, k9 = 2.0 / 13, 2.0 / 27, 2.0 / 10
    e12 = arr[0]
    e26 = arr[0]
    macd_line = []
    for p in arr:
        e12 = (p - e12) * k12 + e12
        e26 = (p - e26) * k26 + e26
        macd_line.append(e12 - e26)
    sig_line = [macd_line[0]]
    for v in macd_line[1:]:
        sig_line.append((v - sig_line[-1]) * k9 + sig_line[-1])
    hist = [macd_line[i] - sig_line[i] for i in range(len(macd_line))]
    return {"macd": float(macd_line[-1]), "signal": float(sig_line[-1]), "hist": float(hist[-1])}


def calc_macd_series(closes, fast=12, slow=26, signal=9):
    """返回 (macd_line, signal_line, histogram)"""
    arr = _to_array(closes)
    if _HAS_TALIB:
        return _talib.MACD(arr, fastperiod=fast, slowperiod=slow, signalperiod=signal)
    n = len(arr)
    if n < slow + signal:
        return arr.copy(), arr.copy(), arr.copy()
    k12, k26, k9 = 2.0 / 13, 2.0 / 27, 2.0 / 10
    e12 = arr[0]
    e26 = arr[0]
    macd_line = np.zeros(n)
    for i, p in enumerate(arr):
        e12 = (p - e12) * k12 + e12
        e26 = (p - e26) * k26 + e26
        macd_line[i] = e12 - e26
    sig_line = np.zeros(n)
    sig_line[0] = macd_line[0]
    for i in range(1, n):
        sig_line[i] = (macd_line[i] - sig_line[i - 1]) * k9 + sig_line[i - 1]
    hist = macd_line - sig_line
    return macd_line, sig_line, hist


# ============================================================
# Stochastic Oscillator (随机指标)
# ============================================================

def calc_stoch(highs, lows, closes, k_period=9, slowing=3, d_period=3):
    """返回 {"k", "d", "prev_k", "prev_d"} 或 None"""
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)
    n = len(c)
    if _HAS_TALIB:
        sk, sd = _talib.STOCH(h, l, c, fastk_period=k_period, slowk_period=slowing, slowd_period=d_period)
        k = _last_valid(sk)
        d = _last_valid(sd)
        if np.isnan(k):
            return None
        prev_k_idx = len(sk) - 2 if len(sk) >= 2 else 0
        prev_d_idx = len(sd) - 2 if len(sd) >= 2 else 0
        return {
            "k": k, "d": d,
            "prev_k": float(sk[prev_k_idx]) if not np.isnan(sk[prev_k_idx]) else k,
            "prev_d": float(sd[prev_d_idx]) if not np.isnan(sd[prev_d_idx]) else d,
        }
    if n < k_period + slowing + d_period + 1:
        return None
    raw_k = np.array([
        ((c[i] - np.min(l[i - k_period + 1:i + 1])) /
         (np.max(h[i - k_period + 1:i + 1]) - np.min(l[i - k_period + 1:i + 1])) * 100)
        if (np.max(h[i - k_period + 1:i + 1]) - np.min(l[i - k_period + 1:i + 1])) != 0
        else 50.0
        for i in range(k_period - 1, n)
    ])
    if len(raw_k) < slowing + d_period + 1:
        return None
    smooth_k = np.array([np.mean(raw_k[i - slowing + 1:i + 1]) for i in range(slowing - 1, len(raw_k))])
    if len(smooth_k) < d_period + 1:
        return None
    return {
        "k": float(smooth_k[-1]), "d": float(np.mean(smooth_k[-d_period:])),
        "prev_k": float(smooth_k[-2]), "prev_d": float(np.mean(smooth_k[-(d_period + 1):-1])),
    }


def calc_stoch_series(highs, lows, closes, k_period=9, slowing=3, d_period=3):
    """返回 (k_series, d_series)"""
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)
    if _HAS_TALIB:
        return _talib.STOCH(h, l, c, fastk_period=k_period, slowk_period=slowing, slowd_period=d_period)
    n = len(c)
    result_k = np.full(n, np.nan)
    result_d = np.full(n, np.nan)
    if n < k_period + slowing + d_period:
        return result_k, result_d
    raw_k = np.full(n, np.nan)
    for i in range(k_period - 1, n):
        hl_range = np.max(h[i - k_period + 1:i + 1]) - np.min(l[i - k_period + 1:i + 1])
        if hl_range == 0:
            raw_k[i] = 50.0
        else:
            raw_k[i] = (c[i] - np.min(l[i - k_period + 1:i + 1])) / hl_range * 100
    smooth_k = np.full(n, np.nan)
    for i in range(slowing - 1 + k_period - 1, n):
        smooth_k[i] = np.mean(raw_k[i - slowing + 1:i + 1])
    for i in range(d_period - 1 + slowing - 1 + k_period - 1, n):
        result_k[i] = smooth_k[i]
        result_d[i] = np.mean(smooth_k[i - d_period + 1:i + 1])
    return result_k, result_d


# ============================================================
# ADX (+DI / -DI)
# ============================================================

def calc_adx(highs, lows, closes, period=14):
    """返回 {"adx", "pdi", "ndi"} 或 None"""
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)
    n = len(c)
    if _HAS_TALIB:
        adx_arr = _talib.ADX(h, l, c, timeperiod=period)
        pdi_arr = _talib.PLUS_DI(h, l, c, timeperiod=period)
        ndi_arr = _talib.MINUS_DI(h, l, c, timeperiod=period)
        a = _last_valid(adx_arr)
        p = _last_valid(pdi_arr)
        d = _last_valid(ndi_arr)
        if np.isnan(a):
            return None
        return {"adx": a, "pdi": p, "ndi": d}
    if n < period + 2:
        return None
    return _calc_adx_wilder(h, l, c, period)


def calc_adx_series(highs, lows, closes, period=14):
    """返回 (adx, pdi, ndi) 序列"""
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)
    if _HAS_TALIB:
        return (_talib.ADX(h, l, c, timeperiod=period),
                _talib.PLUS_DI(h, l, c, timeperiod=period),
                _talib.MINUS_DI(h, l, c, timeperiod=period))
    n = len(c)
    if n < period + 2:
        return np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)

    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        up = h[i] - h[i - 1]
        dn = l[i - 1] - l[i]
        plus_dm[i] = up if (up > dn and up > 0) else 0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0

    result_adx = np.full(n, np.nan)
    result_pdi = np.full(n, np.nan)
    result_ndi = np.full(n, np.nan)

    atr_s = np.mean(tr[1:period + 1])
    pdi_raw = np.mean(plus_dm[1:period + 1]) / atr_s * 100 if atr_s > 0 else 0
    ndi_raw = np.mean(minus_dm[1:period + 1]) / atr_s * 100 if atr_s > 0 else 0
    result_pdi[period] = pdi_raw
    result_ndi[period] = ndi_raw
    dx = abs(pdi_raw - ndi_raw) / max(pdi_raw + ndi_raw, 0.001) * 100
    result_adx[period] = dx

    for i in range(period + 1, n):
        atr_s = (atr_s * (period - 1) + tr[i]) / period
        if atr_s > 0:
            pdi_raw = (pdi_raw * (period - 1) + plus_dm[i] / atr_s * 100) / period
            ndi_raw = (ndi_raw * (period - 1) + minus_dm[i] / atr_s * 100) / period
        result_pdi[i] = pdi_raw
        result_ndi[i] = ndi_raw
        dx = abs(pdi_raw - ndi_raw) / max(pdi_raw + ndi_raw, 0.001) * 100
        result_adx[i] = dx

    return result_adx, result_pdi, result_ndi


def _calc_adx_wilder(highs, lows, closes, period=14):
    """Wilder ADX 纯 numpy 回退"""
    n = len(highs)
    if n < period + 2:
        return None
    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > down and up > 0) else 0
        minus_dm[i] = down if (down > up and down > 0) else 0
    atr_s = np.mean(tr[1:period + 1])
    pdi_raw = np.mean(plus_dm[1:period + 1]) / atr_s * 100 if atr_s > 0 else 0
    ndi_raw = np.mean(minus_dm[1:period + 1]) / atr_s * 100 if atr_s > 0 else 0
    if atr_s <= 0:
        return None
    for i in range(period + 1, n):
        atr_s = (atr_s * (period - 1) + tr[i]) / period
        if atr_s > 0:
            pdi_raw = (pdi_raw * (period - 1) + plus_dm[i] / atr_s * 100) / period
            ndi_raw = (ndi_raw * (period - 1) + minus_dm[i] / atr_s * 100) / period
    dx = abs(pdi_raw - ndi_raw) / max(pdi_raw + ndi_raw, 0.001) * 100
    return {"adx": float(dx), "pdi": float(pdi_raw), "ndi": float(ndi_raw)}


# ============================================================
# MFI (资金流量指数)
# ============================================================

def calc_mfi(highs, lows, closes, volumes, period=14):
    """返回最后一个 MFI 值"""
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)
    v = _to_array(volumes)
    if _HAS_TALIB:
        r = _talib.MFI(h, l, c, v, timeperiod=period)
        return _last_valid(r)
    n = len(c)
    if n < period + 1:
        return float('nan')
    typical_price = (h + l + c) / 3.0
    mf = typical_price * v
    pos_mf = np.sum(mf[np.diff(typical_price) >= 0])
    neg_mf = np.sum(mf[np.diff(typical_price) < 0])
    if neg_mf == 0:
        return 100.0
    mfi = 100.0 - 100.0 / (1.0 + pos_mf / neg_mf)
    return float(mfi)


def calc_mfi_series(highs, lows, closes, volumes, period=14):
    """返回完整 MFI 序列"""
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)
    v = _to_array(volumes)
    if _HAS_TALIB:
        return _talib.MFI(h, l, c, v, timeperiod=period)
    n = len(c)
    if n < period + 1:
        return np.full(n, 50.0)
    typical_price = (h + l + c) / 3.0
    mf = typical_price * v
    result = np.full(n, np.nan)
    pos_mf = np.sum(mf[:period] * (np.diff(typical_price[:period + 1]) >= 0))
    neg_mf = np.sum(mf[:period] * (np.diff(typical_price[:period + 1]) < 0))
    if neg_mf == 0:
        result[period - 1] = 100.0
    else:
        result[period - 1] = 100.0 - 100.0 / (1.0 + pos_mf / neg_mf)
    for i in range(period, n):
        diff = typical_price[i] - typical_price[i - 1]
        pos_mf = (pos_mf * (period - 1) + (mf[i] if diff >= 0 else 0)) / period
        neg_mf = (neg_mf * (period - 1) + (mf[i] if diff < 0 else 0)) / period
        if neg_mf == 0:
            result[i] = 100.0
        else:
            result[i] = 100.0 - 100.0 / (1.0 + pos_mf / neg_mf)
    return result


# ============================================================
# Keltner Channel (肯特纳通道)
# ============================================================

def calc_keltner(closes, atr_val, period=20, mult=2.0):
    """返回 {"ema", "upper", "lower"} 或 None"""
    arr = _to_array(closes)
    ema = calc_ema(arr, period)
    if ema is None or atr_val is None or math.isnan(ema) or math.isnan(atr_val):
        return None
    return {"ema": ema, "upper": ema + atr_val * mult, "lower": ema - atr_val * mult}


def calc_keltner_series(closes, highs, lows, period=20, mult=2.0, atr_period=14):
    """返回 (upper, ema, lower)"""
    arr = _to_array(closes)
    h = _to_array(highs)
    l = _to_array(lows)
    n = len(arr)
    ema_series = calc_ema_series(arr, period)
    atr_series = calc_atr_series(h, l, arr, atr_period)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(ema_series[i]) and not np.isnan(atr_series[i]):
            upper[i] = ema_series[i] + atr_series[i] * mult
            lower[i] = ema_series[i] - atr_series[i] * mult
    return upper, ema_series, lower


# ============================================================
# 兼容性别名 — 供旧脚本直接替换
# ============================================================

calc_ema_current = calc_ema
calc_atr_from_lists = calc_atr
