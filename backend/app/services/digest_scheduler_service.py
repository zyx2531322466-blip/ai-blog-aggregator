"""推送调度与维护者操作编排（T24）。

在 T23 的"处理单个订阅"之上补齐：
- **节奏与发送时间窗**：窗口外顺延（不发送），避免深夜打扰；
- **暂停开关**：维护者可手动暂停，失败率超阈值时系统自动暂停；
- **手动触发**：支持"只生成不投递"（预演）与单订阅重跑；
- **维护者视图**：订阅列表（邮箱脱敏）、推送记录与明细、待办积压统计。

本模块只做编排，具体投递与幂等仍由 ``digest_service`` 保证（同一周期绝不会重复发送）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.base import utcnow
from app.db.enums import DigestStatus, SubscriptionFrequency, SubscriptionStatus
from app.db.models import Digest, Subscription
from app.notifications.mailer import MailSender
from app.services import digest_service, notification_settings_service, subscription_service
from app.services.notification_settings_service import DeliveryHealth, NotificationSettings


@dataclass
class NotificationRunSummary:
    """一轮推送调度的结果摘要。"""

    in_window: bool
    paused: bool
    paused_reason: str | None = None
    generated: int = 0
    sent: int = 0
    failed: int = 0
    skipped_empty: int = 0
    digests: list[Digest] = field(default_factory=list)

    @property
    def processed(self) -> int:
        return len(self.digests)


@dataclass
class ManualRunResult:
    """手动触发结果（``dry_run`` 时只返回计划，不落库、不投递）。"""

    dry_run: bool
    planned: list[dict[str, object]]
    digests: list[Digest] = field(default_factory=list)


def pause_reason(config: NotificationSettings) -> str | None:
    """返回当前暂停原因（未暂停则返回 None）。"""

    return "维护者已暂停推送" if config.sends_paused else None


def _summarize(
    digests: list[Digest], *, in_window: bool, paused: bool, reason: str | None
) -> NotificationRunSummary:
    return NotificationRunSummary(
        in_window=in_window,
        paused=paused,
        paused_reason=reason,
        generated=len(digests),
        sent=sum(1 for digest in digests if digest.status is DigestStatus.SENT),
        failed=sum(1 for digest in digests if digest.status is DigestStatus.FAILED),
        skipped_empty=sum(1 for digest in digests if digest.status is DigestStatus.SKIPPED_EMPTY),
        digests=digests,
    )


def run_scheduled_digests(
    session: Session,
    *,
    sender: MailSender,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> NotificationRunSummary:
    """调度入口：由定时任务调用。窗口外或暂停时只返回状态，不做任何发送。"""

    base = settings or get_settings()
    moment = now or utcnow()
    effective = notification_settings_service.effective_app_settings(session, base)
    config = notification_settings_service.get_notification_settings(session, base)

    reason = pause_reason(config)
    if reason:
        return _summarize([], in_window=True, paused=True, reason=reason)

    if not notification_settings_service.in_send_window(config, moment):
        return _summarize(
            [],
            in_window=False,
            paused=False,
            reason=(
                f"当前 {moment.hour} 点不在发送时间窗 "
                f"{config.send_window_start_hour}:00-{config.send_window_end_hour}:00 内，已顺延"
            ),
        )

    digests = digest_service.run_digest_cycle(
        session, sender=sender, settings=effective, now=moment
    )
    # 送达健康评估：失败率超阈值会自动暂停（并留下系统变更记录）
    health = notification_settings_service.evaluate_delivery_health(
        session, settings=base, clock=moment
    )
    return _summarize(
        digests,
        in_window=True,
        paused=health.paused,
        reason="失败率超过阈值，已自动暂停推送" if health.paused else None,
    )


def _target_subscriptions(session: Session, subscription_id: str | None) -> list[Subscription]:
    if subscription_id is None:
        return list(
            session.scalars(
                select(Subscription).where(Subscription.status == SubscriptionStatus.CONFIRMED)
            ).all()
        )
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise ApiError(404, "NOT_FOUND", "订阅不存在")
    return [subscription]


def run_manual_digest(
    session: Session,
    *,
    sender: MailSender,
    settings: Settings | None = None,
    now: datetime | None = None,
    subscription_id: str | None = None,
    dry_run: bool = False,
) -> ManualRunResult:
    """维护者手动触发。

    - ``dry_run=True``：只计算"本次会推送哪些内容"，不落库、不投递（用于预演与排障）；
    - 否则对目标订阅执行一次投递；**仍受周期幂等约束**（同一周期重跑不会重复发送）。
    """

    base = settings or get_settings()
    moment = now or utcnow()
    effective = notification_settings_service.effective_app_settings(session, base)
    targets = _target_subscriptions(session, subscription_id)

    if dry_run:
        planned: list[dict[str, object]] = []
        for subscription in targets:
            period_start, period_end = digest_service.period_bucket(subscription.frequency, moment)
            existing = digest_service._existing_digest(
                session, subscription.id, period_start, period_end
            )
            if subscription.status is not SubscriptionStatus.CONFIRMED:
                scheduled = 0
                note = "订阅未确认或已退订，不会推送"
            elif existing is not None:
                scheduled = 0
                note = f"本周期已处理（状态：{existing.status.value}）"
            else:
                scheduled = len(digest_service.collect_entries(session, subscription, now=moment))
                note = "可发送" if scheduled else "本周期无新增内容"
            planned.append(
                {
                    "subscription_id": subscription.id,
                    "email": subscription_service.mask_email(subscription.email),
                    "planned_items": scheduled,
                    "note": note,
                }
            )
        return ManualRunResult(dry_run=True, planned=planned)

    digests: list[Digest] = []
    for subscription in targets:
        digest = digest_service.process_subscription(
            session, subscription, sender=sender, settings=effective, now=moment, force=True
        )
        if digest is not None:
            digests.append(digest)
    return ManualRunResult(dry_run=False, planned=[], digests=digests)


def backlog_stats(session: Session) -> dict[str, int]:
    """运维视图：待发送、失败待重试、空周期跳过的数量。"""

    def _count(status: DigestStatus) -> int:
        return int(
            session.scalar(select(func.count()).select_from(Digest).where(Digest.status == status))
            or 0
        )

    return {
        "pending": _count(DigestStatus.PENDING),
        "sent": _count(DigestStatus.SENT),
        "failed": _count(DigestStatus.FAILED),
        "skipped_empty": _count(DigestStatus.SKIPPED_EMPTY),
    }


def list_subscriptions(
    session: Session,
    *,
    status: str | None = None,
    frequency: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[dict[str, object]]]:
    """维护者订阅列表（邮箱脱敏，支持按状态与节奏筛选）。"""

    statement = select(Subscription)
    if status:
        try:
            statement = statement.where(Subscription.status == SubscriptionStatus(status))
        except ValueError:
            raise ApiError(
                400, "VALIDATION_ERROR", "状态只支持 pending_confirmation/confirmed/unsubscribed"
            ) from None
    if frequency:
        try:
            statement = statement.where(Subscription.frequency == SubscriptionFrequency(frequency))
        except ValueError:
            raise ApiError(400, "VALIDATION_ERROR", "节奏只支持 daily 或 weekly") from None

    total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = session.scalars(
        statement.order_by(Subscription.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items: list[dict[str, object]] = []
    for subscription in rows:
        topics = subscription_service.subscription_topics(session, subscription)
        items.append(
            {
                "id": subscription.id,
                "email": subscription_service.mask_email(subscription.email),
                "status": subscription.status.value,
                "frequency": subscription.frequency.value,
                "max_items": subscription.max_items,
                "topic_count": len(topics),
                "last_sent_at": subscription.last_sent_at,
                "created_at": subscription.created_at,
            }
        )
    return total, items


def list_digests(
    session: Session,
    *,
    subscription_id: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[Digest]]:
    """推送记录列表（可按订阅与状态筛选）。"""

    statement = select(Digest)
    if subscription_id:
        statement = statement.where(Digest.subscription_id == subscription_id)
    if status:
        try:
            statement = statement.where(Digest.status == DigestStatus(status))
        except ValueError:
            raise ApiError(
                400, "VALIDATION_ERROR", "状态只支持 pending/sent/failed/skipped_empty"
            ) from None

    total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = list(
        session.scalars(
            statement.order_by(Digest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return total, rows


def get_digest(session: Session, digest_id: str) -> Digest:
    digest = session.get(Digest, digest_id)
    if digest is None:
        raise ApiError(404, "NOT_FOUND", "推送记录不存在")
    return digest


def health_snapshot(session: Session, *, settings: Settings | None = None) -> DeliveryHealth:
    """送达健康与合规自检快照。"""

    return notification_settings_service.evaluate_delivery_health(session, settings=settings)
