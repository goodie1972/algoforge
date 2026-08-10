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


def _report_lang() -> str:
    """获取当前报表语言（zh/en）"""
    try:
        from core.runtime_config import RuntimeConfig
        lang = RuntimeConfig().get('language') or 'zh-CN'
        return 'zh' if str(lang).lower().startswith('zh') else 'en'
    except Exception:
        return 'zh'


def _report_t(section: str, lang: str = '') -> str:
    """报表章节标题翻译"""
    if not lang:
        lang = _report_lang()
    if lang == 'en':
        return {
            "运行状态": "Engine Status",
            "账户概况": "Account Overview",
            "持仓": "Positions",
            "策略信号": "Strategy Signals",
            "风控状态": "Risk Status",
            "行情快照": "Market Snapshot",
            "当日成交": "Today's Trades",
            "今日交易汇总": "Today's Summary",
            "按策略分组": "By Strategy",
            "黄金快讯评估": "Gold News Evaluation",
            "运行中": "Running",
            "已停止": "Stopped",
            "已连接": "Connected",
            "断开": "Disconnected",
            "运行正常": "Running normally",
            "引擎异常": "Engine error",
            "余额": "Balance",
            "张": "positions",
            "笔": "trades",
            "单": "orders",
        }.get(section, section)
    return section


