"""维护者效果概览统计（T20）。

- 分类分布：各受控类别下的可见文章数（含"未分类"）；
- 去重命中统计：完全重复 / 近重复 / 关联推荐 三类分别计数，并给出总量指标。
"""

from dataclasses import dataclass, field

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.enums import ArticleStatus, DedupRelationType
from app.db.models import Article, Category, DuplicateRelation

MERGE_TYPES = (DedupRelationType.EXACT_DUPLICATE, DedupRelationType.NEAR_DUPLICATE)
UNCATEGORIZED_LABEL = "未分类"


@dataclass
class InsightsResult:
    """概览统计结果。"""

    category_distribution: dict[str, int] = field(default_factory=dict)
    dedup_stats: dict[str, int] = field(default_factory=dict)


def build_insights(session: Session) -> InsightsResult:
    """汇总分类分布与去重命中统计。"""

    merged_member_ids = select(DuplicateRelation.article_id).where(
        DuplicateRelation.is_primary.is_(False),
        DuplicateRelation.relation_type.in_(MERGE_TYPES),
    )
    visible_condition = and_(
        Article.status != ArticleStatus.FILTERED,
        Article.id.notin_(merged_member_ids),
    )

    distribution: dict[str, int] = {}
    rows = session.execute(
        select(Category.name, func.count(Article.id))
        .outerjoin(Article, and_(Article.primary_category_id == Category.id, visible_condition))
        .group_by(Category.id, Category.name, Category.created_at)
        .order_by(Category.created_at)
    ).all()
    for name, count in rows:
        distribution[name] = count

    uncategorized = (
        session.scalar(
            select(func.count())
            .select_from(Article)
            .where(Article.primary_category_id.is_(None), visible_condition)
        )
        or 0
    )
    if uncategorized:
        distribution[UNCATEGORIZED_LABEL] = uncategorized

    type_counts = {relation_type.value: 0 for relation_type in DedupRelationType}
    hits = session.execute(
        select(DuplicateRelation.relation_type, func.count())
        .where(DuplicateRelation.is_primary.is_(False))
        .group_by(DuplicateRelation.relation_type)
    ).all()
    for relation_type, count in hits:
        type_counts[relation_type.value] = count

    total_articles = (
        session.scalar(
            select(func.count())
            .select_from(Article)
            .where(Article.status != ArticleStatus.FILTERED)
        )
        or 0
    )
    merged_members = (
        session.scalar(select(func.count()).select_from(merged_member_ids.subquery())) or 0
    )

    dedup_stats = {
        "exact_duplicate": type_counts[DedupRelationType.EXACT_DUPLICATE.value],
        "near_duplicate": type_counts[DedupRelationType.NEAR_DUPLICATE.value],
        "related": type_counts[DedupRelationType.RELATED.value],
        "merged_duplicates": type_counts[DedupRelationType.EXACT_DUPLICATE.value]
        + type_counts[DedupRelationType.NEAR_DUPLICATE.value],
        "total_articles": total_articles,
        "unique_articles": max(0, total_articles - merged_members),
    }

    return InsightsResult(category_distribution=distribution, dedup_stats=dedup_stats)
