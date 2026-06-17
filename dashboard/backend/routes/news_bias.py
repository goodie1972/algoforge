"""
/api/news-bias 路由 — 新闻预判报告
"""
import json
import logging

from fastapi import APIRouter, HTTPException, Query
from data import database as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news-bias", tags=["news-bias"])

engine_runner = None  # injected by main.py


def _parse_json_fields(report: dict) -> dict:
    """将 report 中的 JSON 字符串字段解析为对象"""
    for key in ("news_items", "variable_scores", "market_context", "prediction"):
        val = report.get(key)
        if isinstance(val, str):
            try:
                report[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return report


@router.get("/reports")
async def list_reports(
    date: str = Query("", description="日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """获取预判报告列表"""
    rows = db.get_news_bias_reports(date=date, page=page, page_size=page_size)
    return {"data": rows, "page": page, "page_size": page_size, "total": len(rows)}


@router.get("/reports/{report_id}")
async def get_report(report_id: int):
    """获取单条报告完整内容"""
    report = db.get_news_bias_report(report_id)
    if not report:
        raise HTTPException(404, f"报告 {report_id} 不存在")
    return _parse_json_fields(report)


@router.get("/latest")
async def get_latest():
    """获取最新一条报告"""
    report = db.get_latest_news_bias_report()
    if not report:
        return {"data": None}
    return {"data": _parse_json_fields(report)}


@router.get("/current")
async def get_current():
    """获取最新报告 + 实时行情"""
    report = db.get_latest_news_bias_report()
    price = {}
    if engine_runner:
        cached = getattr(engine_runner, "_cached_price", None)
        if cached:
            price = {
                "bid": cached.get("bid", 0),
                "ask": cached.get("ask", 0),
                "spread": round(cached.get("ask", 0) - cached.get("bid", 0), 2),
            }
    if report:
        report = _parse_json_fields(report)
    return {"report": report, "price": price}


@router.post("/generate")
async def generate_report():
    """手动触发生成预判报告"""
    from services.news_bias import NewsBiasEvaluator

    current_price = 0
    if engine_runner:
        cached = getattr(engine_runner, "_cached_price", None)
        if cached:
            current_price = cached.get("bid", 0)

    evaluator = NewsBiasEvaluator()
    try:
        evaluator.verify_old_predictions(current_price=current_price)
    except Exception as e:
        logger.warning(f"[NewsBias] 验证老报告异常: {e}")

    report = evaluator.generate_prediction_report(current_price=current_price)
    if not report:
        raise HTTPException(500, "生成报告失败: 未获取到新闻数据")
    return report