def _build_daily_report() -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = engine_runner.get_status() if engine_runner else {}
    _raw = getattr(engine_runner, '_cached_account', None)
    account = _raw if isinstance(_raw, dict) else {}
    _raw = getattr(engine_runner, '_cached_positions', None)
    positions = _raw if isinstance(_raw, list) else []
    _raw = getattr(engine_runner, '_cached_price', None)
    price = _raw if isinstance(_raw, dict) else {}

    # 引擎状态
    engine_ok = status.get("status") == "running"
    bridge_ok = status.get("bridge_connected", False)
    uptime = _sec_to_hms(status.get("uptime_seconds", 0))
    verdict = "GREEN" if engine_ok else "RED"

    # 浮动盈亏
    floating_pnl = 0
    try:
        floating_pnl = sum(p.get("profit", 0) for p in positions)
    except Exception:
        pass

    # 当日盈亏（从 trades 表查询今日实际盈亏）
    daily_pnl = 0
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        rows = db.get_trades(limit=1000)
        daily_pnl = sum(r.get("pnl", 0) for r in rows if str(r.get("close_time", ""))[:10] == today)
    except Exception:
        pass

    # 持仓按策略分组
    positions_by_strategy = {}
    for p in positions:
        strat = p.get("strategy", "unknown")
        if strat not in positions_by_strategy:
            positions_by_strategy[strat] = []
        positions_by_strategy[strat].append(p)

    # 信号数据 — 从引擎内存实时读取（非 DB 历史）
    signals_data = []
    try:
        from dashboard.backend.routes.engine import engine_runner as er
        if er and hasattr(er, '_engine') and er._engine:
            engine = er._engine
            with engine._strategies_lock:
                strategies_snapshot = list(engine.strategies)
            for strategy in strategies_snapshot:
                last_sig = getattr(strategy, '_last_signal', None) or {}
                # 实时门禁状态
                _sig_price = strategy.candles[-1].close if strategy.candles else 0
                adx_data = strategy.get_adx_data()
                gate_buy = strategy.calc_gate_state("BUY", _sig_price, adx_data)
                gate_sell = strategy.calc_gate_state("SELL", _sig_price, adx_data)
                threshold = last_sig.get("threshold", getattr(strategy, "score_threshold", 3))
                score_long = last_sig.get("score_long", 0)
                score_short = last_sig.get("score_short", 0)
                signals_data.append({
                    "name": strategy.name,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "signal": last_sig.get("signal"),
                    "score_long": score_long,
                    "score_short": score_short,
                    "threshold": threshold,
                    "threshold_reached": score_long >= threshold or score_short >= threshold,
                    "is_buy_reached": score_long >= threshold if threshold > 0 else False,
                    "is_sell_reached": score_short >= threshold if threshold > 0 else False,
                    "factors_long": last_sig.get("factors_long", []),
                    "factors_short": last_sig.get("factors_short", []),
                    "indicator_values": last_sig.get("indicator_values", {}),
                    # 门禁状态（新增）
                    "gate_buy": gate_buy.get("details", {}),
                    "gate_sell": gate_sell.get("details", {}),
                    "gate_buy_blocked": gate_buy.get("blocked", False),
                    "gate_sell_blocked": gate_sell.get("blocked", False),
                })
    except Exception:
        pass

    # 风控状态 — 从 StrategyRiskState dataclass 读取
    strategy_blocks = []
    try:
        from dashboard.backend.routes.engine import engine_runner as er
        if er and hasattr(er, '_engine') and er._engine:
            eng = er._engine
            if hasattr(eng, '_risk_states'):
                for magic, state in eng._risk_states.items():
                    blocks = []
                    if state.realized_loss_blocked: blocks.append("realized_loss")
                    if state.floating_loss_blocked: blocks.append("floating_loss")
                    if state.rapid_exit_blocked: blocks.append("rapid_exit")
                    if state.consecutive_loss_blocked: blocks.append("consecutive_loss")
                    if state.realized_loss_amount_blocked: blocks.append("loss_amount")
                    strategy_blocks.append({
                        "magic": magic,
                        "strategy": state.name,
                        "blocks": blocks,
                        "realized_pnl": round(state.realized_pnl, 2),
                        "floating_pnl": round(state.floating_pnl, 2),
                        "consecutive_losses": state.consecutive_losses,
                    })
    except Exception:
        pass

    # 当日成交（按今天日期过滤）
    today_str = datetime.now().strftime("%Y-%m-%d")
    day_trades = []
    try:
        all_trades = db.get_trades(limit=200)
        day_trades = [t for t in all_trades if str(t.get("close_time", ""))[:10] == today_str]
    except Exception:
        pass

    # 汇总摘要文本
    pnl_str = f"+${daily_pnl:.2f}" if daily_pnl >= 0 else f"-${abs(daily_pnl):.2f}"
    summary_parts = [
        _report_t('运行正常', _report_lang()) if engine_ok else _report_t('引擎异常', _report_lang()),
        f"{_report_t('余额', _report_lang())} ${account.get('balance', 0):.2f}",
        f"{_report_t('持仓', _report_lang())} {len(positions)} {_report_t('单', _report_lang())}",
        pnl_str,
    ]
    summary = " · ".join(summary_parts)

    sections = [
        {
            "type": "engine",
            'title': _report_t('运行状态', _report_lang()),
            "data": {
                "verdict": verdict,
                'status': _report_t('运行中', _report_lang()) if engine_ok else _report_t('已停止', _report_lang()),
                'bridge': _report_t('已连接', _report_lang()) if bridge_ok else _report_t('断开', _report_lang()),
                "uptime": uptime,
                "started_at": status.get("started_at", ""),
            },
        },
        {
            "type": "account",
            'title': _report_t('账户概况', _report_lang()),
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
            'title': f"{_report_t('持仓', _report_lang())} ({len(positions)} {_report_t('张', _report_lang())})",
            "data": positions,
            "by_strategy": positions_by_strategy,
        },
        {
            "type": "signals",
            'title': _report_t('策略信号', _report_lang()),
            "data": signals_data,
        },
        {
            "type": "risk",
            'title': _report_t('风控状态', _report_lang()),
            "data": {
                "daily_pnl": round(daily_pnl, 2),
                "daily_drawdown": 0,
                "strategy_blocks": strategy_blocks,
            },
        },
        {
            "type": "market",
            'title': _report_t('行情快照', _report_lang()),
            "data": {
                "bid": price.get("bid", 0),
                "ask": price.get("ask", 0),
                "spread": round(price.get("ask", 0) - price.get("bid", 0), 2) if price.get("bid") and price.get("ask") else 0,
            },
        },
    ]

    # 如果有当日成交，添加成交卡片 + 交易汇总
    if day_trades:
        try:
            sections.append({
                "type": "trades",
                'title': f"{_report_t('当日成交', _report_lang())} ({len(day_trades)} {_report_t('笔', _report_lang())})",
                "data": day_trades,
            })
            day_wins = sum(1 for t in day_trades if t.get("pnl", 0) > 0)
            day_losses = sum(1 for t in day_trades if t.get("pnl", 0) <= 0)
            day_total_pnl = sum(t.get("pnl", 0) + t.get("swap", 0) - abs(t.get("commission", 0)) for t in day_trades)
            day_win_rate = round(day_wins / len(day_trades) * 100, 1) if day_trades else 0
            day_best = max((t.get("pnl", 0) for t in day_trades), default=0)
            day_worst = min((t.get("pnl", 0) for t in day_trades), default=0)
            # 按策略分组
            day_by_strategy = {}
            for t in day_trades:
                strat = t.get("strategy", "unknown")
                if strat not in day_by_strategy:
                    day_by_strategy[strat] = {"pnl": 0, "count": 0, "wins": 0}
                day_by_strategy[strat]["pnl"] += t.get("pnl", 0)
                day_by_strategy[strat]["count"] += 1
                if t.get("pnl", 0) > 0:
                    day_by_strategy[strat]["wins"] += 1
            for s in day_by_strategy.values():
                s["win_rate"] = round(s["wins"] / s["count"] * 100, 1) if s["count"] else 0
                s["pnl"] = round(s["pnl"], 2)
            sections.append({
                "type": "weekly_summary",
                'title': _report_t('今日交易汇总', _report_lang()),
                "data": {
                    "date": today_str,
                    "total_pnl": round(day_total_pnl, 2),
                    "count": len(day_trades),
                    "wins": day_wins,
                    "losses": day_losses,
                    "win_rate": day_win_rate,
                    "best": round(day_best, 2),
                    "worst": round(day_worst, 2),
                },
            })
            if day_by_strategy:
                sections.append({
                    "type": "by_strategy",
                    'title': _report_t('按策略分组', _report_lang()),
                    "data": day_by_strategy,
                })
        except Exception as e:
            logger.warning("[Report] todayfillsprocessfailed: %s", e)

    # 黄金快讯评估（新系统 — 汇通+金十+LLM）
    news_data = None
    try:
        from data import database as db
        eval_stats = db.get_gold_news_evaluation_stats()
        summary_stats = db.get_gold_news_summary()
        if summary_stats.get("total", 0) > 0:
            news_data = {
                "enabled": True,
                "total": summary_stats.get("total", 0),
                "directional": summary_stats.get("bullish", 0) + summary_stats.get("bearish", 0),
                "accuracy": eval_stats.get("accuracy", 0),
                "correct": eval_stats.get("correct", 0),
                "wrong": eval_stats.get("wrong", 0),
                "neutral": summary_stats.get("neutral", 0),
                "evaluations": [
                    {"event_title": (r.get("content_en") or r.get("content", ""))[:60],
                     "expected_bias": r.get("direction", ""),
                     "actual_move_15m": r.get("actual_move_15m", 0),
                     "actual_move_1h": r.get("actual_move_1h", 0),
                     "direction_match": "correct" if r.get("direction_match") == 1 else "wrong" if r.get("direction_match") == 0 else "unknown",
                     "source": r.get("source", ""),
                     }
                    for r in db.get_gold_news(limit=10, direction="")
                ],
            }
    except Exception:
        pass

    if news_data and news_data.get("total", 0) > 0:
        directional = news_data.get("directional", 0)
        accuracy = news_data.get("accuracy", 0)
        sections.append({
            "type": "news_bias",
            'title': f"{_report_t('黄金快讯评估', _report_lang())} ({directional} {_report_t('笔', _report_lang())} / {accuracy}%)",
            "data": news_data,
        })

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
            'title': _report_t('按策略分组', _report_lang()),
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
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    report_id = db.insert_report(record)
    return report_id


