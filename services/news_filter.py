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
            logger.info("[NewsFilter] Calendar expired or missing, fetching at start")
            self._do_fetch(now)
        else:
            elapsed = now - last_fetch
            self._next_fetch = last_fetch + FETCH_INTERVAL
            logger.info(f"[NewsFilter] Calendar valid (fetched {elapsed/3600:.1f}h ago)，"
                       f"下次拉取: {datetime.fromtimestamp(self._next_fetch, tz=settings.LOCAL_TZ).strftime('%m-%d %H:%M')}")

    def _read_config(self):
        """读取最新配置（RuntimeConfig 优先，回退 settings.py）"""
        try:
            from core.runtime_config import RuntimeConfig
            rc = RuntimeConfig()
            return {
                "enabled": rc.get("news_filter_enabled", getattr(settings, "NEWS_FILTER_ENABLED", True)),
                "before_min": int(rc.get("news_before_minutes", getattr(settings, "NEWS_BEFORE_MINUTES", 30))),
                "after_min": int(rc.get("news_after_minutes", getattr(settings, "NEWS_AFTER_MINUTES", 120))),
                "impact": rc.get("news_impact_filter", getattr(settings, "NEWS_IMPACT_FILTER", "High")),
                "currency": rc.get("news_currency_filter", getattr(settings, "NEWS_CURRENCY_FILTER", "USD")),
            }
        except Exception:
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
                logger.info(f"[NewsFilter] Loaded {len(events)} events from DB")
        except Exception as e:
            logger.warning(f"[NewsFilter] DB loadfailed: {e}")

    def _save_to_db(self, events: list[dict]):
        """将事件持久化到 SQLite"""
        try:
            from data import database as db
            db.clear_news_calendar()
            now = time.time()
            db.insert_news_events(events, now)
            db.set_metadata("news_last_fetch_time", str(now))
            logger.info(f"[NewsFilter] Persisted {len(events)} events")
        except Exception as e:
            logger.warning(f"[NewsFilter] DB persist failed: {e}")

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
            logger.info(f"[NewsFilter] merged {added} built-in events (FOMC)")

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
        self._run_gold_news_fetch()
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
                logger.info(f"[NewsFilter] HTTP fetch success: {len(data)} event, "
                           f"下次拉取: {datetime.fromtimestamp(self._next_fetch, tz=settings.LOCAL_TZ).strftime('%m-%d %H:%M')}")
            else:
                logger.warning(f"[NewsFilter] Calendar format exception: {type(data)}")
                self._next_fetch = now + 3600  # 1h 后重试
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 429:
                self._retry_after = now + 3600
                logger.warning("[NewsFilter] API rate limited, skip retry for 1h")
            else:
                logger.warning(f"[NewsFilter] HTTP failed: {e}")
            self._next_fetch = now + 3600
        except requests.RequestException as e:
            logger.warning(f"[NewsFilter] HTTP failed: {e}")
            self._next_fetch = now + 3600

    def force_refresh(self):
        """强制重新拉取并合并内置事件，不依赖定时器"""
        self._do_fetch(time.time())

    # ── News-Bias 评估 ──────────────────────────────────

    def _run_gold_news_fetch(self):
        """定时抓取汇通+金十快讯并用 LLM 判断方向（每 4 小时限频一次）"""
        now = time.time()
        if now - getattr(self, '_last_gold_news_fetch', 0) < 14400:
            return
        self._last_gold_news_fetch = now
        try:
            from services.huicong_news import fetch_and_judge
            from services.llm_provider import LLMProviderManager
            mgr = LLMProviderManager()
            active = mgr.get_active()
            if not active:
                for p in mgr._providers:
                    if p.get("api_key"):
                        mgr.set_active(p["id"])
                        break
            results = fetch_and_judge(mgr)
            if results:
                bullish = sum(1 for r in results if r['direction'] == 'bullish')
                bearish = sum(1 for r in results if r['direction'] == 'bearish')
                logger.info(f"[GoldNews] Scheduled fetch done: {len(results)}, bullish{bullish}/bearish{bearish}")
        except Exception as e:
            logger.warning(f"[GoldNews] Scheduled fetch exception: {e}")

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
        """检查是否在禁售窗口内。"""
        cfg = self._read_config()
        if not cfg["enabled"]:
            return False, ""

        if not self._cache:
            return False, "新闻日历已切换为黄金快讯模式，无禁售窗口数据"

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
        """通用窗口检查。"""
        cfg = self._read_config()
        if not cfg["enabled"]:
            return False

        if not self._cache:
            return False

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

    # ── News-Bias 实时方向阻塞 ──────────────────────────────

    def get_current_bias(self) -> Optional[dict]:
        """
        获取当前黄金快讯方向偏向（用于阻塞控制）。
        从 gold_news 表读取最近 N 条快讯的 LLM 判断方向。
        返回 {'overall': 'BULLISH'|'BEARISH'|'NEUTRAL', 'details': [...]} 或 None
        """
        try:
            from config import settings
            
            if not getattr(settings, 'NEWS_BIAS_ENABLED', True):
                return None
            
            # 从 gold_news 表读取最近快讯的方向
            from data import database as db
            db.init_db()
            gold_news = db.get_gold_news(limit=20, direction="")
            
            if not gold_news:
                return None
            
            bullish_score = 0
            bearish_score = 0
            details = []
            
            for item in gold_news[:20]:
                direction = item.get("direction", "neutral")
                confidence = item.get("direction_confidence", "low")
                weight = {"high": 3, "medium": 2, "low": 1}.get(confidence, 1)
                
                if direction == "bullish":
                    bullish_score += weight
                elif direction == "bearish":
                    bearish_score += weight
                
                details.append({
                    "event": item.get("content", "")[:80],
                    "time": item.get("news_time", ""),
                    "bias": direction,
                    "confidence": confidence,
                    "source": item.get("source", "?"),
                })
            
            if not details:
                return None
            
            overall = "NEUTRAL"
            if bullish_score > bearish_score * 1.5:
                overall = "BULLISH"
            elif bearish_score > bullish_score * 1.5:
                overall = "BEARISH"
            
            return {
                "overall": overall,
                "bullish_score": bullish_score,
                "bearish_score": bearish_score,
                "details": details,
            }
        except Exception as e:
            logger.error(f"[NewsBias] direction fetch exception: {e}")
            return None

    # ── 前端展示 ──────────────────────────────────────────

    @staticmethod
    def to_local(dt: datetime) -> datetime:
        offset = datetime.now() - datetime.utcnow()
        offset_hours = round(offset.total_seconds() / 3600)
        return dt + timedelta(hours=offset_hours)

    def get_upcoming_events(self, limit: int = 10, include_past: bool = False) -> list[dict]:
        """获取即将到来的高影响事件（供前端展示）。
        include_past=True 时同时返回过去事件（供偏斜评估）。"""
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
                "actual": evt.get("actual", ""),
            })

        if include_past:
            result.sort(key=lambda x: x["datetime"])
            return result[:limit]
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
