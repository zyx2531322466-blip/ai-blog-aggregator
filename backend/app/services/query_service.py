"""文章查询与浏览服务（T10）。

- 列表：按主类别、标签、来源、时间筛选并分页；合并组只展示主记录一条。
- 详情：返回主记录内容，并列出合并组的全部来源（含各来源发布时间与原文链接）。
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.enums import ArticleStatus, CategoryStatus, DedupRelationType
from app.db.models import Article, Category, DuplicateRelation, Source, Tag, article_tags
from app.schemas.article import (
    ArticleDetail,
    ArticleListItem,
    CategoryRef,
    RelatedArticleRef,
    SourceDetail,
    SourceSummary,
)
from app.services import dedup_service

MERGE_TYPES = (DedupRelationType.EXACT_DUPLICATE, DedupRelationType.NEAR_DUPLICATE)


@dataclass
class ArticleFilters:
    """列表筛选条件。"""

    category: str | None = None
    tag: str | None = None
    source: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    page: int = 1
    page_size: int = 20


def list_articles(session: Session, filters: ArticleFilters) -> tuple[int, list[Article]]:
    """按筛选条件分页查询文章。

    公开列表只呈现"可展示"的内容：排除已过滤（低质量/入口页）与解析失败（error）的记录，
    以及被合并的重复记录（只展示主记录）。
    """

    statement = select(Article).where(
        Article.status.notin_((ArticleStatus.FILTERED, ArticleStatus.ERROR))
    )

    merged_member_ids = select(DuplicateRelation.article_id).where(
        DuplicateRelation.is_primary.is_(False),
        DuplicateRelation.relation_type.in_(MERGE_TYPES),
    )
    statement = statement.where(Article.id.notin_(merged_member_ids))

    if filters.category:
        category_ids = select(Category.id).where(
            or_(Category.id == filters.category, Category.name == filters.category)
        )
        statement = statement.where(Article.primary_category_id.in_(category_ids))

    if filters.tag:
        tag_ids = select(Tag.id).where(or_(Tag.id == filters.tag, Tag.name == filters.tag))
        tagged_article_ids = select(article_tags.c.article_id).where(
            article_tags.c.tag_id.in_(tag_ids)
        )
        statement = statement.where(Article.id.in_(tagged_article_ids))

    if filters.source:
        source_ids = select(Source.id).where(
            or_(
                Source.id == filters.source,
                Source.name == filters.source,
                Source.site_url == filters.source,
            )
        )
        statement = statement.where(Article.source_id.in_(source_ids))

    effective_time = func.coalesce(Article.published_at, Article.crawled_at)
    if filters.start_date is not None:
        statement = statement.where(effective_time >= filters.start_date)
    if filters.end_date is not None:
        statement = statement.where(effective_time <= filters.end_date)

    total = (
        session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    )

    page = max(1, filters.page)
    page_size = max(1, filters.page_size)
    statement = (
        statement.order_by(effective_time.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return total, list(session.scalars(statement))


def build_list_item(session: Session, article: Article) -> ArticleListItem:
    """将文章转换为列表项（含合并组来源计数）。"""

    group = dedup_service.get_group_members(session, article)
    sources_count = max(1, len(group))
    primary_category = (
        CategoryRef.model_validate(article.primary_category)
        if article.primary_category is not None
        else None
    )
    return ArticleListItem(
        id=article.id,
        title=article.title,
        summary=article.summary,
        category=[primary_category.name] if primary_category is not None else [],
        primary_category=primary_category,
        tags=[tag.name for tag in article.tags],
        published_at=article.published_at,
        crawled_at=article.crawled_at,
        primary_source=_source_summary(article),
        sources_count=sources_count,
        merged_sources_count=max(0, sources_count - 1),
        status=article.status,
    )


def get_article_detail(session: Session, article_id: str) -> ArticleDetail:
    """读取文章详情；对被合并的文章返回合并组全部来源。"""

    article = session.get(Article, article_id)
    if article is None:
        raise ApiError(404, "NOT_FOUND", "文章不存在")

    canonical = dedup_service.resolve_primary(session, article)
    group = dedup_service.get_group_members(session, article)
    group_ids = {member.id for member in group} | {canonical.id}
    members = [member for member in group if member.id in group_ids]
    if canonical.id not in {member.id for member in members}:
        members.append(canonical)

    sources = [
        SourceDetail(
            name=member.source.name if member.source is not None else None,
            url=member.url,
            crawled_at=member.crawled_at,
            published_at=member.published_at,
            is_primary=member.id == canonical.id,
        )
        for member in members
        if member is not None
    ]

    primary_category = (
        CategoryRef.model_validate(canonical.primary_category)
        if canonical.primary_category is not None
        else None
    )
    related = dedup_service.get_related_articles(session, canonical)
    return ArticleDetail(
        id=canonical.id,
        title=canonical.title,
        content=canonical.content,
        summary=canonical.summary,
        category=[primary_category.name] if primary_category is not None else [],
        primary_category=primary_category,
        tags=[tag.name for tag in canonical.tags],
        published_at=canonical.published_at,
        crawled_at=canonical.crawled_at,
        sources=sources,
        status=canonical.status,
        related_articles=[
            RelatedArticleRef(id=article.id, title=article.title, url=article.url)
            for article in related
        ],
    )


def _source_summary(article: Article) -> SourceSummary | None:
    if article.source is None:
        return None
    return SourceSummary(name=article.source.name, url=article.source.site_url)


def list_active_categories_with_counts(session: Session) -> list[tuple[str, int]]:
    """公开分类导航：启用中的类别及其可见文章数（plan.md API 3）。"""

    merged_member_ids = select(DuplicateRelation.article_id).where(
        DuplicateRelation.is_primary.is_(False),
        DuplicateRelation.relation_type.in_(MERGE_TYPES),
    )
    statement = (
        select(Category.name, func.count(Article.id))
        .outerjoin(
            Article,
            and_(
                Article.primary_category_id == Category.id,
                Article.status != ArticleStatus.FILTERED,
                Article.id.notin_(merged_member_ids),
            ),
        )
        .where(Category.status == CategoryStatus.ACTIVE)
        .group_by(Category.id, Category.name, Category.created_at)
        .order_by(Category.created_at)
    )
    return [(name, count) for name, count in session.execute(statement).all()]
