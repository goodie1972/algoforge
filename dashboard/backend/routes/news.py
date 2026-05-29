"""
/api/news 路由 - 新闻过滤 & 经济日历
"""
from fastapi import APIRouter
from services.news_filter import NewsFilter

router = APIRouter(prefix="/api/news", tags=["news"])

_news_filter: NewsFilter = None


def get_news_filter() -> NewsFilter:
    global _news_filter
    if _news_filter is None:
        _news_filter = NewsFilter()
    return _news_filter


@router.get("/calendar")
async def get_calendar():
    """获取本周高影响经济事件 + 禁售状态"""
    nf = get_news_filter()
    is_blocked, reason = nf.is_in_blackout()
    events = nf.get_upcoming_events()
    windows = nf.get_blackout_windows()

    return {
        "is_blackout": is_blocked,
        "blackout_reason": reason,
        "upcoming_events": events,
        "blackout_windows": [
            {"start": s.strftime("%Y-%m-%d %H:%M"), "end": e.strftime("%Y-%m-%d %H:%M"), "title": t}
            for s, e, t in windows
        ],
    }
