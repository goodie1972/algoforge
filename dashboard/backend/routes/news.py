"""
/api/news 路由 - 新闻过滤 & 经济日历
"""
import logging

from fastapi import APIRouter
from services.news_filter import NewsFilter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/calendar")
async def get_calendar():
    """获取本周高影响经济事件 + 禁售状态"""
    nf = NewsFilter()  # 单例，与 TradingEngine 共享
    is_blocked, reason = nf.is_in_blackout()
    events = nf.get_upcoming_events()
    windows = nf.get_blackout_windows()

    return {
        "is_blackout": is_blocked,
        "blackout_reason": reason,
        "upcoming_events": events,
        "blackout_windows": [
            {"start": nf.to_local(s).strftime("%Y-%m-%d %H:%M"),
             "end": nf.to_local(e).strftime("%Y-%m-%d %H:%M"),
             "title": t}
            for s, e, t in windows
        ],
    }


@router.post("/refresh")
async def refresh_calendar():
    """强制刷新新闻日历（重新拉取 ForexFactory + 合并内置 FOMC 事件）"""
    import threading
    nf = NewsFilter()
    t = threading.Thread(target=nf.force_refresh, daemon=True)
    t.start()
    t.join(timeout=20)
    is_blocked, reason = nf.is_in_blackout()
    events = nf.get_upcoming_events()
    windows = nf.get_blackout_windows()
    logger.info(f"[新闻刷新] 完成，内置 FOMC 已合并")
    return {
        "status": "ok",
        "is_blackout": is_blocked,
        "blackout_reason": reason,
        "upcoming_events": events,
        "blackout_windows": [
            {"start": nf.to_local(s).strftime("%Y-%m-%d %H:%M"),
             "end": nf.to_local(e).strftime("%Y-%m-%d %H:%M"),
             "title": t}
            for s, e, t in windows
        ],
    }
