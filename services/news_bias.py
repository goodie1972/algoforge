"""
News Bias 评估服务 — 观察模式
================================
对新闻事件打方向标签（利多/利空黄金），记录实际行情走势，
事后比对预测准确率。不影响任何交易决策。

用法：
  from services.news_bias import NewsBiasEvaluator
  evaluator = NewsBiasEvaluator()
  evaluator.evaluate_past_events(hours=6)  # 评估过去 N 小时的事件
  report_data = evaluator.get_report_data()  # 取报告用数据
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional

from config.settings import LOCAL_TZ
from services.news_filter import NewsFilter

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 事件分类规则 V2 — 预期差逻辑
# ═══════════════════════════════════════════════════════════════
# 核心原则：
#  1. 经济数据类事件（NFP/CPI/GDP/Retail Sales 等）的方向取决于
#     「实际值 vs 预期值」的偏差，不硬编码方向。
#  2. 有 actual/forecast 时 → 用预期差判断
#  3. 无 actual 时 → 返回 neutral（不赌方向）
#  4. 只有纯方向事件（地缘、灾害等）用关键词表
# ═══════════════════════════════════════════════════════════════

# 依赖实际数据的「经济数据类」事件关键词
# 当 actual 不可用时，返回 neutral 而非硬编码
ECONOMIC_DATA_KW = [
    "cpi", "consumer price", "producer price", "ppi",
    "nfp", "non-farm", "non farm", "payrolls",
    "gdp", "retail sales", "industrial production",
    "consumer confidence", "consumer sentiment",
    "unemployment", "jobless claims", "jobless",
    "housing starts", "building permits", "durable goods",
    "trade balance", "philadelphia fed", "empire state",
    "ism", "inflation", "core inflation",
    "uom", "michigan",
]

# 纯方向事件（不依赖实际数据，地缘/政策/央行动作等）
# 格式: (关键词列表, 方向, 原因说明)
DIRECTIONAL_PATTERNS = [
    # 地缘紧张 → 避险 → 黄金↑
    (["war", "sanction", "conflict", "missile", "attack", "invasion",
      "military strike", "hostility", "nuclear test", "terror"], "bullish", "地缘紧张→避险→黄金↑"),
    # 地缘缓和 → 避险消退 → 黄金↓
    (["ceasefire", "truce", "peace agreement", "de-escalat", "withdraw",
      "negotiation", "diplomatic solution"], "bearish", "地缘缓和→避险消退→黄金↓"),
    # 央行加息 → 利空黄金
    (["rate hike", "tightening", "raise rate", "lift-off"], "bearish", "加息→利空黄金"),
    # 央行降息 → 利多黄金
    (["rate cut", "cut rate", "easing", "lower rate", "stimulus"], "bullish", "降息→利多黄金"),
    # 鸽派言论 → 利空USD → 利多黄金
    (["dovish", "accommodative", "patient", "wait-and-see"], "bullish", "鸽派言论→利多黄金"),
    # 鹰派言论 → 利空黄金
    (["hawkish", "tighten", "taper", "overheating"], "bearish", "鹰派言论→利空黄金"),
    # 自然灾害/突发事件 → 避险
    (["earthquake", "tsunami", "hurricane", "natural disaster", "pandemic"], "bullish", "突发事件→避险→黄金↑"),
    # 美元走强 → 利空黄金
    (["dollar strength", "usd strength", "strong dollar", "dollar rally"], "bearish", "美元走强→利空黄金"),
    # 美元走弱 → 利多黄金
    (["dollar weakness", "usd weakness", "weak dollar", "dollar sell-off"], "bullish", "美元走弱→利多黄金"),
    # 美债收益率上升 → 利空黄金
    (["yield rise", "bond sell-off", "rate increase", "yield spike"], "bearish", "收益率上升→利空黄金"),
    # 美债收益率下降 → 利多黄金
    (["yield fall", "bond rally", "rate decline", "yield drop"], "bullish", "收益率下降→利多黄金"),
    # 央行购金 → 利多黄金
    (["central bank gold purchase", "gold reserve increase", "gold buying"], "bullish", "央行购金→利多黄金"),
    # ETF 资金流入 → 利多黄金
    (["gold etf inflow", "gold fund inflow", "gold holding increase"], "bullish", "ETF流入→利多黄金"),
    # ETF 资金流出 → 利空黄金
    (["gold etf outflow", "gold fund outflow", "gold holding decrease"], "bearish", "ETF流出→利空黄金"),
    # 风险偏好上升 → 利空黄金
    (["risk-on", "risk appetite", "stock rally", "equity surge"], "bearish", "风险偏好→利空黄金"),
    # 风险偏好下降 → 利多黄金
    (["risk-off", "risk aversion", "fear", "uncertainty", "volatility spike"], "bullish", "避险情绪→利多黄金"),
]

# 高置信度事件关键词
HIGH_CONFIDENCE_KW = [
    "war", "sanction", "ceasefire", "rate hike", "rate cut",
    "dovish", "hawkish", "nuclear", "missile", "invasion",
    "earthquake", "pandemic", "fomc decision", "fed decision",
]


def classify_event(title: str, actual: Optional[str] = None, forecast: Optional[str] = None) -> tuple[str, str, str]:
    """
    根据事件标题 + 实际/预期值 分类方向。
    返回 (bias, reason, confidence)
    bias: 'bullish' / 'bearish' / 'neutral'

    逻辑层级：
      1. 会议/新闻发布会 → neutral（需看内容）
      2. 经济数据类事件（ECONOMIC_DATA_KW）→ 有 actual/forecast 用预期差，无则 neutral
      3. 纯方向事件（DIRECTIONAL_PATTERNS）→ 关键词匹配
    """
    if not title:
        return "neutral", "无标题", "low"

    title_lower = title.lower()

    # 1. 会议/新闻发布会 → 无预设方向
    neutral_keywords = ["press conference", "minutes", " testimony "]
    for kw in neutral_keywords:
        if kw in title_lower:
            return "neutral", f"事件类型({title})需实际内容判断", "low"

    # 2. 经济数据类事件（方向依赖 actual vs forecast）
    is_economic = any(kw in title_lower for kw in ECONOMIC_DATA_KW)

    if is_economic:
        # 有 actual/forecast → 用预期差判断
        if actual is not None and forecast is not None and actual != "" and forecast != "":
            try:
                # 清理数值（去除 % $ T B M 等符号）
                actual_clean = re.sub(r'[^\d.\-]', '', actual).strip()
                forecast_clean = re.sub(r'[^\d.\-]', '', forecast).strip()
                if actual_clean and forecast_clean:
                    actual_val = float(actual_clean)
                    forecast_val = float(forecast_clean)

                    # 失业率/初请: 上升→利多黄金，下降→利空黄金
                    is_unemployment = any(kw in title_lower for kw in ["unemployment", "jobless rate", "jobless claims"])
                    if is_unemployment:
                        if actual_val < forecast_val:
                            return "bearish", f"失业率实际({actual}) < 预期({forecast}) → 就业改善→强美元→利空黄金", "high"
                        elif actual_val > forecast_val:
                            return "bullish", f"失业率实际({actual}) > 预期({forecast}) → 就业恶化→弱美元→利多黄金", "high"
                        else:
                            return "neutral", f"失业率实际({actual}) = 预期({forecast}) → 影响有限", "medium"

                    # 消费者信心/情绪: 上升→risk-on→利空黄金
                    is_confidence = any(kw in title_lower for kw in ["consumer confidence", "consumer sentiment", "uom"])
                    if is_confidence:
                        if actual_val > forecast_val:
                            return "bearish", f"信心实际({actual}) > 预期({forecast}) → 乐观→risk-on→利空黄金", "high"
                        elif actual_val < forecast_val:
                            return "bullish", f"信心实际({actual}) < 预期({forecast}) → 悲观→避险→利多黄金", "high"
                        else:
                            return "neutral", f"信心实际({actual}) = 预期({forecast}) → 影响有限", "medium"

                    # 核心逻辑：实际 > 预期 → 经济强劲/通胀高 → 强美元 → 利空黄金
                    # 实际 < 预期 → 经济疲软/通胀低 → 弱美元 → 利多黄金
                    if actual_val < forecast_val:
                        return "bullish", f"实际({actual}) < 预期({forecast}) → 不及预期→弱美元→利多黄金", "high"
                    elif actual_val > forecast_val:
                        return "bearish", f"实际({actual}) > 预期({forecast}) → 超预期→强美元→利空黄金", "high"
                    else:
                        return "neutral", f"实际({actual}) = 预期({forecast}) → 影响有限", "medium"
            except (ValueError, TypeError) as e:
                logger.debug(f"数值转换失败: {title} actual={actual} forecast={forecast} error={e}")
                pass

        # 无 actual/forecast → 返回 neutral，不赌方向
        return "neutral", f"经济数据({title})需实际值判断", "low"

    # 3. 纯方向事件关键词匹配
    for keywords, direction, reason in DIRECTIONAL_PATTERNS:
        for kw in keywords:
            if kw in title_lower:
                confidence = "high" if any(hkw in title_lower for hkw in HIGH_CONFIDENCE_KW) else "medium"
                return direction, f"{reason}({title})", confidence

    return "neutral", f"无法分类({title})", "low"


class NewsBiasEvaluator:
    """News-bias 评估器 — 观察模式，不干预交易"""

    def __init__(self):
        self._news_filter = NewsFilter()
        self._eval_cache: list[dict] = []
        self._cache_time: float = 0.0

    # ── 核心评估 ──────────────────────────────────────────

    def evaluate_past_events(self, hours: int = 6) -> list[dict]:
        """
        评估过去 N 小时内的高影响 USD 事件。
        从数据库中获取评估记录，检测新事件并评估。
        """
        from data import database as db
        db.init_db()

        # 获取新闻日历中的事件（含 actual/forecast，包含过去事件）
        events = self._news_filter.get_upcoming_events(limit=50, include_past=True)

        # 筛选过去 N 小时内的事件
        now = datetime.now(tz=LOCAL_TZ)
        cutoff = now - timedelta(hours=hours)
        past_events = []
        for evt in events:
            try:
                evt_dt = datetime.strptime(evt["datetime"], "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
                if cutoff <= evt_dt <= now:
                    past_events.append(evt)
            except (ValueError, KeyError):
                continue

        if not past_events:
            return []

        # 检查哪些事件已经评估过
        existing = db.get_news_evaluations(hours=hours)
        existing_titles = {e["event_title"] for e in existing}

        results = list(existing)
        for evt in past_events:
            if evt["title"] in existing_titles:
                continue

            # 分类事件（传入 actual/forecast）
            bias, reason, confidence = classify_event(
                evt["title"],
                actual=evt.get("actual") or None,
                forecast=evt.get("forecast") or None,
            )

            # 获取事件前后的价格
            try:
                evt_dt = datetime.strptime(evt["datetime"], "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
                pre_price, post_15m, post_1h = self._get_prices_around(evt_dt)
                move_15m = round(post_15m - pre_price, 2) if post_15m and pre_price else 0
                move_1h = round(post_1h - pre_price, 2) if post_1h and pre_price else 0

                # 判断方向是否匹配
                direction_match = None
                if bias != "neutral" and move_15m != 0:
                    if (bias == "bullish" and move_15m > 0) or (bias == "bearish" and move_15m < 0):
                        direction_match = "correct"
                    else:
                        direction_match = "wrong"

                record = {
                    "event_title": evt["title"],
                    "event_time": evt["datetime"],
                    "event_country": evt.get("country", "USD"),
                    "event_impact": evt.get("impact", "High"),
                    "expected_bias": bias,
                    "confidence": confidence,
                    "reason": reason,
                    "pre_price": pre_price or 0,
                    "post_price_15m": post_15m or 0,
                    "post_price_1h": post_1h or 0,
                    "actual_move_15m": move_15m,
                    "actual_move_1h": move_1h,
                    "direction_match": direction_match,
                }

                db.insert_news_evaluation(record)
                results.append(record)
                logger.info(f"[NewsBias] 评估: {evt['title']} → {bias}({confidence}) 实动={move_15m:+.2f} {direction_match or 'N/A'}")

            except Exception as e:
                logger.warning(f"[NewsBias] 评估失败 {evt['title']}: {e}")

        self._eval_cache = results
        self._cache_time = time.time()
        return results

    def _get_prices_around(self, event_dt: datetime) -> tuple:
        """
        获取事件前后价格。
        返回 (pre_price, post_15min_price, post_1h_price)
        """
        from data import database as db

        event_ts = int(event_dt.timestamp())

        # 事件前 15 分钟
        pre_ts = event_ts - 900
        # 事件后 15 分钟
        post_15m_ts = event_ts + 900
        # 事件后 1 小时
        post_1h_ts = event_ts + 3600

        # 从数据库读取 M5 K 线（接近指定时间点的收盘价）
        pre_price = self._get_price_at(pre_ts)
        post_15m_price = self._get_price_at(post_15m_ts)
        post_1h_price = self._get_price_at(post_1h_ts)

        return pre_price, post_15m_price, post_1h_price

    def _get_price_at(self, target_ts: int) -> Optional[float]:
        """获取 M5 K 线中离目标时间最近的收盘价"""
        try:
            from data import database as db
            import time as _time
            # 取最近 30 天 M5 K 线（避免返回最旧的 200 根）
            recent_ts = int(_time.time()) - 30 * 24 * 3600
            candles = db.get_candles("M5", start_ts=recent_ts, limit=8000)
            if not candles:
                return None
            # 找离 target_ts 最近的 K 线（误差不超过 5 分钟）
            best = None
            best_diff = float("inf")
            for c in candles:
                c_ts = c.get("time", 0)
                diff = abs(c_ts - target_ts)
                if diff < best_diff and diff < 300:  # 5分钟内
                    best = c.get("close", c.get("close_price", 0))
                    best_diff = diff
            return best
        except Exception:
            return None

    # ── 报告数据 ──────────────────────────────────────────

    def get_report_data(self, hours: int = 24) -> dict:
        """
        生成报告用的 news-bias 数据。
        返回统计摘要 + 最近评估列表。
        """
        from data import database as db
        evaluations = db.get_news_evaluations(hours=hours)

        total = len(evaluations)
        correct = sum(1 for e in evaluations if e.get("direction_match") == "correct")
        wrong = sum(1 for e in evaluations if e.get("direction_match") == "wrong")
        neutral = sum(1 for e in evaluations if e.get("expected_bias") == "neutral" or not e.get("direction_match"))

        # 只算有方向的
        directional = correct + wrong
        accuracy = round(correct / directional * 100, 1) if directional > 0 else 0

        return {
            "enabled": True,
            "total": total,
            "correct": correct,
            "wrong": wrong,
            "neutral": neutral,
            "directional": directional,
            "accuracy": accuracy,
            "evaluations": evaluations[-10:],  # 最近 10 条
        }

    # ── 预判报告生成 ──────────────────────────────────────────

    def generate_prediction_report(self, current_price: float = 0) -> dict | None:
        """
        生成 XAUUSD 新闻预判报告（逻辑链模型）。

        Step 1: 抓新闻 → 按变量分类
        Step 2: 计算五大变量加权得分
        Step 3: 叠加技术面 (RSI, trend, BB)
        Step 4: 综合评分 → 看涨/看跌/震荡
        Step 5: 写入 DB
        """
        from data import database as db
        from services.news_fetcher import NewsFetcher
        import json

        # Step 1: 抓新闻
        fetcher = NewsFetcher()
        news_items = fetcher.fetch_news(limit=20)
        if not news_items:
            logger.warning("[NewsBias] 未获取到新闻，跳过报告生成")
            return None

        # Step 2: 变量加权得分
        var_scores = fetcher.compute_variable_scores(news_items)

        total_score = 0
        for var, s in var_scores.items():
            total_score += s["score"] * s["weight"]

        # Step 3: 市场技术面
        market_ctx = self._get_current_market_context()
        if current_price > 0:
            market_ctx["current_price"] = current_price

        rsi = market_ctx.get("rsi", 50)
        bb_position = market_ctx.get("bb_position", 0.5)
        trend = market_ctx.get("trend", "neutral")

        # 技术调整
        tech_adjustment = 0.0
        if rsi > 70:
            tech_adjustment -= 0.1
        elif rsi < 30:
            tech_adjustment += 0.1

        if bb_position > 0.95:
            tech_adjustment -= 0.05
        elif bb_position < 0.05:
            tech_adjustment += 0.05

        if trend == "uptrend":
            tech_adjustment += 0.05
        elif trend == "downtrend":
            tech_adjustment -= 0.05

        final_score = round(total_score + tech_adjustment, 2)

        # Step 4: 方向判定
        if final_score > 0.3:
            direction = "bullish"
        elif final_score < -0.3:
            direction = "bearish"
        else:
            direction = "sideways"

        confidence = self._compute_confidence(final_score, var_scores)

        prediction = {
            "direction": direction,
            "score": final_score,
            "tech_adjustment": round(tech_adjustment, 2),
            "threshold_used": 0.3,
            "confidence": confidence,
            "reason": self._build_reason(var_scores, tech_adjustment, rsi, bb_position, trend),
        }

        # Step 5: 写入 DB
        entry_price = current_price or market_ctx.get("current_price", 0)
        now = datetime.now()
        title = f"XAUUSD 新闻预判 - {now.strftime('%Y-%m-%d %H:00')}"

        direction_labels = {"bullish": "看涨 ↑", "bearish": "看跌 ↓", "sideways": "震荡 →"}
        summary = f"{direction_labels.get(direction, direction)} 评分={final_score:+.2f} 置信度={confidence}%"

        record = {
            "title": title,
            "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "news_items": json.dumps([{
                "title": n["title"],
                "source": n["source"],
                "variable": n["variable"],
                "direction": n["direction"],
                "weight": n["weight"],
                "chain": n.get("chain", ""),
            } for n in news_items], ensure_ascii=False),
            "variable_scores": json.dumps(var_scores, ensure_ascii=False),
            "market_context": json.dumps(market_ctx, ensure_ascii=False),
            "prediction": json.dumps(prediction, ensure_ascii=False),
            "entry_price": entry_price,
            "verify_price": 0,
            "verify_result": "",
            "verify_at": "",
            "popped_up": 0,
            "summary": summary,
        }
        report_id = db.insert_news_bias_report(record)
        prediction["id"] = report_id

        result = {
            "id": report_id,
            "title": title,
            "summary": summary,
            "prediction": prediction,
            "variable_scores": var_scores,
            "news_items": news_items[:5],
            "market_context": market_ctx,
            "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        }

        logger.info(f"[NewsBias] 报告 #{report_id}: {direction} score={final_score:+.2f}")
        return result

    def verify_old_predictions(self, current_price: float = 0) -> list[dict]:
        """验证超过 12 小时的老报告，回填 verify_price 和 verify_result"""
        from data import database as db
        import json

        reports = db.get_unverified_reports()
        if not reports:
            return []

        results = []
        for r in reports:
            report_id = r["id"]
            entry_price = r.get("entry_price", 0)
            pred_raw = r.get("prediction", "{}")
            prediction = json.loads(pred_raw) if isinstance(pred_raw, str) else (pred_raw or {})

            direction = prediction.get("direction", "")
            if not direction:
                continue

            price = current_price
            if price <= 0:
                price = self._get_latest_price()
            if price <= 0:
                continue

            price_change = price - entry_price
            if abs(price_change) < 0.5:
                actual = "sideways"
            elif price_change > 0:
                actual = "bullish"
            else:
                actual = "bearish"

            correct = direction == actual
            verify_result = "correct" if correct else "wrong"

            db.update_news_bias_report(report_id, {
                "verify_price": round(price, 2),
                "verify_result": verify_result,
                "verify_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

            results.append({
                "id": report_id,
                "predicted": direction,
                "actual": actual,
                "entry_price": entry_price,
                "verify_price": round(price, 2),
                "change": round(price_change, 2),
                "result": verify_result,
            })
            logger.info(f"[NewsBias] 验证 #{report_id}: {direction} vs {actual} → {verify_result}")

        return results

    def _get_current_market_context(self) -> dict:
        """从 DB K 线获取当前技术指标"""
        from data import database as db
        import statistics
        import time as _time

        ctx = {"current_price": 0, "rsi": 50, "trend": "neutral", "bb_position": 0.5}
        try:
            # 取最近 7 天 H1 K 线（避免返回最旧的 100 根）
            recent_ts = int(_time.time()) - 7 * 24 * 3600
            candles = db.get_candles("H1", start_ts=recent_ts, limit=300)
            if not candles or len(candles) < 20:
                return ctx

            closes = [c["close"] for c in candles]
            ctx["current_price"] = closes[-1]
            ctx["rsi"] = round(self._compute_rsi(closes, 14), 1)

            ema9 = self._compute_ema(closes, 9)
            ema21 = self._compute_ema(closes, 21)
            if ema9 and ema21:
                ctx["trend"] = "uptrend" if ema9 > ema21 else "downtrend"

            sma = statistics.mean(closes[-20:])
            std = statistics.stdev(closes[-20:]) if len(closes) >= 20 else 1
            if std > 0:
                bb_pos = (closes[-1] - sma) / (2 * std) + 0.5
                ctx["bb_position"] = round(max(0, min(1, bb_pos)), 2)
        except Exception as e:
            logger.warning(f"[NewsBias] 市场上下文获取失败: {e}")

        return ctx

    @staticmethod
    def _compute_rsi(closes: list[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50
        gains, losses = [], []
        for i in range(len(closes) - period, len(closes)):
            if i == len(closes) - period:
                continue
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100
        return round(100 - (100 / (1 + avg_gain / avg_loss)), 1)

    @staticmethod
    def _compute_ema(closes: list[float], period: int) -> float | None:
        if len(closes) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period
        for price in closes[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    def _get_latest_price(self) -> float:
        """从最近 M5 K 线获取最新价格"""
        from data import database as db
        try:
            candles = db.get_candles("M5", limit=1)
            if candles:
                return candles[-1]["close"]
        except Exception:
            pass
        return 0

    @staticmethod
    def _compute_confidence(score: float, var_scores: dict) -> int:
        """
        计算置信度 (0-100)。
        评分远离阈值 + 变量共振 → 高置信度。
        """
        abs_score = abs(score)
        if abs_score > 0.5:
            base = 80
        elif abs_score > 0.3:
            base = 60
        else:
            base = 40

        # 变量数量修正：有数据的变量越多越可信
        active = sum(1 for s in var_scores.values() if s["count"] > 0)
        if active >= 4:
            base += 10
        elif active <= 1:
            base -= 10

        return max(0, min(100, base))

    @staticmethod
    def _build_reason(var_scores: dict, tech_adj: float, rsi: float, bb_pos: float, trend: str) -> str:
        parts = []
        vars_str = []
        for var, s in var_scores.items():
            if s["count"] > 0:
                vars_str.append(f"{var}({s['score']:+.2f})")
        if vars_str:
            parts.append(f"变量得分: {' '.join(vars_str)}")
        parts.append(f"技术调整: {tech_adj:+.2f} (RSI={rsi}, BB={bb_pos:.0%}, {trend})")
        return " | ".join(parts)
