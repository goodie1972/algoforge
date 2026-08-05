import logging
from fastapi import APIRouter
from services.news_bias_reviewer import NewsBiasReviewer

router = APIRouter(prefix="/api/news-review", tags=["news-review"])
logger = logging.getLogger(__name__)

@router.get("/reviews")
async def get_reviews(limit: int = 20, offset: int = 0):
    """获取复盘记录列表"""
    from data import database as db
    try:
        items = db.get_prediction_reviews(limit=limit, offset=offset)
        return {"success": True, "data": items}
    except Exception as e:
        logger.error(f"获取复盘记录失败: {e}")
        return {"success": False, "error": str(e)}

@router.get("/reviews/{review_id}")
async def get_review(review_id: int):
    """获取单条复盘详情"""
    from data import database as db
    try:
        item = db.get_prediction_review(review_id)
        if not item:
            return {"success": False, "error": "记录不存在"}
        return {"success": True, "data": item}
    except Exception as e:
        logger.error(f"获取复盘详情失败: {e}")
        return {"success": False, "error": str(e)}

@router.get("/stats")
async def get_stats(days: int = 7):
    """获取复盘统计"""
    try:
        reviewer = NewsBiasReviewer()
        stats = reviewer.get_review_stats(days=days)
        return {"success": True, "data": stats}
    except Exception as e:
        logger.error(f"获取复盘统计失败: {e}")
        return {"success": False, "error": str(e)}

@router.post("/run-review")
async def run_review(hours: int = 24):
    """手动触发复盘"""
    try:
        reviewer = NewsBiasReviewer()
        result = reviewer.review_past_reports(hours=hours)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"手动复盘失败: {e}")
        return {"success": False, "error": str(e)}

@router.get("/accuracy-trend")
async def get_accuracy_trend(days: int = 30):
    """获取准确率趋势"""
    from data import database as db
    try:
        items = db.get_accuracy_stats(days=days)
        return {"success": True, "data": items}
    except Exception as e:
        logger.error(f"获取准确率趋势失败: {e}")
        return {"success": False, "error": str(e)}