"""维护者：去重策略管理与审计接口（T13 / T15，需 T03 访问控制）。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import AdminPrincipal, require_admin
from app.db.models import Article
from app.db.session import get_db
from app.schemas.dedup import (
    DedupArticleRef,
    DedupGroupList,
    DedupGroupMemberRead,
    DedupGroupRead,
    DedupHitList,
    DedupHitRead,
    DedupPreviewChangeRead,
    DedupPreviewRead,
    DedupPreviewRequest,
    DedupRollbackRequest,
    DedupSettingHistoryRead,
    DedupSettingsRead,
    DedupSettingsUpdate,
    PrimaryRefreshResponse,
    PrimaryRefreshResultRead,
)
from app.services import dedup_service, dedup_settings_service, primary_selection_service

router = APIRouter(prefix="/admin/dedup", tags=["admin: dedup"])


@router.get("/settings", response_model=DedupSettingsRead)
def get_settings(
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> DedupSettingsRead:
    """查看当前去重阈值配置。"""

    return DedupSettingsRead(
        near_duplicate_threshold=dedup_settings_service.get_near_duplicate_threshold(session)
    )


@router.patch("/settings", response_model=DedupSettingsRead)
def update_settings(
    payload: DedupSettingsUpdate,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> DedupSettingsRead:
    """调整近重复判定阈值（调低更激进、调高更保守），并记录变更历史。"""

    value = dedup_settings_service.set_near_duplicate_threshold(
        session, payload.near_duplicate_threshold, actor=principal.actor
    )
    return DedupSettingsRead(near_duplicate_threshold=value)


@router.get("/history", response_model=list[DedupSettingHistoryRead])
def list_history(
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> list[DedupSettingHistoryRead]:
    """查看阈值变更记录。"""

    records = dedup_settings_service.get_setting_history(session)
    return [DedupSettingHistoryRead.model_validate(record) for record in records]


@router.post("/rollback", response_model=DedupSettingsRead)
def rollback_settings(
    payload: DedupRollbackRequest,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> DedupSettingsRead:
    """回滚到某次变更之前的阈值配置。"""

    value = dedup_settings_service.rollback_setting(
        session, payload.history_id, actor=principal.actor
    )
    return DedupSettingsRead(near_duplicate_threshold=value)


@router.post("/preview", response_model=DedupPreviewRead)
def preview_settings(
    payload: DedupPreviewRequest,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> DedupPreviewRead:
    """预览采用新阈值后，现有去重判定会如何变化（不落库）。"""

    preview = dedup_service.preview_threshold_change(session, payload.near_duplicate_threshold)
    return DedupPreviewRead(
        current_threshold=preview.current_threshold,
        proposed_threshold=preview.proposed_threshold,
        would_merge=[_change(item) for item in preview.would_merge],
        would_unmerge=[_change(item) for item in preview.would_unmerge],
        would_relate=[_change(item) for item in preview.would_relate],
        would_unrelate=[_change(item) for item in preview.would_unrelate],
        unchanged_count=preview.unchanged_count,
    )


@router.get("/hits", response_model=DedupHitList)
def list_hits(
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> DedupHitList:
    """查看去重命中记录：判定类型、依据与涉及来源。"""

    items = []
    for relation, target, member in dedup_service.list_relation_hits(session):
        items.append(
            DedupHitRead(
                id=relation.id,
                group_key=relation.group_key,
                relation_type=relation.relation_type.value,
                similarity=relation.similarity,
                evidence=relation.evidence,
                created_at=relation.created_at,
                primary=_article_ref(target),
                duplicate=_article_ref(member),
            )
        )
    return DedupHitList(total=len(items), items=items)


@router.get("/groups", response_model=DedupGroupList)
def list_groups(
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> DedupGroupList:
    """查看全部合并组：主记录与全部成员（含权重/时间/完整度/可访问性）。"""

    items = [
        _group_read(session, group_key)
        for group_key in primary_selection_service.get_group_keys(session)
    ]
    return DedupGroupList(total=len(items), items=items)


@router.post("/groups/refresh", response_model=PrimaryRefreshResponse)
def refresh_groups(
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> PrimaryRefreshResponse:
    """重新应用主记录选择规则（检测失效并切换）。"""

    results = primary_selection_service.refresh_all_group_primaries(session)
    return PrimaryRefreshResponse(
        refreshed=len(results),
        changed=sum(1 for result in results if result.changed),
        results=[
            PrimaryRefreshResultRead(
                group_key=result.group_key,
                previous_primary_id=result.previous_primary_id,
                primary_id=result.primary_id,
                changed=result.changed,
            )
            for result in results
        ],
    )


@router.post("/groups/{group_key}/refresh", response_model=PrimaryRefreshResultRead)
def refresh_group(
    group_key: str,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> PrimaryRefreshResultRead:
    """重新选择某个合并组的主记录。"""

    result = primary_selection_service.select_and_apply_primary(session, group_key)
    if result is None:
        raise ApiError(404, "NOT_FOUND", "合并组不存在")
    return PrimaryRefreshResultRead(
        group_key=result.group_key,
        previous_primary_id=result.previous_primary_id,
        primary_id=result.primary_id,
        changed=result.changed,
    )


def _group_read(session: Session, group_key: str) -> DedupGroupRead:
    members = primary_selection_service.get_group_members_by_key(session, group_key)
    primary_id = primary_selection_service.current_primary_id(session, group_key)
    return DedupGroupRead(
        group_key=group_key,
        primary_id=primary_id,
        members=[
            DedupGroupMemberRead(
                id=member.id,
                title=member.title,
                url=member.url,
                source_name=member.source.name if member.source is not None else None,
                weight=member.source.weight if member.source is not None else 0.0,
                published_at=member.published_at,
                content_length=len(member.content or ""),
                is_accessible=member.is_accessible,
                is_primary=member.id == primary_id,
            )
            for member in members
        ],
    )


def _change(item: dedup_service.PairChange) -> DedupPreviewChangeRead:
    return DedupPreviewChangeRead(
        article_id=item.article_id,
        other_article_id=item.other_article_id,
        similarity=item.similarity,
        current=item.current,
        proposed=item.proposed,
    )


def _article_ref(article: Article | None) -> DedupArticleRef | None:
    if article is None:
        return None
    return DedupArticleRef(
        id=article.id,
        title=article.title,
        url=article.url,
        source_name=article.source.name if article.source is not None else None,
    )
