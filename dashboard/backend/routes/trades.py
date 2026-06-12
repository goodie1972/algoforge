"""
/api/trades 路由 - 历史成交记录查询 & 策略收益统计
"""
import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException
from data import database as db

router = APIRouter(prefix="/api/trades", tags=["trades"])

engine_runner = None
run_bridge = None
logger = logging.getLogger(__name__)

MAGIC_TO_STRATEGY = {
    # 新版 magic (PPNNVV)
    660701: "M30_rsi_bb", 660702: "M30_rsi_bb", 660703: "M30_rsi_bb", 660704: "M30_rsi_bb",
    660601: "H1_v6_hybrid", 660602: "H1_v6_hybrid", 660603: "H1_v6_hybrid", 660604: "H1_v6_hybrid",
    880101: "sanqing_h1", 880102: "sanqing_h1", 880103: "sanqing_h1", 880104: "sanqing_h1",
    880301: "gold_auto_research", 880302: "gold_auto_research", 880303: "gold_auto_research",
    880304: "gold_auto_research", 880305: "gold_auto_research",
    # 旧版 magic 兼容
    777001: "M30_rsi_bb", 777002: "H1_v6_hybrid", 777003: "gold_auto_research",
}

# 4位 PPNN → 策略名（用于 by_strategy 分组）
PPNN_TO_STRATEGY = {
    "6607": "M30_rsi_bb",
    "6606": "H1_v6_hybrid",
    "8801": "sanqing_h1",
    "8803": "gold_auto_research",
}


def _resolve_strategy_name(magic: int, fallback: str = "") -> str:
    """从 settings 策略池或静态映射表解析魔术号对应的策略名"""
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
    try:
        from config import settings
        pool = getattr(settings, 'STRATEGY_POOL', {})
        for name, cfg in pool.items():
            if cfg.get("magic") == magic:
                return name
    except Exception:
        pass
    # 静态映射表兜底
    name = MAGIC_TO_STRATEGY.get(magic)
    if name:
        return name
    return fallback or f"magic_{magic}"


# ── 辅助函数 ──────────────────────────────────────────

def _empty_stats() -> dict:
    return {
        "total_net_profit": 0, "gross_profit": 0, "gross_loss": 0,
        "profit_factor": "N/A", "expected_payoff": 0,
        "total_trades": 0, "short_trades": 0, "short_won": 0, "short_won_pct": 0,
        "long_trades": 0, "long_won": 0, "long_won_pct": 0,
        "profit_trades": 0, "loss_trades": 0, "win_rate": 0,
        "largest_profit_trade": 0, "largest_loss_trade": 0,
        "avg_profit_trade": 0, "avg_loss_trade": 0, "ratio_avg_profit_loss": 0,
        "avg_hold_seconds": 0, "max_consecutive_wins": 0, "max_consecutive_losses": 0,
        "max_consecutive_wins_pnl": 0, "max_consecutive_losses_pnl": 0,
        "total_commission": 0, "total_swap": 0,
    }


def _is_buy(order_type: str) -> bool:
    return order_type.upper() in ("BUY", "OP_BUY")


