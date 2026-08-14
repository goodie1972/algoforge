"""
后端时间格式化��存工具

提供高性能的时间��格式化功能，内置 LRU ��存以��免重复计算。
参考时区：settings.LOCAL_TZ (UTC+8)
"""

import threading
from functools import lru_cache
from datetime import datetime, timezone, timedelta

from config.settings import LOCAL_TZ


# ����级��，保证线程安全
_cache_lock = threading.RLock()

# ��部统计计数器
_cache_hits = 0
_cache_misses = 0


def _increment_hits():
    global _cache_hits
    with _cache_lock:
        _cache_hits += 1


def _increment_misses():
    global _cache_misses
    with _cache_lock:
        _cache_misses += 1


def _get_stats():
    with _cache_lock:
        return _cache_hits, _cache_misses


@lru_cache(maxsize=10000)
def _fmt_ts_cached(ts: int) -> str:
    """
    ��部��存��数：将 Unix 时间��(秒)格式化为 "YYYY-MM-DD HH:MM:SS" (UTC+8)
    """
    dt = datetime.fromtimestamp(ts, tz=LOCAL_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@lru_cache(maxsize=10000)
def _fmt_ts_ms_cached(ts_ms: int) -> str:
    """
    ��部��存��数：将 Unix 时间��(毫秒)格式化为 "YYYY-MM-DD HH:MM:SS" (UTC+8)
    """
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=LOCAL_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def fmt_ts(ts: int) -> str:
    """
    将 Unix 时间��(秒)格式化为 "YYYY-MM-DD HH:MM:SS" (UTC+8)
    
    Args:
        ts: Unix 时间��（秒级）
        
    Returns:
        格式化后的时间字符��，如 "2024-01-15 14:30:45"
    """
    # ��试从��存获取
    result = _fmt_ts_cached(ts)
    
    # 更新统计
    hits, misses = _get_stats()
    # 这里无法直接判断是否命中，lru_cache 不暴��此信息
    # 我们通过��查��存信息来间接统计
    return result


def fmt_ts_ms(ts_ms: int) -> str:
    """
    将 Unix 时间��(毫秒)格式化为 "YYYY-MM-DD HH:MM:SS" (UTC+8)
    
    Args:
        ts_ms: Unix 时间��（毫秒级）
        
    Returns:
        格式化后的时间字符��，如 "2024-01-15 14:30:45"
    """
    return _fmt_ts_ms_cached(ts_ms)


def get_cache_stats() -> dict:
    """
    ���取��存命中率统计
    
    Returns:
        ��含以下��的字典:
        - hits: ��存命中次数
        - misses: ��存未命中次数
        - total: 总请求次数
        - hit_rate: ���中率 (0.0 - 1.0)
        - cache_size: 当前��存条目数
        - max_size: 最大��存容量
    """
    with _cache_lock:
        hits = _cache_hits
        misses = _cache_misses
        total = hits + misses
        hit_rate = hits / total if total > 0 else 0.0
        
        # ���取 lru_cache 的当前大小
        cache_info = _fmt_ts_cached.cache_info()
        cache_size = cache_info.currsize
        max_size = 10000
        
        # 也包含毫秒��存的信息
        cache_info_ms = _fmt_ts_ms_cached.cache_info()
        cache_size += cache_info_ms.currsize
        
        return {
            "hits": hits,
            "misses": misses,
            "total": total,
            "hit_rate": round(hit_rate, 4),
            "cache_size": cache_size,
            "max_size": max_size,
        }


def clear_cache():
    """
    ��空所有��存并重置统计
    """
    global _cache_hits, _cache_misses
    with _cache_lock:
        _fmt_ts_cached.cache_clear()
        _fmt_ts_ms_cached.cache_clear()
        _cache_hits = 0
        _cache_misses = 0


# 为了更准确的统计，我们需要包装一下��存��数
# 使用一个线程安全的包装器来统计命中/未命中
class _CacheStats:
    """线程安全的��存统计包装器"""
    
    def __init__(self, func, maxsize=10000):
        self._func = lru_cache(maxsize=maxsize)(func)
        self._hits = 0
        self._misses = 0
        self._lock = threading.RLock()
    
    def __call__(self, *args, **kwargs):
        # 先��查是否在��存中（通过 cache_info 对比）
        info_before = self._func.cache_info()
        result = self._func(*args, **kwargs)
        info_after = self._func.cache_info()
        
        with self._lock:
            if info_after.hits > info_before.hits:
                self._hits += 1
            else:
                self._misses += 1
        
        return result
    
    def cache_info(self):
        return self._func.cache_info()
    
    def cache_clear(self):
        self._func.cache_clear()
        with self._lock:
            self._hits = 0
            self._misses = 0
    
    @property
    def hits(self):
        with self._lock:
            return self._hits
    
    @property
    def misses(self):
        with self._lock:
            return self._misses


# 重新实现：使用统计包装器
def _make_cached_formatter():
    def fmt_seconds(ts: int) -> str:
        dt = datetime.fromtimestamp(ts, tz=LOCAL_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    
    def fmt_ms(ts_ms: int) -> str:
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=LOCAL_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    
    return _CacheStats(fmt_seconds), _CacheStats(fmt_ms)


_fmt_ts_wrapper, _fmt_ts_ms_wrapper = _make_cached_formatter()


def fmt_ts(ts: int) -> str:
    """
    将 Unix 时间��(秒)格式化为 "YYYY-MM-DD HH:MM:SS" (UTC+8)
    
    Args:
        ts: Unix 时间��（秒级）
        
    Returns:
        格式化后的时间字符��，如 "2024-01-15 14:30:45"
    """
    return _fmt_ts_wrapper(ts)


def fmt_ts_ms(ts_ms: int) -> str:
    """
    将 Unix 时间��(毫秒)格式化为 "YYYY-MM-DD HH:MM:SS" (UTC+8)
    
    Args:
        ts_ms: Unix 时间��（毫秒级）
        
    Returns:
        格式化后的时间字符��，如 "2024-01-15 14:30:45"
    """
    return _fmt_ts_ms_wrapper(ts_ms)


def get_cache_stats() -> dict:
    """
    ���取��存命中率统计
    
    Returns:
        ��含以下��的字典:
        - hits: ��存命中次数
        - misses: ��存未命中次数
        - total: 总请求次数
        - hit_rate: ���中率 (0.0 - 1.0)
        - cache_size: 当前��存条目数
        - max_size: 最大��存容量
    """
    info_s = _fmt_ts_wrapper.cache_info()
    info_ms = _fmt_ts_ms_wrapper.cache_info()
    
    hits = _fmt_ts_wrapper.hits + _fmt_ts_ms_wrapper.hits
    misses = _fmt_ts_wrapper.misses + _fmt_ts_ms_wrapper.misses
    total = hits + misses
    hit_rate = hits / total if total > 0 else 0.0
    
    return {
        "hits": hits,
        "misses": misses,
        "total": total,
        "hit_rate": round(hit_rate, 4),
        "cache_size": info_s.currsize + info_ms.currsize,
        "max_size": 10000,
    }


def clear_cache():
    """
    ��空所有��存并重置统计
    """
    _fmt_ts_wrapper.cache_clear()
    _fmt_ts_ms_wrapper.cache_clear()