"""
Dashboard 后端工具函数 — 通用辅助
"""
from datetime import datetime


def _add_ts_fields(record: dict) -> dict:
    """为记录中所有时间字段增加 _ts 后缀的 Unix 时间戳字段。

    自动识别以 _time / _at 结尾的键（如 open_time、close_time、created_at、
    updated_at、timestamp 等），将字符串或数值时间转换为 Unix 秒级时间戳。
    """
    result = dict(record)
    for key in record:
        if not (key.endswith("_time") or key.endswith("_at")):
            continue
        val = record.get(key)
        if not val:
            continue
        try:
            if isinstance(val, str):
                if val.strip().isdigit():
                    result[f"{key}_ts"] = int(val)
                else:
                    dt = datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
                    result[f"{key}_ts"] = int(dt.timestamp())
            elif isinstance(val, (int, float)):
                result[f"{key}_ts"] = int(val)
        except Exception:
            pass
    return result