def _calc_stats(trades: list[dict]) -> dict:
    """计算 MT4 标准统计指标"""
    if not trades:
        return _empty_stats()

    total = len(trades)

    # 多空统计
    long_trades = sum(1 for t in trades if _is_buy(t.get("order_type", "")))
    short_trades = total - long_trades
    long_won = sum(1 for t in trades if _is_buy(t.get("order_type", "")) and t.get("pnl", 0) > 0)
    short_won = sum(1 for t in trades if not _is_buy(t.get("order_type", "")) and t.get("pnl", 0) > 0)

    # 盈亏统计
    profit_list = [t for t in trades if t.get("pnl", 0) > 0]
    loss_list = [t for t in trades if t.get("pnl", 0) <= 0]
    profit_count = len(profit_list)
    loss_count = len(loss_list)

    gross_profit = round(sum(t["pnl"] for t in profit_list), 2)
    gross_loss = round(sum(t["pnl"] for t in loss_list), 2)
    total_net_profit = round(sum(t.get("pnl", 0) for t in trades), 2)

    # Profit Factor
    abs_gross_loss = abs(gross_loss)
    if abs_gross_loss == 0:
        profit_factor = "∞" if gross_profit > 0 else "N/A"
    else:
        profit_factor = round(gross_profit / abs_gross_loss, 2)

    # 单笔统计
    largest_profit = max((t.get("pnl", 0) for t in profit_list), default=0)
    largest_loss = min((t.get("pnl", 0) for t in loss_list), default=0)
    avg_profit = round(sum(t["pnl"] for t in profit_list) / profit_count, 2) if profit_count else 0
    avg_loss = round(sum(t["pnl"] for t in loss_list) / loss_count, 2) if loss_count else 0
    ratio_avg = round(avg_profit / abs(avg_loss), 2) if avg_loss != 0 else 0

    # 持仓时间
    hold_secs = [t.get("hold_seconds", 0) for t in trades if t.get("hold_seconds")]
    avg_hold = round(sum(hold_secs) / len(hold_secs)) if hold_secs else 0

    # 连续盈亏
    sorted_trades = sorted(trades, key=lambda t: str(t.get("close_time", "")))
    max_cw = max_cl = 0
    max_cw_pnl = max_cl_pnl = 0
    cur_w = cur_l = 0
    cur_w_pnl = cur_l_pnl = 0.0
    for t in sorted_trades:
        pnl = t.get("pnl", 0)
        if pnl > 0:
            cur_w += 1
            cur_l = 0
            cur_w_pnl += pnl
            cur_l_pnl = 0
            if cur_w > max_cw:
                max_cw = cur_w
                max_cw_pnl = round(cur_w_pnl, 2)
        else:
            cur_l += 1
            cur_w = 0
            cur_l_pnl += pnl
            cur_w_pnl = 0
            if cur_l > max_cl:
                max_cl = cur_l
                max_cl_pnl = round(cur_l_pnl, 2)

    # 佣金 & swap
    total_commission = round(sum(t.get("commission", 0) for t in trades), 2)
    total_swap = round(sum(t.get("swap", 0) for t in trades), 2)

    return {
        "total_net_profit": total_net_profit,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "expected_payoff": round(total_net_profit / total, 2) if total else 0,
        "total_trades": total,
        "short_trades": short_trades,
        "short_won": short_won,
        "short_won_pct": round(short_won / short_trades * 100, 1) if short_trades else 0,
        "long_trades": long_trades,
        "long_won": long_won,
        "long_won_pct": round(long_won / long_trades * 100, 1) if long_trades else 0,
        "profit_trades": profit_count,
        "loss_trades": loss_count,
        "win_rate": round(profit_count / total * 100, 1) if total else 0,
        "largest_profit_trade": round(largest_profit, 2),
        "largest_loss_trade": round(largest_loss, 2),
        "avg_profit_trade": avg_profit,
        "avg_loss_trade": avg_loss,
        "ratio_avg_profit_loss": ratio_avg,
        "avg_hold_seconds": avg_hold,
        "max_consecutive_wins": max_cw,
        "max_consecutive_losses": max_cl,
        "max_consecutive_wins_pnl": max_cw_pnl,
        "max_consecutive_losses_pnl": max_cl_pnl,
        "total_commission": total_commission,
        "total_swap": total_swap,
    }


# ── 历史成交 ──────────────────────────────────────────

@router.get("/history")
async def get_trade_history(limit: int = 100):
    """获取最近 N 条已平仓记录（从 SQLite 读取，按平仓时间倒序）"""
    try:
        trades = db.get_trades(limit=limit)
        return trades
    except Exception as e:
        raise HTTPException(502, f"获取历史成交失败: {e}")


# ── 策略收益统计（MT4 标准报表格式）────────────────────

