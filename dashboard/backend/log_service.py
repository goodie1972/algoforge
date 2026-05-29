"""
日志捕获服务 - 环形缓冲区，通过 API 和 WebSocket 提供
"""

import logging
from datetime import datetime
from typing import Optional


class LogCaptureHandler(logging.Handler):
    """内存环形缓冲区日志处理器"""

    def __init__(self, max_records: int = 2000):
        super().__init__()
        self.max_records = max_records
        self.records: list[dict] = []
        self._new_records: list[dict] = []  # 尚未通过 WS 推送的记录

    def emit(self, record: logging.LogRecord):
        entry = {
            "time": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": self.format(record),
        }
        self.records.append(entry)
        self._new_records.append(entry)
        # 限制环形缓冲区大小
        if len(self.records) > self.max_records:
            self.records = self.records[-self.max_records:]

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
        return result[-limit:]

    def pop_new(self) -> list[dict]:
        """获取并清空新记录（用于 WebSocket 推送）"""
        result = self._new_records.copy()
        self._new_records.clear()
        return result

    def clear(self):
        self.records.clear()
        self._new_records.clear()
