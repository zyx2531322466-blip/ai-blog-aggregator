"""文章浏览接口（T10，公开匿名访问）。"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.article import ArticleDetail, ArticleListResponse
from app.services import query_service
from app.services.query_service import ArticleFilters

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=ArticleListResponse)
def list_articles(
    category: str | None = Query(default=None, description="按主类别（ID 或名称）筛选"),
    tag: str | None = Query(default=None, description="按标签（ID 或名称）筛选"),
    source: str | None = Query(default=None, description="按来源（ID/名称/站点地址）筛选"),
    start_date: datetime | None = Query(default=None, description="起始时间（ISO 8601）"),
    end_date: datetime | None = Query(default=None, description="结束时间（ISO 8601）"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
) -> ArticleListResponse:
    """分页查询文章列表，支持类别/标签/来源/时间筛选。"""

    filters = ArticleFilters(
        category=category,
        tag=tag,
        source=source,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )
    total, articles = query_service.list_articles(session, filters)
    items = [query_service.build_list_item(session, article) for article in articles]
    return ArticleListResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/{article_id}", response_model=ArticleDetail)
def get_article(article_id: str, session: Session = Depends(get_db)) -> ArticleDetail:
    """文章详情，含合并组的全部来源。"""

    return query_service.get_article_detail(session, article_id)