def _gather_weekly_report(target_date: str = "") -> dict:
    """生成周报并写入数据库。使用日报的完整内容，确保有历史记录可查看。"""
    content = _build_daily_report()
    # 日报内容已有完整引擎状态，用周报标题封装
    report_title = content.get("summary", "").split("·")[0].strip() if "·" in content.get("summary", "") else "XAUUSD 状态快照"
    record = {
        "type": "weekly",
        "title": f"{report_title} - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "summary": content.get("summary", ""),
        "content": json.dumps(content, ensure_ascii=False, default=str),
        "account_balance": content.get("account_balance", 0),
        "account_equity": content.get("account_equity", 0),
        "floating_pnl": content.get("floating_pnl", 0),
        "daily_pnl": content.get("daily_pnl", 0),
        "position_count": content.get("position_count", 0),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
    report_type: str = Query("daily", alias="type", description="报告类型: daily / weekly"),
    date: str = Query("", description="周报目标日期 YYYY-MM-DD"),
):
    """手动触发生成报告"""
    open("D:/backup/baobao/pythonprogram/xauusd/report_started.txt", "a").close()
    if not engine_runner:
        raise HTTPException(400, "服务未初始化")
    try:
        if report_type == "weekly":
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
        import traceback
        _err = traceback.format_exc()
        with open("D:\\backup\\baobao\\pythonprogram\\xauusd\\report_error.txt", "w") as _f:
            _f.write(_err)
        raise HTTPException(500, f"生成报告失败: {e}")
