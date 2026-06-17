"""
/api/reports 路由 — 日报/周报系统
"""
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from data import database as db

router = APIRouter(prefix="/api/reports", tags=["reports"])

engine_runner = None
run_bridge = None
logger = logging.getLogger(__name__)


# ── 报告生成核心逻辑 ──────────────────────────────────────

def _sec_to_hms(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def _build_daily_report() -> dict:
    """收集当前引擎状态，生成日报内容（同会话中的 10 分钟报告格式）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = engine_runner.get_status() if engine_runner else {}
    account = getattr(engine_runner, '_cached_account', None) or {}
    positions = getattr(engine_runner, '_cached_positions', []) or []
    price = getattr(engine_runner, '_cached_price', None) or {}

    # 引擎状态
    engine_ok = status.get("status") == "running"
    bridge_ok = status.get("bridge_connected", False)
    uptime = _sec_to_hms(status.get("uptime_seconds", 0))
    verdict = "GREEN" if engine_ok else "RED"

    # 浮动盈亏
    floating_pnl = sum(p.get("profit", 0) for p in positions)

    # 当日盈亏（从风险数据获取，或从 trades 表统计）
    risk_info = {}
    try:
        from dashboard.backend.routes.engine import engine_runner as er
        if er and hasattr(er, '_engine') and er._engine:
            eng = er._engine
            risk_info = {
                "daily_pnl": getattr(eng, '_daily_pnl', 0),
                "daily_drawdown": getattr(eng, '_daily_drawdown', 0),
            }
    except Exception:
        pass

    daily_pnl = risk_info.get("daily_pnl", 0)

    # 持仓按策略分组
    positions_by_strategy = {}
    for p in positions:
        strat = p.get("strategy", "unknown")
        if strat not in positions_by_strategy:
            positions_by_strategy[strat] = []
        positions_by_strategy[strat].append(p)

    # 信号数据 — 从数据库读取最新信号（含阈值、因子、时间戳）
    signals_data = []
    strategy_names = ["M30_rsi_bb", "H1_v6_hybrid", "sanqing_h1", "gold_auto_research", "mtf_resonance_h1"]
    try:
        for s_name in strategy_names:
            sig = db.get_latest_signal(s_name)
            if sig:
                # 解析 JSON 字段
                fl = []
                fs = []
                iv = {}
                try:
                    fl = json.loads(sig.get("factors_long", "[]")) if isinstance(sig.get("factors_long"), str) else (sig.get("factors_long") or [])
                except (json.JSONDecodeError, TypeError):
                    fl = str(sig.get("factors_long", "")).split(",") if sig.get("factors_long") else []
                try:
                    fs = json.loads(sig.get("factors_short", "[]")) if isinstance(sig.get("factors_short"), str) else (sig.get("factors_short") or [])
                except (json.JSONDecodeError, TypeError):
                    fs = str(sig.get("factors_short", "")).split(",") if sig.get("factors_short") else []
                try:
                    iv = json.loads(sig.get("indicator_values", "{}")) if isinstance(sig.get("indicator_values"), str) else (sig.get("indicator_values") or {})
                except (json.JSONDecodeError, TypeError):
                    iv = {}
                threshold = sig.get("threshold", 0)
                score_long = sig.get("score_long", 0)
                score_short = sig.get("score_short", 0)
                signals_data.append({
                    "name": s_name,
                    "time": sig.get("timestamp", ""),
                    "signal": sig.get("signal"),
                    "score_long": score_long,
                    "score_short": score_short,
                    "threshold": threshold,
                    "threshold_reached": score_long >= threshold or score_short >= threshold,
                    "is_buy_reached": score_long >= threshold if threshold > 0 else False,
                    "is_sell_reached": score_short >= threshold if threshold > 0 else False,
                    "factors_long": fl,
                    "factors_short": fs,
                    "indicator_values": iv,
                    "status": sig.get("status", ""),
                    "void_reason": sig.get("void_reason", ""),
                    "ticket": sig.get("ticket"),
                })
    except Exception:
        pass

    # 风控状态 — strategy_blocks
    strategy_blocks = []
    try:
        from dashboard.backend.routes.engine import engine_runner as er
        if er and hasattr(er, '_engine') and er._engine:
            eng = er._engine
            if hasattr(eng, '_risk_states'):
                for magic, state in eng._risk_states.items():
                    blocks = []
                    if state.get("realized_loss_blocked"):
                        blocks.append("realized_loss")
                    if state.get("floating_loss_blocked"):
                        blocks.append("floating_loss")
                    if state.get("rapid_exit_blocked"):
                        blocks.append("rapid_exit")
                    if state.get("consecutive_loss_blocked"):
                        blocks.append("consecutive_loss")
                    strategy_blocks.append({
                        "magic": magic,
                        "strategy": state.get("strategy", ""),
                        "blocks": blocks,
                        "realized_pnl": state.get("realized_pnl", 0),
                        "consecutive_losses": state.get("consecutive_losses", 0),
                    })
    except Exception:
        pass

    # 最近交易（从 trades 表拉取）
    recent_trades = db.get_trades(limit=3)

    # 汇总摘要文本
    pnl_str = f"+${daily_pnl:.2f}" if daily_pnl >= 0 else f"-${abs(daily_pnl):.2f}"
    summary_parts = [
        f"运行正常" if engine_ok else "引擎异常",
        f"余额 ${account.get('balance', 0):.2f}",
        f"持仓 {len(positions)} 单",
        pnl_str,
    ]
    summary = " · ".join(summary_parts)

    sections = [
        {
            "type": "engine",
            "title": "运行状态",
            "data": {
                "verdict": verdict,
                "status": "运行中" if engine_ok else "已停止",
                "bridge": "已连接" if bridge_ok else "断开",
                "uptime": uptime,
                "started_at": status.get("started_at", ""),
            },
        },
        {
            "type": "account",
            "title": "账户概况",
            "data": {
                "balance": account.get("balance", 0),
                "equity": account.get("equity", 0),
                "margin": account.get("margin", 0),
                "free_margin": account.get("free_margin", 0),
                "floating_pnl": round(floating_pnl, 2),
                "daily_pnl": round(daily_pnl, 2),
                "currency": account.get("currency", "USD"),
            },
        },
        {
            "type": "positions",
            "title": f"持仓 ({len(positions)} 张)",
            "data": positions,
            "by_strategy": positions_by_strategy,
        },
        {
            "type": "signals",
            "title": "策略信号",
            "data": signals_data,
        },
        {
            "type": "risk",
            "title": "风控状态",
            "data": {
                "daily_pnl": round(daily_pnl, 2),
                "daily_drawdown": risk_info.get("daily_drawdown", 0),
                "strategy_blocks": strategy_blocks,
            },
        },
        {
            "type": "market",
            "title": "行情快照",
            "data": {
                "bid": price.get("bid", 0),
                "ask": price.get("ask", 0),
                "spread": round(price.get("ask", 0) - price.get("bid", 0), 2) if price.get("bid") and price.get("ask") else 0,
            },
        },
    ]

    # 如果有最近成交，添加成交卡片
    if recent_trades:
        sections.append({
            "type": "trades",
            "title": "最近成交",
            "data": recent_trades,
        })

    # News-Bias 评估
    try:
        from services.news_bias import NewsBiasEvaluator
        evaluator = NewsBiasEvaluator()
        evaluator.evaluate_past_events(hours=6)
        news_data = evaluator.get_report_data(hours=24)
        if news_data.get("enabled") and news_data.get("total", 0) > 0:
            sections.append({
                "type": "news_bias",
                "title": f"News-Bias 评估 ({news_data['directional']}笔 / {news_data['accuracy']}%准确)",
                "data": news_data,
            })
    except Exception:
        pass

    return {
        "sections": sections,
        "generated_at": now,
        "summary": summary,
        "account_balance": account.get("balance", 0),
        "account_equity": account.get("equity", 0),
        "floating_pnl": round(floating_pnl, 2),
        "daily_pnl": round(daily_pnl, 2),
        "position_count": len(positions),
    }


def _build_weekly_report(target_date: str = "") -> dict:
    """生成指定日期的周报，汇总当天交易情况"""
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")

    from_date = f"{target_date} 00:00:00"
    to_date = f"{target_date} 23:59:59"

    # 获取当天所有成交
    all_trades = db.get_trades(limit=10000)
    day_trades = [t for t in all_trades if from_date[:10] == str(t.get("close_time", ""))[:10]]

    # 统计
    total_pnl = sum(t.get("pnl", 0) + t.get("swap", 0) - abs(t.get("commission", 0)) for t in day_trades)
    count = len(day_trades)
    wins = sum(1 for t in day_trades if t.get("pnl", 0) > 0)
    losses = sum(1 for t in day_trades if t.get("pnl", 0) <= 0)
    win_rate = round(wins / count * 100, 1) if count else 0

    best = max((t.get("pnl", 0) for t in day_trades), default=0)
    worst = min((t.get("pnl", 0) for t in day_trades), default=0)

    # 按策略分组
    by_strategy = {}
    for t in day_trades:
        strat = t.get("strategy", "unknown")
        if strat not in by_strategy:
            by_strategy[strat] = {"pnl": 0, "count": 0, "wins": 0}
        by_strategy[strat]["pnl"] += t.get("pnl", 0)
        by_strategy[strat]["count"] += 1
        if t.get("pnl", 0) > 0:
            by_strategy[strat]["wins"] += 1

    for s in by_strategy.values():
        s["win_rate"] = round(s["wins"] / s["count"] * 100, 1) if s["count"] else 0
        s["pnl"] = round(s["pnl"], 2)

    pnl_str = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
    summary = f"{target_date} · {count} 笔 · 盈亏 {pnl_str} · 胜率 {win_rate}%"

    sections = [
        {
            "type": "weekly_summary",
            "title": f"交易汇总 - {target_date}",
            "data": {
                "date": target_date,
                "total_pnl": round(total_pnl, 2),
                "count": count,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "best": round(best, 2),
                "worst": round(worst, 2),
            },
        },
        {
            "type": "by_strategy",
            "title": "按策略分组",
            "data": by_strategy,
        },
    ]

    if day_trades:
        sections.append({
            "type": "trades",
            "title": f"成交明细 ({count} 笔)",
            "data": day_trades,
        })

    return {
        "sections": sections,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary,
        "daily_pnl": round(total_pnl, 2),
        "position_count": count,
    }


def _gather_daily_report() -> dict:
    """生成日报内容并写入数据库。返回报告 id"""
    content = _build_daily_report()
    record = {
        "type": "daily",
        "title": f"XAUUSD 状态报告 - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "summary": content.get("summary", ""),
        "content": json.dumps(content, ensure_ascii=False, default=str),
        "account_balance": content.get("account_balance", 0),
        "account_equity": content.get("account_equity", 0),
        "floating_pnl": content.get("floating_pnl", 0),
        "daily_pnl": content.get("daily_pnl", 0),
        "position_count": content.get("position_count", 0),
    }
    report_id = db.insert_report(record)
    return report_id


def _gather_weekly_report(target_date: str = "") -> dict:
    """生成周报并写入数据库。返回报告 id"""
    content = _build_weekly_report(target_date)
    record = {
        "type": "weekly",
        "title": f"XAUUSD 交易周报 - {target_date}",
        "summary": content.get("summary", ""),
        "content": json.dumps(content, ensure_ascii=False, default=str),
        "daily_pnl": content.get("daily_pnl", 0),
        "position_count": content.get("position_count", 0),
    }
    report_id = db.insert_report(record)
    return report_id


# ── REST 端点 ─────────────────────────────────────────────

@router.get("")
async def list_reports(
    type: str = Query("daily", description="报告类型: daily / weekly"),
    date_from: str = Query("", description="开始日期 YYYY-MM-DD"),
    date_to: str = Query("", description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """获取报告列表"""
    rows = db.get_reports(type=type, date_from=date_from, date_to=date_to,
                          page=page, page_size=page_size)
    total = len(rows)
    return {"data": rows, "page": page, "page_size": page_size, "total": total}


@router.get("/{report_id}")
async def get_report(report_id: int):
    """获取单条报告的完整内容"""
    report = db.get_report(report_id)
    if not report:
        raise HTTPException(404, f"报告 {report_id} 不存在")
    # content 是 JSON 字符串，解析为对象
    if isinstance(report.get("content"), str):
        try:
            report["content"] = json.loads(report["content"])
        except (json.JSONDecodeError, TypeError):
            pass
    return report


@router.get("/timeline/{date}")
async def get_timeline(
    date: str,
    type: str = Query("daily", description="报告类型: daily / weekly"),
):
    """获取指定日期的时间轴"""
    rows = db.get_report_timeline(date=date, type=type)
    return {"date": date, "type": type, "data": rows}


@router.post("/generate")
async def generate_report(
    type: str = Query("daily", description="报告类型: daily / weekly"),
    date: str = Query("", description="周报目标日期 YYYY-MM-DD"),
):
    """手动触发生成报告"""
    if not engine_runner:
        raise HTTPException(400, "服务未初始化")
    try:
        if type == "weekly":
            report_id = _gather_weekly_report(target_date=date)
        else:
            report_id = _gather_daily_report()
        if not report_id:
            raise HTTPException(500, "生成报告失败: 数据库写入失败")
        report = db.get_report(report_id)
        if report and isinstance(report.get("content"), str):
            try:
                report["content"] = json.loads(report["content"])
            except (json.JSONDecodeError, TypeError):
                pass
        return {"id": report_id, "report": report}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"生成报告失败: {e}")
