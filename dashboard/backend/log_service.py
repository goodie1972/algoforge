"""
日志捕获服务 - 环形缓冲区 + 数据库持久化
"""
import logging
import sys
import os
from datetime import datetime
from typing import Optional

# 添加项目根目录以导入 data.database
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from data import database as db
from config.settings import LOCAL_TZ


class LogCaptureHandler(logging.Handler):
    """日志处理器 — 同时写入内存环形缓冲区和数据库"""

    def __init__(self, max_records: int = 2000):
        super().__init__()
        self.max_records = max_records
        self.records: list[dict] = []
        self._new_records: list[dict] = []
        self._db_write_count = 0  # 每 100 条触发一次 prune

    def emit(self, record: logging.LogRecord):
        entry = {
            "time": datetime.fromtimestamp(record.created, tz=LOCAL_TZ).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": self.format(record),
        }
        self.records.append(entry)
        self._new_records.append(entry)
        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]

        # 写入数据库（静默失败，不影响主流程）
        try:
            db.insert_log(entry["time"], entry["level"], entry["name"], entry["message"])
            self._db_write_count += 1
            if self._db_write_count % 100 == 0:
                db.prune_logs()
        except Exception:
            pass

    def get_recent(self, level: Optional[str] = None,
                   limit: int = 100,
                   since: Optional[str] = None) -> list[dict]:
        """按条件筛选日志"""
        result = self.records
        if level:
            levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
            min_level = levels.get(level.upper(), 0)
            result = [r for r in result if levels.get(r["level"], 0) >= min_level]
        if since:
            result = [r for r in result if r["time"] >= since]
        return list(reversed(result[-limit:]))

    def pop_new(self) -> list[dict]:
        """获取并清空新记录（用于 WebSocket 推送）"""
        result = self._new_records.copy()
        self._new_records.clear()
        return result

    def clear(self):
        self.records.clear()
        self._new_records.clear()
