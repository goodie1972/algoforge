"""
News-Bias 方向全局缓存
======================
引擎每 60s 从 DB 拉取最新 news_bias_reports 报告的方向，
策略层通过 BiasState.get() 同步读取（线程安全）。

direction 取值（已规范化为三态）：
  - "bullish"   看涨
  - "bearish"   看跌
  - "neutral"   震荡 / sideways
  - None        暂无报告（启动早期 / DB 异常 / NEWS_BIAS_ENABLED=False）
"""
import threading
import time
from typing import Optional

_BIAS_LOCK = threading.Lock()
_direction: Optional[str] = None
_score: float = 0.0
_updated_at: float = 0.0
_source: str = "init"  # 哪个文件/线程最后更新了缓存（用于诊断）


def _normalize(d: Optional[str]) -> Optional[str]:
    """将 DB 里的方向字符串规范为三态枚举"""
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
    """读取当前缓存的 bias 方向（已规范化为 bullish/bearish/neutral/None）。"""
    with _BIAS_LOCK:
        return _direction


def get_full() -> dict:
    """读取完整状态（方向 + 评分 + 时间戳 + 来源），用于 Dashboard 显示"""
    with _BIAS_LOCK:
        return {
            "direction": _direction,
            "score": _score,
            "updated_at": _updated_at,
            "source": _source,
            "age_seconds": (time.time() - _updated_at) if _updated_at else None,
        }


def set(direction: Optional[str], score: float = 0.0, source: str = ""):
    """由后台任务调用，写入最新方向（自动规范化）"""
    global _direction, _score, _updated_at, _source
    with _BIAS_LOCK:
        _direction = _normalize(direction)
        _score = score
        _updated_at = time.time()
        _source = source


def is_stale(max_age_seconds: float) -> bool:
    """缓存是否过期（用于调试：UI 可标红"数据陈旧"）"""
    with _BIAS_LOCK:
        if _updated_at == 0:
            return True
        return (time.time() - _updated_at) > max_age_seconds


def refresh_from_db() -> Optional[str]:
    """从 DB 读最新报告并更新缓存，返回新方向"""
    try:
        from data.database import get_latest_news_bias_report
        report = get_latest_news_bias_report()
        if report and isinstance(report, dict):
            prediction = report.get("prediction", {})
            if isinstance(prediction, str):
                import json as _json
                try:
                    prediction = _json.loads(prediction)
                except Exception:
                    prediction = {}
            raw_dir = prediction.get("direction") if isinstance(prediction, dict) else None
            score = prediction.get("score", 0) if isinstance(prediction, dict) else 0
            set(raw_dir, score, source="db_refresh")
            return get()
        else:
            set(None, 0, source="db_empty")
            return None
    except Exception as e:
        set(None, 0, source=f"db_error:{e}")
        return None
