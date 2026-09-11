"""维护者：来源/关注领域配置接口（T04，均需 T03 访问控制）。"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.security import AdminPrincipal, require_admin
from app.db.enums import SourceListType, UpdateFrequency
from app.db.models import Source
from app.db.session import get_db
from app.scheduler.frequency import DEFAULT_FREQUENCY_INTERVALS, FREQUENCY_LABELS
from app.schemas.source import (
    FrequencyTierRead,
    SourceCreate,
    SourceListResponse,
    SourceRead,
    SourceUpdate,
)
from app.services import source_service

router = APIRouter(
    prefix="/admin/sources",
    tags=["admin: sources"],
    dependencies=[Depends(require_admin)],
)


@router.post("", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceCreate, session: Session = Depends(get_db)) -> Source:
    """新增来源：可同时配置关注领域、白/黑名单归属与权重。"""

    return source_service.create_source(session, payload)


@router.get("", response_model=SourceListResponse)
def list_sources(
    list_type: SourceListType | None = Query(default=None, description="按白名单/黑名单筛选"),
    session: Session = Depends(get_db),
) -> SourceListResponse:
    """查看来源列表，可按白名单/黑名单筛选。"""

    items = source_service.list_sources(session, list_type=list_type)
    return SourceListResponse(
        total=len(items),
        items=[SourceRead.model_validate(item) for item in items],
    )


@router.get("/frequency-tiers", response_model=list[FrequencyTierRead])
def list_frequency_tiers(
    principal: AdminPrincipal = Depends(require_admin),
) -> list[FrequencyTierRead]:
    """返回建议的更新频率档位（高频/普通/低频），供维护者选择或自定义。"""

    return [
        FrequencyTierRead(
            frequency=frequency,
            label=FREQUENCY_LABELS[frequency],
            interval_seconds=DEFAULT_FREQUENCY_INTERVALS[frequency],
        )
        for frequency in (
            UpdateFrequency.HIGH,
            UpdateFrequency.NORMAL,
            UpdateFrequency.LOW,
        )
    ]


@router.get("/{source_id}", response_model=SourceRead)
def get_source(source_id: str, session: Session = Depends(get_db)) -> Source:
    """查看单个来源/关注领域配置。"""

    return source_service.get_source(session, source_id)


@router.patch("/{source_id}", response_model=SourceRead)
def update_source(
    source_id: str, payload: SourceUpdate, session: Session = Depends(get_db)
) -> Source:
    """编辑关注领域、黑白名单归属或权重。"""

    return source_service.update_source(session, source_id, payload)
