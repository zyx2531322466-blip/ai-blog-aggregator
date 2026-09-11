"""采集阶段的内容质量过滤（T16）。

在解析之后、进入分类流程之前，结合来源的排除词与内容质量特征，
过滤掉广告页、纯导航/聚合页等明显不适合作为文章展示的内容。
"""

from app.filtering.quality_filter import (
    AD_PATTERNS,
    MIN_CONTENT_LENGTH,
    MIN_LINK_TEXT_RATIO,
    QualityDecision,
    evaluate_quality,
    link_text_ratio,
)

__all__ = [
    "AD_PATTERNS",
    "MIN_CONTENT_LENGTH",
    "MIN_LINK_TEXT_RATIO",
    "QualityDecision",
    "evaluate_quality",
    "link_text_ratio",
]
