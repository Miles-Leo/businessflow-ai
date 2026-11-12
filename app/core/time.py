# 模块职责：UTC+8 业务展示转换；不得通过替换时区标签改变实际时刻。
"""Business presentation uses UTC+8; persisted instants remain UTC."""
from datetime import datetime, timedelta, timezone

BUSINESS_TIMEZONE = timezone(timedelta(hours=8), name="UTC+8")


def business_iso(value: datetime | str) -> str:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    return parsed.astimezone(BUSINESS_TIMEZONE).isoformat()


def business_display(value: datetime | str) -> str:
    return datetime.fromisoformat(business_iso(value)).strftime("%Y-%m-%d %H:%M:%S UTC+8")
