# -*- coding: utf-8 -*-
"""
监督者系统 — 策略交易行为监督与分析
======================================
功能：
1. 实时追踪每笔开仓信息（策略、方向、价格、入场因子）
2. 平仓后自动分析交易质量，标记异常行为
3. 按策略统计健康度指标，生成告警
4. 运行时活跃持仓监控
"""

import json
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── 告警规则阈值 ───────────────────────────────────────
RULES = {
    "win_rate_warn": 40.0,          # 胜率低于此值告警（%）
    "win_rate_critical": 25.0,       # 胜率低于此值严重告警（%）
    "avg_loss_vs_win_ratio": 1.5,    # 平均亏损/平均盈利 > 此值告警
    "consecutive_losses_warn": 4,    # 连续亏损次数告警
    "quick_exit_ratio_warn": 0.3,    # 闪电单（<5min）占比告警
    "hard_stop_ratio_warn": 0.2,     # 硬止损占比告警
    "min_sample_size": 5,            # 最小分析样本数
    "di_gate_effectiveness_warn": 0.7,  # DI跳过止盈但最终亏损比例
    "profit_drawdown_warn": 0.5,     # 利润回撤止盈但亏损的比例
}


class TradeSupervisor:
    """策略交易监督器"""

    def __init__(self, closed_trades_file: str = None):
        self._alerts: list[dict] = []
        self._strategy_health: dict[str, dict] = {}
        self._open_trades: dict[int, dict] = {}  # ticket → 开仓快照
        self._closed_trades_file = closed_trades_file or (
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "logs", "closed_trades.jsonl")
        )
        self._analysis_cache: dict[str, dict] = {}
        self._last_analysis_time: float = 0

        # 加载已有告警
        self._load_alerts()

    # ── 公开接口 ─────────────────────────────────────

    def on_trade_open(self, ticket: int, strategy: str, magic: int,
                      direction: str, price: float, entry_data: dict):
        """记录开仓信息"""
        self._open_trades[ticket] = {
            "ticket": ticket,
            "strategy": strategy,
            "magic": magic,
            "direction": direction,
            "entry_price": price,
            "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "entry_factors": entry_data.get("entry_factors", {}),
            "indicator_values": entry_data.get("indicator_values", {}),
            "scores": entry_data.get("scores", {}),
            "entry_timestamp": time.time(),
        }
        logger.info(f"[监督者] 记录开仓 #{ticket} {strategy} {direction} @{price}")

    def on_trade_close(self, record: dict, exit_type: str = "strategy_exit"):
        """平仓后分析交易质量
        Args:
            record: 平仓记录 dict
            exit_type: 出场类型 (strategy_exit, hard_stop, breakeven, profit_drawdown 等)
        """
        ticket = record.get("ticket")
        strategy = record.get("strategy", "unknown")
        pnl = record.get("pnl", 0)
        exit_reason = record.get("exit_reason", exit_type)
        hold_seconds = record.get("hold_seconds", 0)

        # 清除活跃持仓记录
        self._open_trades.pop(ticket, None)

        # 分析这笔交易
        issues = self._analyze_single_trade(record)
        if issues:
            for issue in issues:
                self._add_alert(strategy, ticket, issue, record)

        # 重新计算策略健康度
        self._refresh_strategy_health(strategy)

    def get_strategy_health(self, strategy: str = None) -> dict:
        """获取策略健康度"""
        self._ensure_analysis()
        if strategy:
            return self._strategy_health.get(strategy, {})
        return dict(self._strategy_health)

    def get_alerts(self, since: float = 0, limit: int = 50) -> list[dict]:
        """获取告警列表"""
        result = []
        for a in reversed(self._alerts):
            if a["timestamp"] >= since:
                result.append(a)
            if len(result) >= limit:
                break
        return result

    def get_open_trades(self) -> list[dict]:
        """当前活跃持仓"""
        return list(self._open_trades.values())

    def get_overview(self, db_trades: list[dict] = None) -> dict:
        """全局概览"""
        self._ensure_analysis(db_trades)

        total = len(self._strategy_health)
        alert_count = sum(1 for s in self._strategy_health.values()
                          if s.get("alert_count", 0) > 0)
        healthy = total - alert_count

        return {
            "total_strategies": total,
            "healthy_strategies": healthy,
            "alerting_strategies": alert_count,
            "total_alerts": len(self._alerts),
            "recent_alerts": self.get_alerts(since=time.time() - 86400),
            "open_trades": len(self._open_trades),
            "all_health": self.get_strategy_health(),
        }

    def refresh_all(self, trades: list[dict] = None):
        """全量刷新分析"""
        self._ensure_analysis(trades)
        self._save_alerts()

    # ── 内部分析 ─────────────────────────────────────

    def _analyze_single_trade(self, record: dict) -> list[str]:
        """单笔交易质量检查"""
        issues = []
        pnl = record.get("pnl", 0)
        hold_seconds = record.get("hold_seconds", 0)
        exit_reason = record.get("exit_reason", "")
        strategy = record.get("strategy", "unknown")

        # 1. 闪电单亏损
        if hold_seconds < 300 and pnl < 0:
            issues.append(f"闪电亏损单: 持仓仅{hold_seconds}秒，亏损${abs(pnl):.2f}")

        # 2. 硬止损
        try:
            snap = json.loads(record.get("indicator_snapshot", "{}"))
        except (json.JSONDecodeError, TypeError):
            snap = {}
        exit_detail = snap.get("exit_detail", {})
        exit_type = exit_detail.get("exit_type", "")

        if exit_type == "hard_stop":
            issues.append(f"硬止损出场: 亏损${abs(pnl):.2f}")

        # 3. 利润回撤止盈但亏损
        if exit_type == "profit_drawdown" and pnl < 0:
            issues.append(f"利润回撤出场但亏损: ${pnl:.2f}")

        # 4. 保本出场但亏损（非小额亏损）
        if exit_type == "breakeven" and pnl < -5:
            issues.append(f"保本出场大额亏损: ${pnl:.2f}")

        # 5. MT4 强制平仓（非策略主动出场）
        if exit_reason == "mt4_history":
            issues.append(f"MT4自主平仓（非策略信号）: 盈亏${pnl:.2f}")

        # 6. 入场因子分析（信号与方向是否匹配）
        entry_factors = snap.get("entry_factors", {})
        scores = snap.get("scores", {})
        direction = record.get("order_type", "")
        if scores:
            long_score = scores.get("long", 0)
            short_score = scores.get("short", 0)
            if direction in ("BUY", "OP_BUY") and long_score < short_score:
                issues.append(f"多单但做多评分({long_score})低于做空评分({short_score})")
            if direction in ("SELL", "OP_SELL") and short_score < long_score:
                issues.append(f"空单但做空评分({short_score})低于做多评分({long_score})")

        return issues

    def _refresh_strategy_health(self, strategy_name: str):
        """重新计算单个策略健康度"""
        trades = self._load_trades_for_strategy(strategy_name)
        if not trades:
            return

        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        win_rate = len(wins) / len(trades) * 100 if trades else 0

        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(abs(t["pnl"]) for t in losses) / len(losses) if losses else 0

        # 连续亏损
        max_consec = 0
        cur = 0
        for t in sorted(trades, key=lambda x: x.get("open_time", "")):
            if t.get("pnl", 0) <= 0:
                cur += 1
                max_consec = max(max_consec, cur)
            else:
                cur = 0

        # 出场原因分布
        from collections import Counter
        reasons = Counter(t.get("exit_reason", "unknown") for t in trades)
        exit_types = Counter()
        hard_stop_count = 0
        for t in trades:
            try:
                snap = json.loads(t.get("indicator_snapshot", "{}"))
            except (json.JSONDecodeError, TypeError):
                snap = {}
            et = snap.get("exit_detail", {}).get("exit_type", "")
            if et:
                exit_types[et] += 1
            if et == "hard_stop":
                hard_stop_count += 1

        quick_trades = [t for t in trades if t.get("hold_seconds", 0) < 300]

        # 生成告警
        alert_count = 0
        alerts = []
        sample_ok = len(trades) >= RULES["min_sample_size"]

        if sample_ok and win_rate < RULES["win_rate_critical"]:
            alerts.append(f"胜率极低 ({win_rate:.1f}%)")
            alert_count += 2
        elif sample_ok and win_rate < RULES["win_rate_warn"]:
            alerts.append(f"胜率偏低 ({win_rate:.1f}%)")
            alert_count += 1

        if losses and wins and avg_loss > avg_win * RULES["avg_loss_vs_win_ratio"]:
            alerts.append(f"盈亏比倒挂 (均亏${avg_loss:.2f}/均盈${avg_win:.2f})")
            alert_count += 2

        if max_consec >= RULES["consecutive_losses_warn"]:
            alerts.append(f"连续亏损{max_consec}次")
            alert_count += 1

        qr = len(quick_trades) / len(trades) if trades else 0
        if sample_ok and qr > RULES["quick_exit_ratio_warn"]:
            alerts.append(f"闪电单占比{len(quick_trades)}/{len(trades)} ({qr*100:.0f}%)")
            alert_count += 1

        hr = hard_stop_count / len(trades) if trades else 0
        if sample_ok and hr > RULES["hard_stop_ratio_warn"]:
            alerts.append(f"硬止损占比{hard_stop_count}/{len(trades)} ({hr*100:.0f}%)")
            alert_count += 1

        # 判断健康状态
        if alert_count >= 3:
            status = "critical"
        elif alert_count >= 1:
            status = "warning"
        else:
            status = "healthy"

        self._strategy_health[strategy_name] = {
            "strategy": strategy_name,
            "status": status,
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "max_consecutive_losses": max_consec,
            "quick_exits": len(quick_trades),
            "hard_stops": hard_stop_count,
            "exit_reasons": dict(reasons),
            "exit_types": dict(exit_types),
            "alert_count": alert_count,
            "alerts": alerts,
            "updated_at": datetime.now().strftime("%H:%M:%S"),
        }

    def _ensure_analysis(self, trades: list[dict] = None):
        """确保所有策略已分析（缓存）"""
        now = time.time()
        if now - self._last_analysis_time < 30 and self._strategy_health:
            return

        if trades is None:
            trades = self._load_all_trades()

        # 清空并重新分析
        strategies = set(t.get("strategy", "unknown") for t in trades)
        for s in strategies:
            self._refresh_strategy_health(s)

        self._last_analysis_time = now

    def _load_all_trades(self) -> list[dict]:
        """从 JSONL 加载所有平仓记录"""
        trades = []
        try:
            if os.path.exists(self._closed_trades_file):
                with open(self._closed_trades_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                trades.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
        except Exception as e:
            logger.warning(f"[监督者] 加载成交文件失败: {e}")
        return trades

    def _load_trades_for_strategy(self, strategy: str) -> list[dict]:
        """加载指定策略的平仓记录"""
        all_trades = self._load_all_trades()
        return [t for t in all_trades if t.get("strategy") == strategy]

    def _add_alert(self, strategy: str, ticket: int, issue: str, record: dict):
        """添加告警记录"""
        alert = {
            "timestamp": time.time(),
            "time_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategy": strategy,
            "ticket": ticket,
            "issue": issue,
            "pnl": record.get("pnl", 0),
            "direction": record.get("order_type", ""),
            "entry_price": record.get("entry_price", 0),
            "exit_price": record.get("exit_price", 0),
            "hold_seconds": record.get("hold_seconds", 0),
        }
        self._alerts.append(alert)

        # 保留最近 500 条
        if len(self._alerts) > 500:
            self._alerts = self._alerts[-500:]

        logger.warning(f"[监督者告警] {strategy} #{ticket}: {issue}")

    # ── 公开查询方法 ─────────────────────────────────

    def analyze_strategy(self, strategy_name: str) -> dict:
        """对外：分析单策略详情（含所有交易明细分析）"""
        trades = self._load_trades_for_strategy(strategy_name)
        analysis = self._strategy_health.get(strategy_name, {
            "strategy": strategy_name,
            "status": "unknown",
            "total_trades": len(trades),
        })
        analysis["recent_trades"] = trades[-20:] if trades else []
        return analysis

    def clear_alerts(self):
        """对外：清除所有告警"""
        self._alerts.clear()
        self._save_alerts()

    @property
    def trade_events(self) -> list:
        """对外：交易事件流（按时间排序的开平仓事件）"""
        events = []
        for ticket, ot in self._open_trades.items():
            events.append({
                "ticket": ticket,
                "strategy": ot["strategy"],
                "event": "open",
                "direction": ot["direction"],
                "price": ot["entry_price"],
                "time": ot["entry_time"],
            })
        return events

    # ── 持久化 ───────────────────────────────────────

    def _save_alerts(self):
        """持久化告警"""
        try:
            alerts_file = os.path.join(
                os.path.dirname(self._closed_trades_file), "supervisor_alerts.json"
            )
            with open(alerts_file, "w", encoding="utf-8") as f:
                json.dump(self._alerts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[监督者] 持久化告警失败: {e}")

    def _load_alerts(self):
        """加载持久化告警"""
        try:
            alerts_file = os.path.join(
                os.path.dirname(self._closed_trades_file), "supervisor_alerts.json"
            )
            if os.path.exists(alerts_file):
                with open(alerts_file, "r", encoding="utf-8") as f:
                    self._alerts = json.load(f)
                logger.info(f"[监督者] 加载 {len(self._alerts)} 条历史告警")
        except Exception as e:
            logger.warning(f"[监督者] 加载历史告警失败: {e}")
