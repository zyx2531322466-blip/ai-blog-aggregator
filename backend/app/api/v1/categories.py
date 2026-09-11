"""公开分类导航接口（plan.md API 3，供前端筛选使用）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.category import PublicCategoryItem, PublicCategoryList
from app.services import query_service

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=PublicCategoryList)
def list_categories(session: Session = Depends(get_db)) -> PublicCategoryList:
    """返回启用中的类别及其可见文章计数。"""

    counts = query_service.list_active_categories_with_counts(session)
    return PublicCategoryList(
        categories=[PublicCategoryItem(name=name, article_count=count) for name, count in counts]
    )
