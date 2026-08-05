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


def _get_h1_adx(period: int = 14) -> Optional[float]:
    """H1 ADX 计算，用于 news-bias 门禁"""
    try:
        from data.database import get_conn
        conn = get_conn()
        rows = conn.execute(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv "
            "WHERE timeframe='H1' ORDER BY timestamp"
        ).fetchall()
        conn.close()
        if len(rows) < period + 2:
            return None
        highs = [r[2] for r in rows]
        lows = [r[3] for r in rows]
        closes = [r[4] for r in rows]
        n = len(highs)
        tr_list, plus_dm, minus_dm = [], [], []
        for i in range(1, n):
            h, l_, pc = highs[i], lows[i], closes[i - 1]
            ph, pl = highs[i - 1], lows[i - 1]
            tr_list.append(max(h - l_, abs(h - pc), abs(l_ - pc)))
            up = h - ph
            down = pl - l_
            plus_dm.append(up if up > down and up > 0 else 0)
            minus_dm.append(down if down > up and down > 0 else 0)
        if len(tr_list) < period:
            return None
        atr_v = sum(tr_list[:period]) / period
        pdi_v = sum(plus_dm[:period]) / period
        ndi_v = sum(minus_dm[:period]) / period
        if atr_v <= 0:
            return None
        pdi_v = pdi_v / atr_v * 100
        ndi_v = ndi_v / atr_v * 100
        atr_s, pdi_s, ndi_s = [atr_v], [pdi_v], [ndi_v]
        for i in range(period, len(tr_list)):
            atr_s.append((atr_s[-1] * (period - 1) + tr_list[i]) / period)
            if atr_s[-1] > 0:
                pdi_s.append((pdi_s[-1] * (period - 1) + plus_dm[i] / atr_s[-1] * 100) / period)
                ndi_s.append((ndi_s[-1] * (period - 1) + minus_dm[i] / atr_s[-1] * 100) / period)
            else:
                pdi_s.append(pdi_s[-1])
                ndi_s.append(ndi_s[-1])
        dx = [abs(pdi_s[i] - ndi_s[i]) / max(pdi_s[i] + ndi_s[i], 0.001) * 100 for i in range(len(atr_s))]
        adx = [sum(dx[:period]) / period]
        for i in range(period, len(dx)):
            adx.append((adx[-1] * (period - 1) + dx[i]) / period)
        return round(adx[-1], 1)
    except Exception as e:
        return None


def _get_recent_accuracy(reviews: int = 10) -> float:
    """获取最近 N 条复盘的准确率（0.0~1.0），无数据返回 0.5（保守默认）"""
    try:
        from data import database as _db
        items = _db.get_prediction_reviews(limit=reviews)
        if not items:
            return 0.5
        correct = sum(1 for r in items if r.get("is_correct"))
        return correct / len(items)
    except Exception:
        return 0.5


def refresh_from_db() -> Optional[str]:
    """从 DB 读最新报告并更新缓存，返回新方向（H1 ADX ≤ 阈值时强制 neutral）"""
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

            # ADX 门禁：H1 ADX ≤ 阈值视为震荡市，绕过 news-bias
            try:
                from config import settings as _bias_settings
                _adx_gate = getattr(_bias_settings, 'NEWS_BIAS_ADX_GATE', 0)
                if _adx_gate > 0:
                    _h1_adx = _get_h1_adx()
                    if _h1_adx is not None and _h1_adx <= _adx_gate:
                        set("neutral", score, source=f"adx_gate(adx={_h1_adx})")
                        return "neutral"
            except Exception:
                pass

            # 准确率门禁：最近 10 条复盘准确率 < 50% 时强制 neutral
            _accuracy = _get_recent_accuracy(reviews=10)
            if _accuracy < 0.5:
                set("neutral", score, source=f"accuracy_gate(acc={_accuracy:.0%})")
                return "neutral"

            set(raw_dir, score, source="db_refresh")
            return get()
        else:
            set(None, 0, source="db_empty")
            return None
    except Exception as e:
        set(None, 0, source=f"db_error:{e}")
        return None
