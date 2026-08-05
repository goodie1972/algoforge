"""
XAUUSD 新闻预判复盘服务 — 事后偏差分析与改进
=============================================
对已生成的预测报告进行复盘，比对实际走势，分类偏差类型，
生成改进建议，并更新准确率统计。

用法：
  from services.news_bias_reviewer import NewsBiasReviewer
  reviewer = NewsBiasReviewer()
  results = reviewer.review_past_reports(hours=24)
  stats = reviewer.get_review_stats(days=7)
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from config import settings
from services.news_fetcher import classify_direction

logger = logging.getLogger(__name__)


class NewsBiasReviewer:
    """
    新闻预判复盘器 — 事后分析预测偏差，生成改进建议。
    不干预交易决策，仅用于评估和优化预测逻辑。
    """

    def __init__(self):
        """初始化复盘器，延迟导入 database 以避免循环依赖"""
        self._db = None

    @property
    def db(self):
        """延迟加载 database 模块"""
        if self._db is None:
            from data import database as db
            self._db = db
        return self._db

    # ── 数据库辅助方法（内联 SQL，避免依赖 database.py 中尚不存在的函数） ──

    def _get_conn(self):
        """获取数据库连接"""
        return self.db.get_conn()

    def _get_unreviewed_reports(self) -> list[dict]:
        """
        获取创建超过 12 小时且尚未复盘的预测报告。
        通过 LEFT JOIN prediction_reviews 排除已复盘的记录。
        """
        conn = self._get_conn()
        try:
            cutoff = (datetime.now() - timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
            rows = conn.execute(
                """SELECT r.* FROM news_bias_reports r
                   LEFT JOIN prediction_reviews pv ON r.id = pv.report_id
                   WHERE r.created_at <= ? AND pv.id IS NULL
                   ORDER BY r.created_at ASC""",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _insert_prediction_review(self, record: dict) -> int:
        """
        写入一条复盘记录到 prediction_reviews 表。
        返回新记录的 id，失败返回 0。
        """
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO prediction_reviews
                   (report_id, predicted_direction, actual_direction, is_correct,
                    error_type, root_cause, suggestion, keywords_used,
                    price_at_prediction, price_after_15m, price_after_1h, price_after_4h)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.get("report_id"),
                    record.get("predicted_direction", ""),
                    record.get("actual_direction", ""),
                    int(record.get("is_correct", False)),
                    record.get("error_type", ""),
                    record.get("root_cause", ""),
                    record.get("suggestion", ""),
                    record.get("keywords_used", ""),
                    record.get("price_at_prediction", 0),
                    record.get("price_after_15m", 0),
                    record.get("price_after_1h", 0),
                    record.get("price_after_4h", 0),
                ),
            )
            conn.commit()
            return cur.lastrowid or 0
        except Exception as e:
            logger.warning(f"[NewsBiasReviewer] 写入 prediction_review 失败: {e}")
            return 0
        finally:
            conn.close()

    def _update_accuracy_stats(self, date: str, stats: dict) -> bool:
        """
        更新指定日期的准确率统计。
        stats 应包含 total, correct, accuracy, breakdown(JSON str)。
        """
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO accuracy_stats (date, total, correct, accuracy, breakdown)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(date) DO UPDATE SET
                     total=excluded.total,
                     correct=excluded.correct,
                     accuracy=excluded.accuracy,
                     breakdown=excluded.breakdown""",
                (
                    date,
                    stats.get("total", 0),
                    stats.get("correct", 0),
                    stats.get("accuracy", 0.0),
                    stats.get("breakdown", "{}"),
                ),
            )
            conn.commit()
            return True
        except Exception as e:
            logger.warning(f"[NewsBiasReviewer] 更新 accuracy_stats 失败: {e}")
            return False
        finally:
            conn.close()

    def _get_accuracy_stats(self, days: int = 7) -> list[dict]:
        """
        获取最近 N 天的准确率统计。
        """
        conn = self._get_conn()
        try:
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            rows = conn.execute(
                """SELECT * FROM accuracy_stats
                   WHERE date >= ?
                   ORDER BY date DESC""",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _get_prediction_reviews(self, hours: int = 24) -> list[dict]:
        """
        获取最近 N 小时的复盘记录，关联报告标题。
        """
        conn = self._get_conn()
        try:
            cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            rows = conn.execute(
                """SELECT pv.*, r.title AS report_title, r.summary AS report_summary
                   FROM prediction_reviews pv
                   LEFT JOIN news_bias_reports r ON pv.report_id = r.id
                   WHERE pv.created_at >= ?
                   ORDER BY pv.created_at DESC""",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── 核心复盘流程 ──────────────────────────────────────

    def review_past_reports(self, hours: int = 24) -> list[dict]:
        """
        复盘过去 N 小时内的预测报告。

        流程：
          1. 从 DB 获取创建超过 12 小时且未复盘的报告
          2. 对每条报告：
             a. 获取当前价格，比较 entry_price 判断实际方向（变动 > 0.5% 才算方向）
             b. 判断预测是否正确
             c. 若错误，调用 _classify_error_type() 分类偏差类型
             d. 调用 _generate_suggestion() 生成改进建议
             e. 写入 prediction_reviews 表
          3. 更新 accuracy_stats 表

        Args:
            hours: 回溯时间范围（小时），默认 24。

        Returns:
            本次复盘的记录列表。
        """
        self.db.init_db()

        reports = self._get_unreviewed_reports()
        if not reports:
            logger.info("[NewsBiasReviewer] 无待复盘报告")
            return []

        current_price = self._get_latest_price()
        if current_price <= 0:
            logger.warning("[NewsBiasReviewer] 无法获取当前价格，跳过复盘")
            return []

        results = []
        correct_count = 0
        error_breakdown = {}

        for report in reports:
            try:
                review = self._review_single_report(report, current_price)
                if review:
                    # 写入复盘记录
                    self._insert_prediction_review(review)
                    results.append(review)

                    if review["is_correct"]:
                        correct_count += 1
                    else:
                        error_type = review.get("error_type", "unknown")
                        error_breakdown[error_type] = error_breakdown.get(error_type, 0) + 1

                    logger.info(
                        f"[NewsBiasReviewer] 复盘 #{report['id']}: "
                        f"预测={review['predicted_direction']} "
                        f"实际={review['actual_direction']} "
                        f"{'✓正确' if review['is_correct'] else '✗偏差:' + error_type}"
                    )
            except Exception as e:
                logger.warning(
                    f"[NewsBiasReviewer] 复盘报告 #{report.get('id', '?')} 失败: {e}"
                )

        # 更新准确率统计
        if results:
            self._update_stats(results, correct_count, error_breakdown)

        logger.info(
            f"[NewsBiasReviewer] 复盘完成: {len(results)} 条, "
            f"正确={correct_count}, 错误={len(results) - correct_count}"
        )
        return results

    def _review_single_report(self, report: dict, current_price: float) -> Optional[dict]:
        """
        对单条报告进行复盘分析。

        Args:
            report: news_bias_reports 表中的一条记录。
            current_price: 当前 XAUUSD 价格。

        Returns:
            复盘记录 dict，若无法分析返回 None。
        """
        report_id = report["id"]
        entry_price = report.get("entry_price", 0)
        if entry_price <= 0:
            return None

        # 解析 prediction JSON
        pred_raw = report.get("prediction", "{}")
        prediction = (
            json.loads(pred_raw)
            if isinstance(pred_raw, str)
            else (pred_raw or {})
        )
        predicted_direction = prediction.get("direction", "")

        # 获取创建时间
        created_at_str = report.get("created_at", "")
        try:
            created_dt = datetime.strptime(
                created_at_str, "%Y-%m-%d %H:%M:%S"
            )
        except (ValueError, TypeError):
            created_dt = datetime.now() - timedelta(hours=12)

        # 计算价格变动百分比
        price_change_pct = (current_price - entry_price) / entry_price * 100

        # 判断实际方向（变动 > 0.5% 才算方向）
        if abs(price_change_pct) <= 0.5:
            actual_direction = "sideways"
        elif price_change_pct > 0:
            actual_direction = "bullish"
        else:
            actual_direction = "bearish"

        # 判断预测是否正确
        is_correct = predicted_direction == actual_direction

        # 获取事件前后价格
        price_15m, price_1h, price_4h = self._get_prices_around(
            created_dt, entry_price
        )

        # 提取关键词
        keywords_used = self._extract_keywords(report)

        review = {
            "report_id": report_id,
            "predicted_direction": predicted_direction,
            "actual_direction": actual_direction,
            "is_correct": is_correct,
            "error_type": "",
            "root_cause": "",
            "suggestion": "",
            "keywords_used": keywords_used,
            "price_at_prediction": entry_price,
            "price_after_15m": price_15m,
            "price_after_1h": price_1h,
            "price_after_4h": price_4h,
        }

        # 错误时分类偏差
        if not is_correct:
            error_type = self._classify_error_type(report, actual_direction, created_dt)
            suggestion = self._generate_suggestion(report, error_type)
            review["error_type"] = error_type
            review["root_cause"] = self._build_root_cause(error_type, report)
            review["suggestion"] = suggestion

        return review

    # ── 偏差分类 ──────────────────────────────────────────

    def _classify_error_type(
        self, report: dict, actual_dir: str, created_dt: datetime
    ) -> str:
        """
        分类偏差类型。

        类型说明：
          - 'data_counterintuitive': 数据反直觉（如 CPI 降但金价跌）
          - 'other_factor_dominant': 其他因素主导（同时段有高影响事件）
          - 'technical_override': 技术面压制（RSI 超买/超卖、关键阻力）
          - 'premature_pricing': 提前消化（市场已提前定价）
          - 'time_window_mismatch': 时间窗口错位（方向对但时机偏移）
          - 'unknown': 未分类

        Args:
            report: 预测报告记录。
            actual_dir: 实际走势方向（'bullish'/'bearish'/'sideways'）。
            created_dt: 报告创建时间。

        Returns:
            偏差类型标识符。
        """
        pred_raw = report.get("prediction", "{}")
        prediction = (
            json.loads(pred_raw)
            if isinstance(pred_raw, str)
            else (pred_raw or {})
        )
        predicted_dir = prediction.get("direction", "sideways")
        news_items_raw = report.get("news_items", "[]")
        news_items = (
            json.loads(news_items_raw)
            if isinstance(news_items_raw, str)
            else (news_items_raw or [])
        )
        market_ctx_raw = report.get("market_context", "{}")
        market_ctx = (
            json.loads(market_ctx_raw)
            if isinstance(market_ctx_raw, str)
            else (market_ctx_raw or {})
        )

        # 1. 检查技术面压制
        rsi = market_ctx.get("rsi", 50)
        trend = market_ctx.get("trend", "")
        bb_pos = market_ctx.get("bb_position", 0.5)

        # 预测看涨但 RSI > 70（超买区），或预测看跌但 RSI < 30（超卖区）
        if predicted_dir == "bullish" and rsi > 70:
            return "technical_override"
        if predicted_dir == "bearish" and rsi < 30:
            return "technical_override"

        # 预测与趋势相反且趋势明显
        if trend == "downtrend" and predicted_dir == "bullish" and rsi < 45:
            return "technical_override"
        if trend == "uptrend" and predicted_dir == "bearish" and rsi > 55:
            return "technical_override"

        # 2. 检查同时段是否有其他高影响事件（其他因素主导）
        conflicting_events = self._check_conflicting_events(created_dt)
        if conflicting_events:
            return "other_factor_dominant"

        # 3. 检查数据反直觉
        # 如果新闻标题包含 CPI/PPI/Inflation/NFP 等关键数据
        # 且实际方向与数据预期方向相反
        text = json.dumps(news_items, ensure_ascii=False).lower()
        data_keywords = ["cpi", "ppi", "nfp", "non-farm", "payroll",
                         "inflation", "gdp", "retail sales", "unemployment",
                         "fomc", "fed", "interest rate"]
        has_data_event = any(kw in text for kw in data_keywords)

        # 检查新闻标题中的预期方向
        news_direction = self._get_news_direction(news_items)

        if has_data_event and news_direction:
            # 新闻预期 bullish 但实际 bearish，或反之
            if news_direction != actual_dir:
                return "data_counterintuitive"

        # 4. 检查时间窗口错位 / 提前消化
        price_15m = report.get("price_after_15m", 0) or 0
        price_1h = report.get("price_after_1h", 0) or 0
        entry_price = report.get("entry_price", 0) or 0

        if entry_price > 0 and price_15m > 0 and price_1h > 0:
            move_15m = price_15m - entry_price
            move_1h = price_1h - entry_price
            # 15分钟方向正确但1小时方向错误 → 提前消化
            if (move_15m > 0) == (predicted_dir == "bullish") and \
               (move_1h > 0) != (predicted_dir == "bullish"):
                return "premature_pricing"
            # 15分钟方向错误 → 时间窗口错位
            if (move_15m > 0) != (predicted_dir == "bullish"):
                return "time_window_mismatch"

        # 5. 检查提前消化（数据事件但价格变动极小）
        if has_data_event and price_15m > 0 and entry_price > 0:
            move_15m_pct = (price_15m - entry_price) / entry_price * 100
            if abs(move_15m_pct) < 0.2:
                return "premature_pricing"

        return "unknown"

    def _check_conflicting_events(self, event_dt: datetime) -> list[dict]:
        """
        检查事件时间前后 2 小时内是否有其他高影响事件。

        Args:
            event_dt: 事件时间。

        Returns:
            冲突事件列表，空列表表示无冲突。
        """
        try:
            self.db.init_db()
            conn = self._get_conn()
            try:
                start = event_dt - timedelta(hours=2)
                end = event_dt + timedelta(hours=2)
                start_str = start.strftime("%Y-%m-%d %H:%M:%S")
                end_str = end.strftime("%Y-%m-%d %H:%M:%S")
                rows = conn.execute(
                    """SELECT * FROM news_evaluations
                       WHERE event_time >= ? AND event_time <= ?
                       ORDER BY event_time ASC""",
                    (start_str, end_str),
                ).fetchall()
                events = [dict(r) for r in rows]
                # 排除自身
                return [e for e in events if e.get("event_time", "") != event_dt.strftime("%Y-%m-%d %H:%M")]
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[NewsBiasReviewer] 检查冲突事件失败: {e}")
            return []

    def _get_news_direction(self, news_items: list) -> str:
        """
        从新闻项中综合判断新闻预期方向。

        Args:
            news_items: 新闻项列表。

        Returns:
            'bullish' / 'bearish' / ''。
        """
        bullish_count = 0
        bearish_count = 0
        for item in news_items:
            direction = item.get("direction", "neutral")
            if direction == "bullish":
                bullish_count += 1
            elif direction == "bearish":
                bearish_count += 1

        if bullish_count > bearish_count:
            return "bullish"
        elif bearish_count > bullish_count:
            return "bearish"
        return ""

    # ── 改进建议生成 ──────────────────────────────────────

    def _generate_suggestion(self, report: dict, error_type: str) -> str:
        """
        基于偏差类型和报告关键词，生成具体的规则优化建议。

        Args:
            report: 预测报告记录。
            error_type: 偏差类型标识符。

        Returns:
            优化建议文本。
        """
        suggestion_templates = {
            "data_counterintuitive": (
                "【数据反直觉】建议：1) 增加数据发布前后的价格动量过滤器，"
                "仅当数据公布后 15 分钟价格方向与预期一致时才确认信号；"
                "2) 引入预期差修正（实际值 vs 预期值）来调整方向权重；"
                "3) 增加对数据发布前市场定价程度的评估。"
            ),
            "other_factor_dominant": (
                "【其他因素主导】建议：1) 检查同时段其他高影响事件，"
                "在事件冲突时降低置信度阈值；2) 引入事件优先级排序，"
                "按影响级别分配权重；3) 考虑地缘政治/突发新闻的临时影响。"
            ),
            "technical_override": (
                "【技术面压制】建议：1) 增加技术面过滤器（RSI 超买/超卖、"
                "趋势线、关键支撑阻力位）；2) 当 RSI > 70 时降低看涨置信度，"
                "RSI < 30 时降低看跌置信度；3) 叠加趋势方向判断，"
                "顺趋势时提高权重，逆趋势时降低权重。"
            ),
            "premature_pricing": (
                "【提前消化】建议：1) 增加事件前价格走势分析，"
                "若事件前 2 小时价格已朝预期方向移动则降低预期强度；"
                "2) 引入价格动量衰减指标；3) 考虑市场是否已完全定价该事件。"
            ),
            "time_window_mismatch": (
                "【时间窗口错位】建议：1) 延长验证窗口至 4-8 小时，"
                "避免短期噪音干扰；2) 使用移动平均确认趋势持续性；"
                "3) 增加时间衰减因子，短期信号权重随时间递减。"
            ),
            "unknown": (
                "【未分类偏差】建议：1) 增加更多特征以辅助分类；"
                "2) 手动分析该案例并补充规则；3) 考虑情绪因素（市场恐慌/贪婪指数）。"
            ),
        }

        base = suggestion_templates.get(error_type, suggestion_templates["unknown"])

        # 尝试从报告中提取关键词，补充具体建议
        keywords = self._extract_keywords(report)
        if keywords:
            base += f"\n涉及关键词：{keywords}"

        return base

    def _build_root_cause(self, error_type: str, report: dict) -> str:
        """
        构建偏差根因描述。

        Args:
            error_type: 偏差类型。
            report: 预测报告记录。

        Returns:
            根因描述文本。
        """
        pred_raw = report.get("prediction", "{}")
        prediction = (
            json.loads(pred_raw)
            if isinstance(pred_raw, str)
            else (pred_raw or {})
        )
        direction = prediction.get("direction", "?")
        score = prediction.get("score", 0)
        confidence = prediction.get("confidence", 0)

        causes = {
            "data_counterintuitive": (
                f"预测方向 {direction}(评分={score}, 置信度={confidence}%) 与实际数据走势相反，"
                "可能因市场已提前消化数据预期。"
            ),
            "other_factor_dominant": (
                f"预测方向 {direction}(评分={score}, 置信度={confidence}%) 被同时段其他因素覆盖，"
                "单一变量分析不足以解释价格变动。"
            ),
            "technical_override": (
                f"预测方向 {direction}(评分={score}, 置信度={confidence}%) 被技术面因素压制，"
                "市场处于超买/超卖或趋势反转阶段。"
            ),
            "premature_pricing": (
                f"预测方向 {direction}(评分={score}, 置信度={confidence}%) 方向正确但市场已提前消化，"
                "价格在事件前已反映预期。"
            ),
            "time_window_mismatch": (
                f"预测方向 {direction}(评分={score}, 置信度={confidence}%) 在短时间窗口内方向正确，"
                "但验证窗口扩大后方向改变。"
            ),
            "unknown": (
                f"预测方向 {direction}(评分={score}, 置信度={confidence}%) 偏差原因无法自动分类，"
                "需人工分析。"
            ),
        }
        return causes.get(error_type, causes["unknown"])

    # ── 关键词提取 ────────────────────────────────────────

    def _extract_keywords(self, report: dict) -> str:
        """
        从报告关联的新闻项中提取关键词。

        Args:
            report: 预测报告记录。

        Returns:
            逗号分隔的关键词列表。
        """
        news_items_raw = report.get("news_items", "[]")
        try:
            news_items = (
                json.loads(news_items_raw)
                if isinstance(news_items_raw, str)
                else (news_items_raw or [])
            )
        except (json.JSONDecodeError, TypeError):
            news_items = []

        if not news_items:
            return ""

        # 从标题中提取关键词
        all_titles = " ".join(
            item.get("title", "") for item in news_items if item.get("title")
        )
        # 常见关键词
        common_kw = [
            "CPI", "PPI", "NFP", "FOMC", "Fed", "GDP", "ISM",
            "inflation", "unemployment", "retail", "housing",
            "dollar", "gold", "XAU", "rate", "trade",
            "war", "sanction", "ceasefire", "tension",
            "bullish", "bearish", "neutral",
        ]
        found = []
        for kw in common_kw:
            if kw.lower() in all_titles.lower():
                found.append(kw)

        # 限制关键词数量
        return ", ".join(found[:10]) if found else ""

    # ── 价格获取 ──────────────────────────────────────────

    def _get_latest_price(self) -> float:
        """
        获取最新 XAUUSD 价格。

        Returns:
            最新价格，失败返回 0.0。
        """
        try:
            from data import database as db
            candles = db.get_candles("M5", limit=1)
            if candles:
                return candles[-1]["close"]
        except Exception as e:
            logger.warning(f"[NewsBiasReviewer] 获取最新价格失败: {e}")
        return 0.0

    def _get_prices_around(
        self, event_dt: datetime, entry_price: float
    ) -> tuple:
        """
        获取事件前后的价格区间。

        Args:
            event_dt: 事件时间。
            entry_price: 入场价格（作为基准）。

        Returns:
            (price_15m, price_1h, price_4h) 元组，获取失败则用 entry_price 填充。
        """
        try:
            from data import database as db
            event_ts = int(event_dt.timestamp())

            price_15m = self._get_price_at(db, event_ts + 900) or entry_price
            price_1h = self._get_price_at(db, event_ts + 3600) or entry_price
            price_4h = self._get_price_at(db, event_ts + 14400) or entry_price

            return price_15m, price_1h, price_4h
        except Exception:
            return entry_price, entry_price, entry_price

    def _get_price_at(self, db, target_ts: int) -> Optional[float]:
        """
        获取 M5 K 线中离目标时间最近的收盘价。

        Args:
            db: database 模块。
            target_ts: 目标 Unix 时间戳。

        Returns:
            最近价格，未找到返回 None。
        """
        try:
            import time as _time
            recent_ts = target_ts - 3600  # 往前 1 小时
            candles = db.get_candles("M5", start_ts=recent_ts, limit=100)
            if not candles:
                return None
            best = None
            best_diff = float("inf")
            for c in candles:
                c_ts = c.get("time", 0)
                diff = abs(c_ts - target_ts)
                if diff < best_diff and diff < 300:  # 5 分钟内
                    best = c.get("close", c.get("close_price", 0))
                    best_diff = diff
            return best
        except Exception:
            return None

    # ── 统计更新 ──────────────────────────────────────────

    def _update_stats(
        self,
        results: list[dict],
        correct_count: int,
        error_breakdown: dict,
    ):
        """
        更新准确率统计表。

        Args:
            results: 本次复盘的所有记录。
            correct_count: 正确预测数。
            error_breakdown: 偏差类型分布。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        total = len(results)
        accuracy = round(correct_count / total * 100, 1) if total > 0 else 0.0

        # 构造 breakdown JSON
        breakdown = {
            "total": total,
            "correct": correct_count,
            "wrong": total - correct_count,
            "accuracy": accuracy,
            "error_types": error_breakdown,
        }

        # 获取当日已有统计，合并更新
        existing_stats = self._get_accuracy_stats(days=1)
        existing_today = [s for s in existing_stats if s.get("date") == today]

        if existing_today:
            prev = existing_today[0]
            merged_total = prev.get("total", 0) + total
            merged_correct = prev.get("correct", 0) + correct_count
            try:
                prev_breakdown = json.loads(prev.get("breakdown", "{}"))
            except (json.JSONDecodeError, TypeError):
                prev_breakdown = {}
            merged_breakdown = {
                "total": merged_total,
                "correct": merged_correct,
                "wrong": merged_total - merged_correct,
                "accuracy": round(merged_correct / merged_total * 100, 1) if merged_total > 0 else 0.0,
                "error_types": {
                    **prev_breakdown.get("error_types", {}),
                    **error_breakdown,
                },
            }
            self._update_accuracy_stats(today, {
                "total": merged_total,
                "correct": merged_correct,
                "accuracy": merged_breakdown["accuracy"],
                "breakdown": json.dumps(merged_breakdown, ensure_ascii=False),
            })
        else:
            self._update_accuracy_stats(today, {
                "total": total,
                "correct": correct_count,
                "accuracy": accuracy,
                "breakdown": json.dumps(breakdown, ensure_ascii=False),
            })

        logger.info(
            f"[NewsBiasReviewer] 统计更新: {today} 总={total} 正确={correct_count} "
            f"准确率={accuracy}%"
        )

    # ── 复盘统计查询 ──────────────────────────────────────

    def get_review_stats(self, days: int = 7) -> dict:
        """
        获取复盘统计。

        返回：
            - accuracy_trend: 每日准确率趋势列表
            - error_distribution: 偏差类型分布
            - suggestions: 改进建议列表
            - summary: 总体统计摘要

        Args:
            days: 统计天数，默认 7。

        Returns:
            统计 dict，便于 API 序列化。
        """
        self.db.init_db()

        # 获取准确率日统计
        stats = self._get_accuracy_stats(days=days)

        # 获取复盘记录
        reviews = self._get_prediction_reviews(hours=days * 24)

        # 准确率趋势
        accuracy_trend = []
        for s in stats:
            try:
                breakdown = json.loads(s.get("breakdown", "{}"))
            except (json.JSONDecodeError, TypeError):
                breakdown = {}
            accuracy_trend.append({
                "date": s.get("date", ""),
                "total": s.get("total", 0),
                "correct": s.get("correct", 0),
                "accuracy": s.get("accuracy", 0.0),
                "error_types": breakdown.get("error_types", {}),
            })

        # 偏差类型分布
        error_distribution = {}
        for r in reviews:
            err_type = r.get("error_type", "unknown")
            if err_type:
                error_distribution[err_type] = error_distribution.get(err_type, 0) + 1

        # 改进建议列表
        suggestions = []
        seen_suggestions = set()
        for r in reviews:
            suggestion = r.get("suggestion", "")
            if suggestion and suggestion not in seen_suggestions:
                seen_suggestions.add(suggestion)
                suggestions.append({
                    "report_id": r.get("report_id"),
                    "report_title": r.get("report_title", ""),
                    "error_type": r.get("error_type", ""),
                    "suggestion": suggestion,
                    "created_at": r.get("created_at", ""),
                })

        # 总体统计摘要
        total = len(reviews)
        correct = sum(1 for r in reviews if r.get("is_correct"))
        wrong = total - correct

        summary = {
            "total_reviews": total,
            "correct": correct,
            "wrong": wrong,
            "accuracy": round(correct / total * 100, 1) if total > 0 else 0.0,
            "days": days,
            "error_types_count": len(error_distribution),
        }

        return {
            "accuracy_trend": accuracy_trend,
            "error_distribution": error_distribution,
            "suggestions": suggestions[:20],  # 最多返回 20 条
            "summary": summary,
        }