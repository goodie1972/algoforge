"""
News-Bias 方向全局缓存
======================
引擎每 60s 从 news_filter.get_current_bias() 拉取最新方向，
策略层通过 BiasState.get() 同步读取（线程安全）。

direction 取值（已规范化为三态）：
  - "bullish"   看涨
  - "bearish"   看跌
  - "neutral"   中性
  - None        暂无数据 / 异常
"""
import threading
import time
from typing import Optional

_BIAS_LOCK = threading.Lock()
_direction: Optional[str] = None
_score: float = 0.0
_updated_at: float = 0.0
_source: str = "init"


def _normalize(d: Optional[str]) -> Optional[str]:
    if not d:
        return None
    d = d.lower()
    if d in ("bullish", "up", "看涨"):
        return "bullish"
    if d in ("bearish", "down", "看跌"):
        return "bearish"
    if d in ("neutral", "sideways", "震荡", "range"):
        return "neutral"
    return None


def get() -> Optional[str]:
    with _BIAS_LOCK:
        return _direction


def get_full() -> dict:
    with _BIAS_LOCK:
        return {
            "direction": _direction,
            "score": _score,
            "updated_at": _updated_at,
            "source": _source,
            "age_seconds": (time.time() - _updated_at) if _updated_at else None,
        }


def set(direction: Optional[str], score: float = 0.0, source: str = ""):
    global _direction, _score, _updated_at, _source
    with _BIAS_LOCK:
        _direction = _normalize(direction)
        _score = score
        _updated_at = time.time()
        _source = source


def is_stale(max_age_seconds: float) -> bool:
    with _BIAS_LOCK:
        if _updated_at == 0:
            return True
        return (time.time() - _updated_at) > max_age_seconds


def refresh_from_db() -> Optional[str]:
    """
    从 news_filter.get_current_bias() 读取黄金快讯方向（金十+汇通+LLM），
    更新全局缓存。策略层通过 get() 读取此缓存。
    """
    try:
        from services.news_filter import NewsFilter
        nf = NewsFilter()
        bias = nf.get_current_bias()
        if bias:
            direction = bias.get("overall", "neutral").lower()
            bullish_score = bias.get("bullish_score", 0)
            bearish_score = bias.get("bearish_score", 0)
            score = bullish_score - bearish_score
            set(direction, score, source="gold_news")
            return get()
        else:
            set(None, 0, source="no_bias")
            return None
    except Exception as e:
        set(None, 0, source=f"error:{e}")
        return None