"""
News Filter 新闻过滤服务
从 ForexFactory JSON 订阅源获取经济日历，计算禁售时间窗口
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import requests

from config import settings

logger = logging.getLogger(__name__)

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


class NewsFilter:
    """新闻过滤服务 — 重大数据发布前后暂停开仓"""

    def __init__(self):
        self._cache: list[dict] = []
        self._cache_time: float = 0.0
        self._cache_ttl: float = 3600  # 1小时缓存
        self._blackout_windows: list[tuple[datetime, datetime, str]] = []
        self._windows_computed_at: float = 0.0

    def _read_config(self):
        """读取最新配置"""
        return {
            "enabled": getattr(settings, "NEWS_FILTER_ENABLED", True),
            "before_min": int(getattr(settings, "NEWS_BEFORE_MINUTES", 30)),
            "after_min": int(getattr(settings, "NEWS_AFTER_MINUTES", 30)),
            "impact": getattr(settings, "NEWS_IMPACT_FILTER", "High"),
            "currency": getattr(settings, "NEWS_CURRENCY_FILTER", "USD"),
        }

    def fetch_calendar(self) -> list[dict]:
        """获取本周经济日历（带缓存）"""
        now = time.time()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        try:
            resp = requests.get(FF_CALENDAR_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                self._cache = data
                self._cache_time = now
                logger.info(f"[新闻过滤] 获取经济日历成功: {len(data)} 个事件")
            else:
                logger.warning(f"[新闻过滤] 日历数据格式异常: {type(data)}")
        except requests.RequestException as e:
            logger.warning(f"[新闻过滤] 获取经济日历失败: {e}")
            if self._cache:
                logger.info("[新闻过滤] 使用缓存数据")

        return self._cache

    def get_blackout_windows(self) -> list[tuple[datetime, datetime, str]]:
        """返回当前应生效的禁售窗口列表 [(start, end, event_title), ...]"""
        cfg = self._read_config()
        if not cfg["enabled"]:
            return []

        self.fetch_calendar()
        if not self._cache:
            return []

        # 解析影响级别过滤
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

            if currency not in currency_filter:
                continue
            if impact not in impact_filter:
                continue

            evt_dt = self._parse_event_datetime(evt)
            if evt_dt is None:
                continue

            # 窗口已过则跳过
            if evt_dt + after_delta < now:
                continue

            start = evt_dt - before_delta
            end = evt_dt + after_delta
            windows.append((start, end, title))

        self._blackout_windows = windows
        self._windows_computed_at = time.time()
        return windows

    def is_in_blackout(self, now: Optional[datetime] = None) -> tuple[bool, str]:
        """检查当前时间是否在禁售窗口内，返回 (True/False, 原因)"""
        cfg = self._read_config()
        if not cfg["enabled"]:
            return False, ""

        if now is None:
            now = datetime.utcnow()

        windows = self.get_blackout_windows()

        for start, end, title in windows:
            if start <= now <= end:
                return True, title

        return False, ""

    def get_upcoming_events(self, limit: int = 10) -> list[dict]:
        """获取即将到来的高影响事件（供前端展示）"""
        cfg = self._read_config()
        self.fetch_calendar()
        if not self._cache:
            return []

        impact_filter = set(cfg["impact"].replace(" ", "").split(","))
        currency_filter = set(cfg["currency"].replace(" ", "").split(","))

        now = datetime.now()
        result = []
        for evt in self._cache:
            currency = (evt.get("country") or "").upper()
            impact = (evt.get("impact") or "").strip()

            if currency not in currency_filter:
                continue
            if impact not in impact_filter:
                continue

            evt_dt = self._parse_event_datetime(evt)
            if evt_dt is None:
                continue

            result.append({
                "title": evt.get("title", "Unknown"),
                "country": currency,
                "impact": impact,
                "datetime": evt_dt.strftime("%Y-%m-%d %H:%M"),
                "forecast": evt.get("forecast", ""),
                "previous": evt.get("previous", ""),
            })

        # 按时间排序，返回未来的
        result.sort(key=lambda x: x["datetime"])
        future = [r for r in result if r["datetime"] >= now.strftime("%Y-%m-%d %H:%M")]
        return future[:limit]

    @staticmethod
    def _parse_event_datetime(evt: dict) -> Optional[datetime]:
        """解析事件的 datetime，支持多种格式，统一返回 naive datetime"""
        date_str = evt.get("date", "")
        time_str = evt.get("time", "")

        if not date_str:
            return None

        # ISO 8601 带时区: "2026-05-28T08:30:00-04:00"
        try:
            dt = datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S")
            # 处理时区偏移，转换为 UTC naive datetime
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

        # ISO 8601 无时区: "2026-05-28T08:30:00"
        try:
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass

        # "MM-DD-YYYY HH:MM" 或 "YYYY-MM-DD HH:MM"
        if not time_str or time_str in ("All Day", "Tentative"):
            time_str = "00:00"

        for fmt in ("%Y-%m-%d", "%m-%d-%Y"):
            try:
                return datetime.strptime(f"{date_str} {time_str}", f"{fmt} %H:%M")
            except ValueError:
                continue
        return None
