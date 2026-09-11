"""更新频率档位与到期判定（T17）。

建议档位（可由维护者为每个来源选择或自定义）：
- 高频：1–6 小时（默认取 3 小时）
- 普通：每天（24 小时）
- 低频：每周（7 天）
"""

from datetime import datetime, timezone

from app.db.enums import UpdateFrequency
from app.db.models import Source

HOUR = 3600
DAY = 24 * HOUR

DEFAULT_FREQUENCY_INTERVALS: dict[UpdateFrequency, int] = {
    UpdateFrequency.HIGH: 3 * HOUR,
    UpdateFrequency.NORMAL: 24 * HOUR,
    UpdateFrequency.LOW: 7 * DAY,
}

FREQUENCY_LABELS: dict[UpdateFrequency, str] = {
    UpdateFrequency.HIGH: "高频（每 3 小时）",
    UpdateFrequency.NORMAL: "普通（每天）",
    UpdateFrequency.LOW: "低频（每周）",
    UpdateFrequency.CUSTOM: "自定义",
}


def interval_for_source(source: Source) -> int:
    """返回来源的抓取间隔秒数；未配置时使用默认档位（普通=每天）。"""

    if source.update_frequency is UpdateFrequency.CUSTOM and source.update_interval_seconds:
        return int(source.update_interval_seconds)
    return DEFAULT_FREQUENCY_INTERVALS.get(
        source.update_frequency, DEFAULT_FREQUENCY_INTERVALS[UpdateFrequency.NORMAL]
    )


def is_due(source: Source, *, now: datetime) -> bool:
    """判断来源是否到达下一次抓取时间。"""

    if not source.is_active:
        return False
    if source.last_crawled_at is None:
        return True

    last_crawled = source.last_crawled_at
    if last_crawled.tzinfo is None:
        last_crawled = last_crawled.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    return (now - last_crawled).total_seconds() >= interval_for_source(source)
