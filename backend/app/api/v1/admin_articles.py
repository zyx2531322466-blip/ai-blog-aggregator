"""维护者：文章维度的管理接口（T12 重新归类、T18 主记录失效切换）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import AdminPrincipal, require_admin
from app.db.models import Article
from app.db.session import get_db
from app.schemas.article import ArticleDetail, ArticleReclassifyRequest
from app.schemas.dedup import ArticleInaccessibleResponse
from app.services import classifier_service, primary_selection_service, query_service

router = APIRouter(prefix="/admin/articles", tags=["admin: articles"])


@router.post("/{article_id}/category", response_model=ArticleDetail)
def reclassify_article(
    article_id: str,
    payload: ArticleReclassifyRequest,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> ArticleDetail:
    """将（通常是未分类的）文章重新指定为某个受控类别。"""

    article = classifier_service.reclassify_article(
        session, article_id, payload.category_id, actor=principal.actor
    )
    return query_service.get_article_detail(session, article.id)


@router.post("/{article_id}/inaccessible", response_model=ArticleInaccessibleResponse)
def mark_article_inaccessible(
    article_id: str,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> ArticleInaccessibleResponse:
    """标记原文不可访问，并自动触发所属合并组的主记录切换（T18）。"""

    article = session.get(Article, article_id)
    if article is None:
        raise ApiError(404, "NOT_FOUND", "文章不存在")

    primary_selection_service.mark_article_inaccessible(session, article_id)
    session.commit()

    group_key = primary_selection_service.group_key_for_article(session, article_id)
    if group_key is None:
        return ArticleInaccessibleResponse(
            article_id=article_id, is_accessible=False, group_refreshed=False
        )

    result = primary_selection_service.select_and_apply_primary(session, group_key)
    session.commit()
    return ArticleInaccessibleResponse(
        article_id=article_id,
        is_accessible=False,
        group_refreshed=True,
        primary_id=result.primary_id if result is not None else None,
        changed=result.changed if result is not None else False,
    )