@router.get("/stats")
async def get_trade_stats(strategies: str = "", from_date: str = "", to_date: str = ""):
    """策略收益统计（透视表），从 SQLite 读取"""
    trades = db.get_trades(limit=10000)

    # 按策略名筛选
    if strategies:
        strat_list = [s.strip() for s in strategies.split(",") if s.strip()]
        trades = [t for t in trades if t.get("strategy", "") in strat_list]

    # 按 close_time 日期范围筛选
    if from_date:
        trades = [t for t in trades if str(t.get("close_time", ""))[:10] >= from_date[:10]]
    if to_date:
        trades = [t for t in trades if str(t.get("close_time", ""))[:10] <= to_date[:10]]

    # 汇总
    summary = _calc_stats(trades)

    # 分策略（按魔术号分组）
    by_magic = {}
    magic_set = sorted(set(t.get("magic") for t in trades if t.get("magic") is not None))
    for magic in magic_set:
        s_trades = [t for t in trades if t.get("magic") == magic]
        strategy_name = _resolve_strategy_name(magic)
        if strategy_name.startswith("magic_"):
            s_trades_sorted = sorted(s_trades, key=lambda t: str(t.get("close_time", "")), reverse=True)
            strategy_name = s_trades_sorted[0].get("strategy", f"magic_{magic}")
        stats = _calc_stats(s_trades)
        stats["magic"] = magic
        stats["strategy"] = strategy_name
        by_magic[str(magic)] = stats

    # 分策略族（按4位PPNN分组，versions按6位magic细分）
    by_strategy = {}
    for magic_key, version_stats in by_magic.items():
        magic = int(magic_key)
        magic_str = str(magic)
        if len(magic_str) == 6 and magic_str[:4] in PPNN_TO_STRATEGY:
            group_key = magic_str[:4]
            strategy_name = PPNN_TO_STRATEGY[group_key]
        else:
            strategy_name = version_stats.get("strategy") or _resolve_strategy_name(magic)
            group_key = magic_str[:4] if len(magic_str) >= 4 else magic_str

        if strategy_name not in by_strategy:
            family_trades = [
                t for t in trades
                if _resolve_strategy_name(t.get("magic", 0), t.get("strategy", "")) == strategy_name
            ]
            family_stats = _calc_stats(family_trades)
            family_stats["magic"] = group_key
            family_stats["strategy"] = strategy_name
            family_stats["versions"] = []
            by_strategy[strategy_name] = family_stats

        version_item = dict(version_stats)
        version_item["version"] = f"v{magic % 100:02d}" if len(magic_str) == 6 else "legacy"
        by_strategy[strategy_name]["versions"].append(version_item)

    for stats in by_strategy.values():
        stats["versions"].sort(key=lambda x: x.get("magic", 0))

    return {"summary": summary, "by_magic": by_magic, "by_strategy": by_strategy}


# ── 从 MT4 恢复历史成交 ───────────────────────────────

