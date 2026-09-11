"""维护者：受控类别管理接口（T07，均需 T03 访问控制）。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.security import AdminPrincipal, require_admin
from app.db.enums import CategoryStatus
from app.db.models import Category
from app.db.session import get_db
from app.schemas.category import (
    CategoryCreate,
    CategoryHistoryRead,
    CategoryListResponse,
    CategoryMerge,
    CategoryRead,
    CategoryRename,
)
from app.services import category_service

router = APIRouter(prefix="/admin/categories", tags=["admin: categories"])


@router.get("", response_model=CategoryListResponse)
def list_categories(
    include_inactive: bool = Query(default=True, description="是否包含已停用类别"),
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> CategoryListResponse:
    """列出类别（禁用类别默认一并返回，便于维护者管理）。"""

    items = category_service.list_categories(session, include_inactive=include_inactive)
    return CategoryListResponse(
        total=len(items), items=[CategoryRead.model_validate(item) for item in items]
    )


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> Category:
    """创建新类别。"""

    return category_service.create_category(session, payload.name, actor=principal.actor)


@router.post("/{category_id}/rename", response_model=CategoryRead)
def rename_category(
    category_id: str,
    payload: CategoryRename,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> Category:
    """重命名类别（含默认类别）。"""

    return category_service.rename_category(
        session, category_id, payload.new_name, actor=principal.actor
    )


@router.post("/{category_id}/merge", response_model=CategoryRead)
def merge_category(
    category_id: str,
    payload: CategoryMerge,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> Category:
    """将当前类别合并到目标类别，文章归属同步迁移。"""

    return category_service.merge_categories(
        session, category_id, payload.target_category_id, actor=principal.actor
    )


@router.post("/{category_id}/deactivate", response_model=CategoryRead)
def deactivate_category(
    category_id: str,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> Category:
    """停用类别（不再作为新文章可选分类）。"""

    return category_service.set_category_status(
        session, category_id, CategoryStatus.INACTIVE, actor=principal.actor
    )


@router.post("/{category_id}/activate", response_model=CategoryRead)
def activate_category(
    category_id: str,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> Category:
    """重新启用类别。"""

    return category_service.set_category_status(
        session, category_id, CategoryStatus.ACTIVE, actor=principal.actor
    )


@router.get("/{category_id}/history", response_model=list[CategoryHistoryRead])
def category_history(
    category_id: str,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> list[CategoryHistoryRead]:
    """查看类别的创建/重命名/合并/停用历史。"""

    records = category_service.get_category_history(session, category_id)
    return [CategoryHistoryRead.model_validate(record) for record in records]
