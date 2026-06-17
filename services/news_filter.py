"""
News Filter 新闻过滤服务 — 单例，SQLite 持久化，24h 自动拉取
"""
import importlib
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from config import settings

logger = logging.getLogger(__name__)

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FETCH_INTERVAL = 86400  # 24 小时

# 内置高影响事件（ForexFactory 周历无法覆盖的远期事件，如 FOMC）
# 格式与 ForexFactory 一致，_parse_event_datetime 可处理 ISO+时区
BUILTIN_EVENTS = [
    # 2026 FOMC 日程 — Day 2（利率决议 + 新闻发布会）
    {"date": "2026-06-17T14:00:00-04:00", "time": "14:00", "title": "FOMC Interest Rate Decision (Warsh's 1st)", "country": "USD", "impact": "High", "forecast": "", "previous": ""},
    {"date": "2026-06-17T14:30:00-04:00", "time": "14:30", "title": "FOMC Press Conference", "country": "USD", "impact": "High", "forecast": "", "previous": ""},
    {"date": "2026-07-29T14:00:00-04:00", "time": "14:00", "title": "FOMC Interest Rate Decision", "country": "USD", "impact": "High", "forecast": "", "previous": ""},
    {"date": "2026-07-29T14:30:00-04:00", "time": "14:30", "title": "FOMC Press Conference", "country": "USD", "impact": "High", "forecast": "", "previous": ""},
    {"date": "2026-09-16T14:00:00-04:00", "time": "14:00", "title": "FOMC Interest Rate Decision + SEP + Dot Plot", "country": "USD", "impact": "High", "forecast": "", "previous": ""},
    {"date": "2026-09-16T14:30:00-04:00", "time": "14:30", "title": "FOMC Press Conference", "country": "USD", "impact": "High", "forecast": "", "previous": ""},
    {"date": "2026-10-28T14:00:00-04:00", "time": "14:00", "title": "FOMC Interest Rate Decision", "country": "USD", "impact": "High", "forecast": "", "previous": ""},
    {"date": "2026-10-28T14:30:00-04:00", "time": "14:30", "title": "FOMC Press Conference", "country": "USD", "impact": "High", "forecast": "", "previous": ""},
    {"date": "2026-12-09T14:00:00-04:00", "time": "14:00", "title": "FOMC Interest Rate Decision + SEP + Dot Plot", "country": "USD", "impact": "High", "forecast": "", "previous": ""},
    {"date": "2026-12-09T14:30:00-04:00", "time": "14:30", "title": "FOMC Press Conference", "country": "USD", "impact": "High", "forecast": "", "previous": ""},
]