@router.post("/recover")
async def recover_trades():
    """从 MT4 拉取全部历史成交，补写缺失记录到 closed_trades.jsonl"""
    if not engine_runner or not engine_runner.bridge or not engine_runner.is_running:
        raise HTTPException(400, "引擎未运行或桥接未连接")

    engine = engine_runner._engine
    if not engine:
        raise HTTPException(400, "引擎未初始化")

    try:
        orders = await run_bridge(engine_runner.bridge.get_order_history, "XAUUSD")
    except Exception as e:
        raise HTTPException(502, f"从 MT4 获取历史成交失败: {e}")

    if not orders:
        return {"recovered": 0, "message": "MT4 无历史成交记录"}

    existing_tickets = {t["ticket"] for t in engine._closed_trades}
    missing = [o for o in orders if o["ticket"] not in existing_tickets]

    if not missing:
        return {"recovered": 0, "message": "所有历史成交已入库，无需补充"}

    records = []
    for order in missing:
        magic = order["magic"]
        strategy = _resolve_strategy_name(magic)
        open_dt = datetime.fromtimestamp(order["open_time"])
        close_dt = datetime.fromtimestamp(order["close_time"])
        hold_sec = int(order["close_time"] - order["open_time"])

        record = {
            "ticket": order["ticket"],
            "symbol": order["symbol"],
            "order_type": order["order_type"],
            "volume": order["volume"],
            "entry_price": order["open_price"],
            "exit_price": order["close_price"],
            "pnl": round(order["profit"], 2),
            "stop_loss": order["stop_loss"],
            "take_profit": order["take_profit"],
            "swap": round(order["swap"], 2),
            "commission": round(order["commission"], 2),
            "magic": magic,
            "strategy": strategy,
            "open_time": open_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "close_time": close_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "hold_seconds": hold_sec,
            "exit_reason": "mt4_history",
        }
        records.append(record)
        engine._closed_trades.append(record)

    trades_file = engine._trades_file
    try:
        with open(trades_file, "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError as e:
        raise HTTPException(500, f"写入成交记录文件失败: {e}")

    total_pnl = sum(r["pnl"] for r in records)
    buy_count = sum(1 for r in records if _is_buy(r["order_type"]))
    sell_count = len(records) - buy_count

    logger.info(
        f"成交恢复: {len(records)} 条 "
        f"(多 {buy_count} 空 {sell_count}) "
        f"总盈亏 ${total_pnl:.2f}"
    )

    return {
        "recovered": len(records),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "total_pnl": round(total_pnl, 2),
        "records": records,
    }


# ── 交易分析 ──────────────────────────────────────────

def _analyze_entry_m30_rsi_bb(direction: str, entry_price: float) -> dict:
    """M30_rsi_bb 开仓逻辑分析"""
    factors = [
        ("H1 趋势", "H1 SMA200 判断趋势方向，顺势 +1 分"),
        ("BB 触轨", "价格触及布林带上轨(空)/下轨(多) +1 分"),
        ("RSI 极端", "RSI 超买(>65)/超卖(<30) +1 分"),
        ("M30 RSI 方向", "M30 RSI 上升(多)/下降(空) +1 分"),
        ("低波动率", "ATR < 均价×2.5% 时 +1 分"),
    ]
    threshold = 3
    likely = []
    if direction == "SELL":
        likely = ["H1 趋势 DOWN", "BB 上轨触轨", "RSI 超买区域"]
    else:
        likely = ["H1 趋势 UP", "BB 下轨触轨", "RSI 超卖区域"]
    return {
        "system": "5因子评分系统，评分 ≥ 3 触发",
        "threshold": threshold,
        "factors": [{"name": f, "desc": d} for f, d in factors],
        "likely_conditions": likely,
    }


def _analyze_entry_sanqing_h1(direction: str, entry_price: float) -> dict:
    """sanqing_h1 开仓逻辑分析"""
    return {
        "system": "6因子评分系统，评分 ≥ 5 触发",
        "threshold": 5,
        "factors": [
            ("EMA9/21 趋势", "多头排列 +2 / 空头排列 +2 / 金叉死叉 +1"),
            ("EMA9 支撑/阻力", "价格回踩 EMA9 不破(多)/反弹 EMA9 不过(空) +2"),
            ("实体/ATR 比值", "K线实体 > 1.0 ATR +1"),
            ("成交量放大", "成交量 > 21日均量×1.3 +1"),
            ("K线实体扩张", "实体 > 5日均量中位数×1.5 +2"),
        ],
        "likely_conditions": [
            "EMA9/21 空头排列" if direction == "SELL" else "EMA9/21 多头排列",
            "价格测试 EMA9 阻力" if direction == "SELL" else "价格回踩 EMA9 支撑",
        ],
    }


def _analyze_entry_h1_v6_hybrid(direction: str, entry_price: float) -> dict:
    """H1_v6_hybrid 开仓逻辑分析"""
    return {
        "system": "8因子评分系统（仅做多），评分 ≥ 3 触发",
        "threshold": 3,
        "factors": [
            ("H1 EMA20 斜率", "EMA20 上行趋势 +2"),
            ("M30 RSI 方向", "RSI 从低位回升 +1"),
            ("K线形态", "看涨吞没/锤子线等 +1"),
            ("成交量确认", "放量上涨 +1"),
            ("ATR 波动率", "低波动后启动 +1"),
        ],
        "likely_conditions": ["H1 上行趋势", "RSI 从低位回升", "EMA20 斜率向上"],
    }


def _analyze_entry_gold_auto_research(direction: str, entry_price: float) -> dict:
    """gold_auto_research 开仓逻辑分析"""
    return {
        "system": "多因子评分系统",
        "factors": [
            ("趋势跟踪", "EMA 均线排列判断方向"),
            ("动量确认", "RSI/MACD 确认动能"),
            ("波动率过滤", "ATR 控制入场时机"),
        ],
        "likely_conditions": [
            "EMA 空头排列" if direction == "SELL" else "EMA 多头排列",
            "RSI 确认动能方向",
        ],
    }


def _analyze_exit(exit_reason: str, pnl: float, direction: str, strategy_name: str) -> dict:
    """平仓逻辑分析"""
    analyses = {
        "strategy_exit": {
            "label": "策略出场",
            "logic": "ATR 动态出场系统：①利润回撤止盈(peak→25%回撤) ②ATR 移动止盈(trail_mult) ③硬止损(hard_mult)",
            "exit_trigger": "未知",
        },
        "mt4_history": {
            "label": "MT4 历史恢复",
            "logic": "该单由 MT4 历史记录恢复，非当前引擎决策平仓",
            "exit_trigger": "引擎接管时已在 MT4 中平仓",
        },
        "ema20_trail": {
            "label": "EMA20 追踪止损",
            "logic": "旧版 EMA20 追踪止损出场",
            "exit_trigger": "价格反向穿越 EMA20",
        },
    }
    result = analyses.get(exit_reason, {
        "label": exit_reason,
        "logic": "未知出场逻辑",
        "exit_trigger": "",
    })

    # 添加盈亏判断
    result["pnl"] = round(pnl, 2)
    result["is_loss"] = pnl < 0

    # 亏损单补充分析
    if pnl < 0:
        result["loss_analysis"] = _analyze_loss(pnl, strategy_name, direction, exit_reason)
    return result


def _analyze_loss(pnl: float, strategy: str, direction: str, exit_reason: str) -> dict:
    """亏损原因分析"""
    reasons = []
    suggestions = []

    if exit_reason == "strategy_exit":
        reasons.append("ATR 动态出场系统触发，未到硬止损水位即被移动止盈出场（旧版逻辑）")
        suggestions.append("【已修复】亏损状态下不再触发移动止盈，仅走硬止损")

        if "sanqing" in strategy or "M30_rsi" in strategy:
            if direction == "SELL":
                reasons.append("空单在 H1 下跌趋势中反弹被扫，ATR trail_mult=1.5 偏紧")
                suggestions.append("当前 H1 DOWN 趋势下 SELL 的 trail_mult 为 1.5（顺势偏松），\n"
                                  "但实际效果是亏损时也触发，已修复为仅盈利时追踪")
                suggestions.append("可考虑：H1 趋势强劲反弹时，适当增大首单 ATR 硬止损倍数")
            elif direction == "BUY":
                reasons.append("多单在上升趋势中回调被扫")
                suggestions.append("检查当前趋势状态，考虑顺趋势方向放宽 trail_mult")

    if exit_reason == "ema20_trail":
        reasons.append("EMA20 追踪止损被反向突破")
        suggestions.append("可考虑结合 ATR 动态调整 EMA20 通道宽度")

    # 根据策略补充建议
    if strategy == "M30_rsi_bb":
        suggestions.append("M30_rsi_bb 胜率较高(70%)但盈亏比偏低，关注单笔亏损控制")
    elif strategy == "sanqing_h1":
        suggestions.append("sanqing_h1 评分阈值较高(5)，关注信号精确性")
    elif strategy == "H1_v6_hybrid":
        suggestions.append("H1_v6_hybrid 仅做多，整体表现优秀(PF 28+)")

    return {
        "possible_reasons": reasons,
        "suggestions": list(set(suggestions)),
    }


@router.get("/analysis/{ticket}")
async def get_trade_analysis(ticket: int):
    """分析单笔成交的开仓/平仓逻辑及优化建议"""
    if not engine_runner or not engine_runner._engine:
        raise HTTPException(400, "引擎未运行")

    trades = list(engine_runner._engine.closed_trades)
    trade = None
    for t in trades:
        if t.get("ticket") == ticket:
            trade = t
            break

    if not trade:
        raise HTTPException(404, f"未找到成交记录 ticket={ticket}")

    strategy = trade.get("strategy", "未知")
    direction = trade.get("order_type", "未知")
    entry_price = trade.get("entry_price", 0)
    exit_price = trade.get("exit_price", 0)
    pnl = trade.get("pnl", 0)
    exit_reason = trade.get("exit_reason", "未知")
    hold_seconds = trade.get("hold_seconds", 0)
    magic = trade.get("magic", 0)
    sl = trade.get("stop_loss", 0)
    tp = trade.get("take_profit", 0)

    # 尝试从 indicator_snapshot 读取实际开仓/平仓数据
    snapshot_raw = trade.get("indicator_snapshot", "")
    if snapshot_raw:
        try:
            snapshot = json.loads(snapshot_raw) if isinstance(snapshot_raw, str) else snapshot_raw
        except (json.JSONDecodeError, TypeError):
            snapshot = {}
    else:
        snapshot = {}

    entry_factors = snapshot.get("entry_factors", {})
    exit_detail = snapshot.get("exit_detail", {})

    if entry_factors.get("long") or entry_factors.get("short"):
        scores = snapshot.get("scores", {})
        indicator_values = snapshot.get("indicator_values", {})
        factors_list = entry_factors.get("long", []) if "BUY" in direction.upper() else entry_factors.get("short", [])
        entry = {
            "system": "实时评分记录",
            "score_long": scores.get("long", 0),
            "score_short": scores.get("short", 0),
            "long_factors": entry_factors.get("long", []),
            "short_factors": entry_factors.get("short", []),
            "indicator_values": indicator_values,
            "likely_conditions": factors_list,
            "factors": [{"name": f, "desc": f} for f in factors_list],
        }
    else:
        strategy_lower = strategy.lower()
        if "m30_rsi" in strategy_lower or "rsi_bb" in strategy_lower:
            entry = _analyze_entry_m30_rsi_bb(direction, entry_price)
        elif "sanqing" in strategy_lower:
            entry = _analyze_entry_sanqing_h1(direction, entry_price)
        elif "v6_hybrid" in strategy_lower or str(magic).startswith("6606") or magic == 777002:
            entry = _analyze_entry_h1_v6_hybrid(direction, entry_price)
        elif "gold_auto" in strategy_lower or str(magic).startswith("8803") or magic == 777003:
            entry = _analyze_entry_gold_auto_research(direction, entry_price)
        else:
            entry = {"system": "未知策略", "likely_conditions": []}

    if exit_detail:
        exit_type = exit_detail.get("exit_type", "")
        exit_logic_map = {
            "profit_drawdown": "利润回撤止盈",
            "trail_stop": "ATR移动止盈",
            "hard_stop": "ATR硬止损",
        }
        direction_label = "空单" if "SELL" in direction.upper() else "多单"
        exit_info = {
            "label": "实时出场记录",
            "exit_detail": exit_detail,
            "logic": exit_logic_map.get(exit_type, f"策略出场({exit_type})"),
            "pnl": round(pnl, 2),
            "is_loss": pnl < 0,
        }
    else:
        exit_info = _analyze_exit(exit_reason, pnl, direction, strategy)

    result = {
        "ticket": ticket,
        "strategy": strategy,
        "magic": magic,
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "pnl": round(pnl, 2),
        "hold_seconds": hold_seconds,
        "sl": sl,
        "tp": tp,
        "entry_analysis": entry,
        "exit_analysis": exit_info,
    }

    if snapshot.get("indicator_values"):
        result["indicator_snapshot"] = snapshot

    return result
