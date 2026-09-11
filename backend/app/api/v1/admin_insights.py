"""维护者：效果概览接口（T20，需 T03 访问控制）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import AdminPrincipal, require_admin
from app.db.session import get_db
from app.schemas.insights import InsightsRead
from app.services import insights_service

router = APIRouter(prefix="/admin/insights", tags=["admin: insights"])


@router.get("", response_model=InsightsRead)
def get_insights(
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> InsightsRead:
    """返回分类分布与去重命中统计。"""

    result = insights_service.build_insights(session)
    return InsightsRead(
        category_distribution=result.category_distribution,
        dedup_stats=result.dedup_stats,
    )