class NewsFilter:
    """新闻过滤服务 — 单例，线程安全"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._data_lock = threading.Lock()
        self._cache: list[dict] = []
        self._cache_time: float = 0.0
        self._cache_ttl: float = 43200  # 12h 内存缓存
        self._retry_after: float = 0.0
        self._next_fetch: float = 0.0
        self._blackout_windows: list[tuple[datetime, datetime, str]] = []
        self._windows_computed_at: float = 0.0

        # 从 DB 恢复缓存
        self._load_from_db()

        # 检查是否需要立即拉取
        last_fetch = self._get_last_fetch_time()
        now = time.time()
        if last_fetch == 0 or (now - last_fetch) >= FETCH_INTERVAL:
            logger.info("[新闻过滤] 日历过期或缺失，启动时拉取")
            self._do_fetch(now)
        else:
            elapsed = now - last_fetch
            self._next_fetch = last_fetch + FETCH_INTERVAL
            logger.info(f"[新闻过滤] 日历有效（{elapsed/3600:.1f}h 前拉取），"
                       f"下次拉取: {datetime.fromtimestamp(self._next_fetch).strftime('%m-%d %H:%M')}")

    def _read_config(self):
        """读取最新配置"""
        return {
            "enabled": getattr(settings, "NEWS_FILTER_ENABLED", True),
            "before_min": int(getattr(settings, "NEWS_BEFORE_MINUTES", 30)),
            "after_min": int(getattr(settings, "NEWS_AFTER_MINUTES", 120)),
            "impact": getattr(settings, "NEWS_IMPACT_FILTER", "High"),
            "currency": getattr(settings, "NEWS_CURRENCY_FILTER", "USD"),
        }

    # ── DB 持久化 ──────────────────────────────────────────

    def _load_from_db(self):
        """从 SQLite 加载日历缓存"""
        try:
            from data import database as db
            db.init_db()
            events = db.load_news_events()
            if events:
                with self._data_lock:
                    self._cache = events
                    self._cache_time = time.time()
                self._merge_builtin_events()
                logger.info(f"[新闻过滤] 从 DB 加载 {len(events)} 个事件")
        except Exception as e:
            logger.warning(f"[新闻过滤] DB 加载失败: {e}")

    def _save_to_db(self, events: list[dict]):
        """将事件持久化到 SQLite"""
        try:
            from data import database as db
            db.clear_news_calendar()
            now = time.time()
            db.insert_news_events(events, now)
            db.set_metadata("news_last_fetch_time", str(now))
            logger.info(f"[新闻过滤] 已持久化 {len(events)} 个事件")
        except Exception as e:
            logger.warning(f"[新闻过滤] DB 持久化失败: {e}")

    def _merge_builtin_events(self):
        """将内置高影响事件（FOMC）合并到缓存，避免 ForexFactory 周历覆盖不到"""
        if not self._cache:
            self._cache = list(BUILTIN_EVENTS)
            return
        existing_keys = {(e.get("title", ""), e.get("date", "")) for e in self._cache}
        added = 0
        for evt in BUILTIN_EVENTS:
            key = (evt["title"], evt["date"])
            if key not in existing_keys:
                self._cache.append(evt)
                existing_keys.add(key)
                added += 1
        if added:
            logger.info(f"[新闻过滤] 合并 {added} 个内置事件 (FOMC)")

    def _get_last_fetch_time(self) -> float:
        """读取上次成功拉取的时间戳"""
        try:
            from data import database as db
            val = db.get_metadata("news_last_fetch_time")
            if val:
                return float(val)
        except (ValueError, TypeError, Exception):
            pass
        return 0.0

    # ── 定时拉取 ──────────────────────────────────────────

    def try_scheduled_fetch(self):
        """每个 tick 调用，到期自动拉取。is_in_blackout 不触发 HTTP"""
        now = time.time()
        self._run_bias_evaluation()
        if now < self._retry_after:
            return
        if self._next_fetch > 0 and now < self._next_fetch:
            return
        self._do_fetch(now)

    def _do_fetch(self, now: float):
        """执行 HTTP 拉取，成功后更新 DB 和定时器"""
        try:
            resp = requests.get(FF_CALENDAR_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                with self._data_lock:
                    self._cache = data
                    self._cache_time = now
                self._merge_builtin_events()
                self._retry_after = 0.0
                self._next_fetch = now + FETCH_INTERVAL
                merged = list(self._cache)
                self._save_to_db(merged)
                logger.info(f"[新闻过滤] HTTP 拉取成功: {len(data)} 个事件, "
                           f"下次拉取: {datetime.fromtimestamp(self._next_fetch).strftime('%m-%d %H:%M')}")
            else:
                logger.warning(f"[新闻过滤] 日历格式异常: {type(data)}")
                self._next_fetch = now + 3600  # 1h 后重试
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 429:
                self._retry_after = now + 3600
                logger.warning("[新闻过滤] API 限流，1h 内不重试")
            else:
                logger.warning(f"[新闻过滤] HTTP 失败: {e}")
            self._next_fetch = now + 3600
        except requests.RequestException as e:
            logger.warning(f"[新闻过滤] HTTP 失败: {e}")
            self._next_fetch = now + 3600

    def force_refresh(self):
        """强制重新拉取并合并内置事件，不依赖定时器"""
        self._do_fetch(time.time())

    # ── News-Bias 评估 ──────────────────────────────────

    def _read_bias_config(self) -> dict:
        """读取最新 NEWS_BIAS 配置（每次重新加载 settings，支持运行时修改）"""
        try:
            importlib.reload(settings)
        except Exception:
            pass
        return {
            "enabled": getattr(settings, "NEWS_BIAS_ENABLED", True),
            "report_hours": getattr(settings, "NEWS_BIAS_REPORT_HOURS", "0,12"),
        }

    def _run_bias_evaluation(self):
        """执行 news-bias 事后评估（受配置控制，每 10 分钟限频一次）"""
        cfg = self._read_bias_config()
        if not cfg["enabled"]:
            return

        now = time.time()
        if now - getattr(self, '_last_bias_eval', 0) < 600:
            return
        self._last_bias_eval = now

        try:
            from services.news_bias import NewsBiasEvaluator
            evaluator = NewsBiasEvaluator()
            results = evaluator.evaluate_past_events(hours=6)
            if results:
                # 检查是否在报告时间点
                current_hour = datetime.now().hour
                report_hours = [
                    int(h.strip()) for h in cfg["report_hours"].split(",")
                    if h.strip().isdigit()
                ]
                is_report_time = current_hour in report_hours
                summary = f"[NewsBias] 评估 {len(results)} 条事件"
                if is_report_time:
                    report = evaluator.get_report_data(hours=24)
                    summary += (f", 报告: {report['directional']}笔方向性 "
                                f"准确率{report['accuracy']}%")
                logger.info(summary)
        except Exception as e:
            logger.warning(f"[NewsBias] 评估异常: {e}")

    def get_blackout_windows(self) -> list[tuple[datetime, datetime, str]]:
        """返回当前应生效的禁售窗口列表"""
        cfg = self._read_config()
        if not cfg["enabled"]:
            return []

        if not self._cache:
            return []

        impact_filter = set(cfg["impact"].replace(" ", "").split(","))
        currency_filter = set(cfg["currency"].replace(" ", "").split(","))
        before_delta = timedelta(minutes=cfg["before_min"])
        after_delta = timedelta(minutes=cfg["after_min"])
        now = datetime.utcnow()

        windows = []
        for evt in self._cache:
            currency = (evt.get("country") or "").upper()
            impact = (evt.get("impact") or "").strip()
            title = evt.get("title", "Unknown")

            if currency not in currency_filter or impact not in impact_filter:
                continue

            evt_dt = self._parse_event_datetime(evt)
            if evt_dt is None:
                continue
            if evt_dt + after_delta < now:
                continue

            windows.append((evt_dt - before_delta, evt_dt + after_delta, title))

        with self._data_lock:
            self._blackout_windows = windows
            self._windows_computed_at = time.time()
        return windows

    def is_in_blackout(self, now: Optional[datetime] = None) -> tuple[bool, str]:
        """检查是否在禁售窗口内。空缓存 → 安全默认 True"""
        cfg = self._read_config()
        if not cfg["enabled"]:
            return False, ""

        if not self._cache:
            return True, "日历数据未加载"

        if now is None:
            now = datetime.utcnow()

        windows = self.get_blackout_windows()
        for start, end, title in windows:
            if start <= now <= end:
                return True, title
        return False, ""

    def is_in_pre_tighten(self, now: Optional[datetime] = None) -> bool:
        return self._is_in_window(now, "pre_tighten")

    def is_in_force_close(self, now: Optional[datetime] = None) -> bool:
        return self._is_in_window(now, "force_close")

    def _is_in_window(self, now: Optional[datetime], mode: str) -> bool:
        """通用窗口检查。空缓存 → 安全默认 True"""
        cfg = self._read_config()
        if not cfg["enabled"]:
            return False

        if not self._cache:
            return True

        if now is None:
            now = datetime.utcnow()

        impact_filter = set(cfg["impact"].replace(" ", "").split(","))
        currency_filter = set(cfg["currency"].replace(" ", "").split(","))
        pre_close_min = int(getattr(settings, "NEWS_PRE_CLOSE_MINUTES", 15))
        pre_tighten_min = int(getattr(settings, "NEWS_PRE_TIGHTEN_MINUTES", 120))

        for evt in self._cache:
            currency = (evt.get("country") or "").upper()
            impact = (evt.get("impact") or "").strip()
            if currency not in currency_filter or impact not in impact_filter:
                continue

            evt_dt = self._parse_event_datetime(evt)
            if evt_dt is None:
                continue

            if mode == "pre_tighten":
                start = evt_dt - timedelta(minutes=pre_tighten_min)
                end = evt_dt - timedelta(minutes=pre_close_min)
            elif mode == "force_close":
                start = evt_dt - timedelta(minutes=pre_close_min)
                end = evt_dt
            else:
                return False

            if start <= now <= end:
                return True
        return False

    # ── 前端展示 ──────────────────────────────────────────

    @staticmethod
    def to_local(dt: datetime) -> datetime:
        offset = datetime.now() - datetime.utcnow()
        offset_hours = round(offset.total_seconds() / 3600)
        return dt + timedelta(hours=offset_hours)

    def get_upcoming_events(self, limit: int = 10) -> list[dict]:
        """获取即将到来的高影响事件（供前端展示）"""
        cfg = self._read_config()
        if not self._cache:
            return []

        impact_filter = set(cfg["impact"].replace(" ", "").split(","))
        currency_filter = set(cfg["currency"].replace(" ", "").split(","))
        now = datetime.now()

        result = []
        for evt in self._cache:
            currency = (evt.get("country") or "").upper()
            impact = (evt.get("impact") or "").strip()
            if currency not in currency_filter or impact not in impact_filter:
                continue

            evt_dt = self._parse_event_datetime(evt)
            if evt_dt is None:
                continue

            local_dt = self.to_local(evt_dt)
            result.append({
                "title": evt.get("title", "Unknown"),
                "country": currency,
                "impact": impact,
                "datetime": local_dt.strftime("%Y-%m-%d %H:%M"),
                "datetime_utc": evt_dt.strftime("%Y-%m-%d %H:%M"),
                "forecast": evt.get("forecast", ""),
                "previous": evt.get("previous", ""),
            })

        result.sort(key=lambda x: x["datetime"])
        future = [r for r in result if r["datetime"] >= now.strftime("%Y-%m-%d %H:%M")]
        return future[:limit]

    # ── 日期时间解析 ──────────────────────────────────────

    @staticmethod
    def _parse_event_datetime(evt: dict) -> Optional[datetime]:
        date_str = evt.get("date", "")
        time_str = evt.get("time", "")

        if not date_str:
            return None

        try:
            dt = datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S")
            tz_part = date_str[19:]
            if tz_part and tz_part[0] in "+-" and len(tz_part) == 6:
                sign = 1 if tz_part[0] == "+" else -1
                hours = int(tz_part[1:3])
                mins = int(tz_part[4:6])
                offset = sign * timedelta(hours=hours, minutes=mins)
                dt = dt - offset
            return dt
        except (ValueError, IndexError):
            pass

        try:
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass

        if not time_str or time_str in ("All Day", "Tentative"):
            time_str = "00:00"

        for fmt in ("%Y-%m-%d", "%m-%d-%Y"):
            try:
                return datetime.strptime(f"{date_str} {time_str}", f"{fmt} %H:%M")
            except ValueError:
                continue
        return None
