"""维护者：订阅与推送管理接口（T24，需 T03 访问控制）。

对应 `plan.md` API 契约第 9 节：
- ``GET   /admin/subscriptions``        订阅列表（邮箱脱敏）
- ``GET   /admin/digests``              推送记录列表
- ``GET   /admin/digests/{id}``         推送记录明细（含命中方向）
- ``POST  /admin/digests/run``          手动触发（支持预演与单订阅重跑）
- ``GET   /admin/notification-settings`` / ``PATCH`` 全局推送设置（含变更历史）
- ``GET   /admin/delivery-health``      送达健康与发信合规自检
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import AdminPrincipal, require_admin
from app.db.session import get_db
from app.notifications.mailer import MailSender, build_mail_sender
from app.schemas.notification import (
    AdminSubscriptionList,
    AdminSubscriptionRead,
    DeliveryChecklistItem,
    DeliveryHealthRead,
    DigestDetailRead,
    DigestItemRead,
    DigestList,
    DigestPlanItemRead,
    DigestRead,
    DigestRunRequest,
    DigestRunResponse,
    NotificationBacklogRead,
    NotificationSettingHistoryRead,
    NotificationSettingsRead,
    NotificationSettingsUpdate,
)
from app.services import digest_scheduler_service, digest_service, notification_settings_service

router = APIRouter(prefix="/admin", tags=["admin: notifications"])


def get_mail_sender(settings: Settings = Depends(get_settings)) -> MailSender:
    """邮件发送器依赖：未开启真实发信时为记录型实现（可安全用于预演）。"""

    return build_mail_sender(settings)


@router.get("/subscriptions", response_model=AdminSubscriptionList)
def list_subscriptions(
    status: str | None = Query(default=None),
    frequency: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> AdminSubscriptionList:
    """订阅列表（邮箱脱敏；可按状态与节奏筛选）。"""

    total, items = digest_scheduler_service.list_subscriptions(
        session, status=status, frequency=frequency, page=page, page_size=page_size
    )
    return AdminSubscriptionList(
        total=total,
        page=page,
        page_size=page_size,
        items=[AdminSubscriptionRead(**item) for item in items],
    )


@router.get("/digests", response_model=DigestList)
def list_digests(
    subscription_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> DigestList:
    """推送记录列表。"""

    total, rows = digest_scheduler_service.list_digests(
        session, subscription_id=subscription_id, status=status, page=page, page_size=page_size
    )
    return DigestList(
        total=total,
        page=page,
        page_size=page_size,
        items=[DigestRead.model_validate(row) for row in rows],
    )


@router.get("/digests/{digest_id}", response_model=DigestDetailRead)
def get_digest(
    digest_id: str,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> DigestDetailRead:
    """推送记录明细：包含本期推送了哪些文章、命中了哪些方向。"""

    digest = digest_scheduler_service.get_digest(session, digest_id)
    base = DigestRead.model_validate(digest)
    return DigestDetailRead(
        **base.model_dump(),
        items=[
            DigestItemRead(**item) for item in digest_service.digest_entries_view(session, digest)
        ],
    )


@router.post("/digests/run", response_model=DigestRunResponse)
def run_digests(
    payload: DigestRunRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    sender: MailSender = Depends(get_mail_sender),
    principal: AdminPrincipal = Depends(require_admin),
) -> DigestRunResponse:
    """手动触发推送。

    - ``dry_run=true``：只返回"本次会推送什么"，不落库、不投递；
    - ``subscription_id``：只处理该订阅（单订阅重跑）；仍受周期幂等约束，不会重复打扰用户。
    """

    result = digest_scheduler_service.run_manual_digest(
        session,
        sender=sender,
        settings=settings,
        subscription_id=payload.subscription_id,
        dry_run=payload.dry_run,
    )
    if result.dry_run:
        return DigestRunResponse(
            dry_run=True,
            planned=[DigestPlanItemRead(**item) for item in result.planned],
        )
    return DigestRunResponse(
        dry_run=False,
        generated=len(result.digests),
        sent=sum(1 for digest in result.digests if digest.status.value == "sent"),
        failed=sum(1 for digest in result.digests if digest.status.value == "failed"),
        skipped_empty=sum(1 for digest in result.digests if digest.status.value == "skipped_empty"),
    )


@router.get("/notification-settings", response_model=NotificationSettingsRead)
def read_notification_settings(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: AdminPrincipal = Depends(require_admin),
) -> NotificationSettingsRead:
    """查看当前推送设置。"""

    config = notification_settings_service.get_notification_settings(session, settings)
    return NotificationSettingsRead(**vars(config))


@router.patch("/notification-settings", response_model=NotificationSettingsRead)
def update_notification_settings(
    payload: NotificationSettingsUpdate,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: AdminPrincipal = Depends(require_admin),
) -> NotificationSettingsRead:
    """调整推送设置（节奏、时间窗、单封上限、空周期策略、重试上限、暂停开关）。"""

    config = notification_settings_service.update_notification_settings(
        session,
        payload.model_dump(exclude_none=True),
        actor=principal.actor,
        settings=settings,
    )
    return NotificationSettingsRead(**vars(config))


@router.get("/notification-settings/history", response_model=list[NotificationSettingHistoryRead])
def read_notification_setting_history(
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> list[NotificationSettingHistoryRead]:
    """推送设置变更历史（谁在何时把某个配置从多少改为多少）。"""

    rows = notification_settings_service.get_setting_history(session)
    return [NotificationSettingHistoryRead.model_validate(row) for row in rows]


@router.get("/delivery-health", response_model=DeliveryHealthRead)
def read_delivery_health(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: AdminPrincipal = Depends(require_admin),
) -> DeliveryHealthRead:
    """送达健康与发信合规自检（失败率超阈值会自动暂停推送）。"""

    health = digest_scheduler_service.health_snapshot(session, settings=settings)
    return DeliveryHealthRead(
        sampled=health.sampled,
        sent=health.sent,
        failed=health.failed,
        skipped_empty=health.skipped_empty,
        failure_rate=health.failure_rate,
        threshold=health.threshold,
        paused=health.paused,
        checklist=[DeliveryChecklistItem(**item) for item in health.checklist],
    )


@router.get("/notification-backlog", response_model=NotificationBacklogRead)
def read_backlog(
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> NotificationBacklogRead:
    """运维视图：待发送 / 失败待重试 / 空周期跳过的积压统计。"""

    stats = digest_scheduler_service.backlog_stats(session)
    return NotificationBacklogRead(**stats)
