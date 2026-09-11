"""维护者效果概览的响应模型（T20）。"""

from pydantic import BaseModel


class InsightsRead(BaseModel):
    """分类分布 + 去重命中统计。"""

    category_distribution: dict[str, int]
    dedup_stats: dict[str, int]
