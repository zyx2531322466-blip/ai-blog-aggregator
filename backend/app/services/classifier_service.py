"""分类结果落库服务（T08 / T12）。

- 主类别：取自 T07 的受控类别清单（仅启用中的类别），恰好一个；
- 标签：零个或多个，按名称复用；
- 分类成功后将文章状态置为"正常"；
- 无命中时按 T12 兜底为"未分类/其他"，绝不丢弃文章。
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classifier.rules import Classification, classify_text
from app.core.errors import ApiError
from app.db.enums import ArticleStatus, CategoryStatus
from app.db.models import Article, Category, Tag
from app.services import category_service
from app.services.category_service import FALLBACK_CATEGORY_NAME

Classifier = Callable[..., Classification]


@dataclass
class ArticleClassification:
    """一篇文章的分类结果。"""

    article: Article
    category_id: str | None
    tags: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)
    used_fallback: bool = False


def ensure_fallback_category(session: Session) -> Category:
    """获取兜底类别"其他"，不存在时创建（保证未分类文章有归属）。"""

    category = category_service.find_category_by_name(session, FALLBACK_CATEGORY_NAME)
    if category is None:
        category = Category(name=FALLBACK_CATEGORY_NAME, is_default=True)
        session.add(category)
        session.flush()
    return category


def classify_article(
    session: Session,
    article: Article,
    *,
    classifier: Classifier = classify_text,
    fallback: bool = False,
) -> ArticleClassification:
    """判定文章主类别并附加标签，结果写入文章记录。

    ``fallback=True`` 时启用 T12 兜底：无命中则归入"未分类/其他"并标记未分类状态。
    """

    active_categories = category_service.list_categories(session, include_inactive=False)
    by_name = {category.name: category for category in active_categories}
    result = classifier(
        article.title,
        article.content,
        allowed_categories=set(by_name),
    )

    category = by_name.get(result.category_name) if result.category_name else None
    used_fallback = False
    if category is not None:
        article.primary_category_id = category.id
        article.status = ArticleStatus.NORMAL
    elif fallback:
        category = ensure_fallback_category(session)
        article.primary_category_id = category.id
        article.status = ArticleStatus.UNCATEGORIZED
        used_fallback = True

    article.tags = [_get_or_create_tag(session, name) for name in result.tags]

    session.commit()
    session.refresh(article)
    return ArticleClassification(
        article=article,
        category_id=category.id if category is not None else None,
        tags=list(result.tags),
        scores=result.scores,
        used_fallback=used_fallback,
    )


def classify_pending_articles(
    session: Session,
    *,
    classifier: Classifier = classify_text,
    fallback: bool = True,
    source_id: str | None = None,
) -> list[ArticleClassification]:
    """批量分类状态为"待分类"的文章（默认启用兜底）。"""

    statement = select(Article).where(Article.status == ArticleStatus.PENDING)
    if source_id is not None:
        statement = statement.where(Article.source_id == source_id)
    results = []
    for article in session.scalars(statement):
        results.append(classify_article(session, article, classifier=classifier, fallback=fallback))
    return results


def reclassify_article(
    session: Session, article_id: str, category_id: str, *, actor: str
) -> Article:
    """维护者手动将文章重新指定为某个受控类别（T12）。

    仅允许指定启用中的类别；操作后文章状态回到"正常"，查询结果同步更新。
    """

    article = session.get(Article, article_id)
    if article is None:
        raise ApiError(404, "NOT_FOUND", "文章不存在")

    category = category_service.get_category(session, category_id)
    if category.status is not CategoryStatus.ACTIVE:
        raise ApiError(422, "VALIDATION_ERROR", "不能指定已停用的类别")

    article.primary_category_id = category.id
    article.status = ArticleStatus.NORMAL
    session.commit()
    session.refresh(article)
    return article


def _get_or_create_tag(session: Session, name: str) -> Tag:
    tag = session.scalars(select(Tag).where(Tag.name == name)).first()
    if tag is None:
        tag = Tag(name=name)
        session.add(tag)
        session.flush()
    return tag
