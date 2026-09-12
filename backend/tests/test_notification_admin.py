"""T24 推送调度、维护者管理与送达合规测试。

覆盖：默认设置与变更历史、参数校验、发送时间窗顺延、暂停开关、
手动触发（预演/单订阅重跑）与幂等、失败率超阈值自动暂停、合规自检项、
维护者接口（脱敏列表、推送明细、积压统计）与鉴权。
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1 import admin_notifications
from app.core.config import Settings
from app.db.enums import (
    ArticleStatus,
    CategoryStatus,
    DigestStatus,
    SubscriptionFrequency,
    SubscriptionStatus,
    SubscriptionTopicType,
)
from app.db.models import (
    Article,
    Category,
    Digest,
    NotificationSettingHistory,
    Source,
    Subscription,
)
from app.notifications.mailer import RecordingMailSender
from app.services import digest_scheduler_service, digest_service, notification_settings_service
from app.services.subscription_service import TopicInput

NOW = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)  # 周一 10 点（默认时间窗内）


def build_settings(**overrides: object) -> Settings:
    """测试用配置（保持本模块自包含，与 conftest 的约定一致）。"""

    base: dict[str, object] = {
        "environment": "test",
        "admin_token": "test-admin-token",
        "admin_actor": "test-admin",
        "database_url": "sqlite+pysqlite:///:memory:",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def make_category(session: Session, name: str = "AI/机器学习") -> Category:
    category = Category(name=name, status=CategoryStatus.ACTIVE)
    session.add(category)
    session.commit()
    return category


def make_source(session: Session) -> Source:
    source = Source(name="示例博客", site_url="https://blog.example.com/")
    session.add(source)
    session.commit()
    return source


def db_category_missing(session: Session, name: str) -> bool:
    """类别是否尚未创建。"""

    return session.scalars(select(Category).where(Category.name == name)).first() is None


def make_article(
    session: Session, *, title: str, url: str, source: Source, category: Category
) -> Article:
    article = Article(
        title=title,
        content="正文",
        summary="摘要",
        url=url,
        source_id=source.id,
        primary_category_id=category.id,
        status=ArticleStatus.NORMAL,
        crawled_at=NOW,
    )
    session.add(article)
    session.commit()
    return article


def confirmed_subscription(
    session: Session,
    *,
    email: str = "reader@example.com",
    frequency: str = "daily",
    confirmed_days_ago: int = 3,
    topics: list[TopicInput] | None = None,
) -> Subscription:
    from app.services import subscription_service

    if topics is None:
        # 订阅方向必须真实存在，这里按需创建（测试辅助）
        if db_category_missing(session, "AI/机器学习"):
            make_category(session, "AI/机器学习")
        topics = [TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")]
    subscription, token = subscription_service.create_subscription(
        session, email=email, topics=topics, frequency=frequency
    )
    subscription_service.confirm_subscription(session, token)
    session.refresh(subscription)
    subscription.confirmed_at = NOW - timedelta(days=confirmed_days_ago)
    session.commit()
    return subscription


# ---------------------------------------------------------------------------
# 设置与合规
# ---------------------------------------------------------------------------


def test_default_settings_come_from_app_config(db_session: Session) -> None:
    config = notification_settings_service.get_notification_settings(
        db_session, build_settings(digest_max_items=7, digest_default_frequency="daily")
    )

    assert config.max_items_per_digest == 7
    assert config.default_frequency == "daily"
    assert config.sends_paused is False
    assert config.send_window_start_hour == 9 and config.send_window_end_hour == 21


def test_update_settings_records_history(db_session: Session) -> None:
    updated = notification_settings_service.update_notification_settings(
        db_session,
        {"max_items_per_digest": 5, "send_window_start_hour": 8},
        actor="tester",
    )

    assert updated.max_items_per_digest == 5
    assert updated.send_window_start_hour == 8
    rows = notification_settings_service.get_setting_history(db_session)
    assert {row.key for row in rows} == {"max_items_per_digest", "send_window_start_hour"}
    assert all(row.actor == "tester" for row in rows)
    assert {row.new_value for row in rows} == {"5", "8"}


def test_invalid_settings_are_rejected(db_session: Session) -> None:
    from app.core.errors import ApiError
    from app.services import notification_settings_service as service

    with pytest.raises(ApiError):
        service.update_notification_settings(db_session, {"default_frequency": "hourly"})

    with pytest.raises(ApiError):
        service.update_notification_settings(db_session, {"max_items_per_digest": 999})

    with pytest.raises(ApiError):
        service.update_notification_settings(
            db_session, {"send_window_start_hour": 22, "send_window_end_hour": 8}
        )

    assert db_session.scalar(select(func.count()).select_from(NotificationSettingHistory)) == 0


def test_send_window_blocks_off_hours(db_session: Session) -> None:
    """窗口外顺延：不发送、不落库，仅返回状态说明。"""

    config = notification_settings_service.get_notification_settings(db_session, build_settings())

    assert notification_settings_service.in_send_window(config, NOW) is True
    assert notification_settings_service.in_send_window(config, NOW.replace(hour=3)) is False


def test_scheduled_run_outside_window_does_not_send(db_session: Session) -> None:
    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session, title="内容", url="https://a.example.com/1", source=source, category=category
    )
    confirmed_subscription(db_session)

    sender = RecordingMailSender()
    summary = digest_scheduler_service.run_scheduled_digests(
        db_session, sender=sender, settings=build_settings(), now=NOW.replace(hour=3)
    )

    assert summary.in_window is False
    assert summary.processed == 0
    assert sender.messages == []
    assert db_session.scalar(select(func.count()).select_from(Digest)) == 0


def test_paused_setting_blocks_sending(db_session: Session) -> None:
    """维护者暂停后不发送，并给出明确原因。"""

    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session, title="内容", url="https://a.example.com/2", source=source, category=category
    )
    confirmed_subscription(db_session)
    notification_settings_service.update_notification_settings(
        db_session, {"sends_paused": True}, actor="tester"
    )

    sender = RecordingMailSender()
    summary = digest_scheduler_service.run_scheduled_digests(
        db_session, sender=sender, settings=build_settings(), now=NOW
    )

    assert summary.paused is True
    assert summary.paused_reason == "维护者已暂停推送"
    assert sender.messages == []


def test_scheduled_run_sends_and_reports(db_session: Session) -> None:
    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session, title="内容", url="https://a.example.com/3", source=source, category=category
    )
    confirmed_subscription(db_session)

    sender = RecordingMailSender()
    summary = digest_scheduler_service.run_scheduled_digests(
        db_session, sender=sender, settings=build_settings(), now=NOW
    )

    assert summary.in_window is True and summary.paused is False
    assert summary.sent == 1 and summary.failed == 0
    assert len(sender.messages) == 1


def test_auto_pause_when_failure_rate_exceeds_threshold(db_session: Session) -> None:
    """失败率超过阈值 → 自动暂停，并留下"系统暂停"的变更记录。"""

    subscription = confirmed_subscription(db_session)
    for index in range(3):
        db_session.add(
            Digest(
                subscription_id=subscription.id,
                period_start=NOW - timedelta(days=index + 1),
                period_end=NOW - timedelta(days=index),
                status=DigestStatus.FAILED,
                item_count=1,
                retry_count=3,
                error="smtp timeout",
            )
        )
    db_session.commit()

    health = notification_settings_service.evaluate_delivery_health(
        db_session, settings=build_settings(bounce_pause_threshold=0.2)
    )

    assert health.failed == 3 and health.sent == 0
    assert health.failure_rate == 1.0
    assert health.paused is True

    config = notification_settings_service.get_notification_settings(db_session, build_settings())
    assert config.sends_paused is True
    history = notification_settings_service.get_setting_history(db_session)
    assert any(
        row.actor == "system" and row.key == "sends_paused" and row.new_value == "true"
        for row in history
    )


def test_health_checklist_covers_compliance_items(db_session: Session) -> None:
    health = digest_scheduler_service.health_snapshot(db_session, settings=build_settings())

    items = {entry["item"] for entry in health.checklist}
    assert "真实发信开关" in items
    assert "退订链接可达性" in items
    assert any("SPF" in item for item in items)
    assert health.paused is False


def test_dry_run_plans_without_delivery(db_session: Session) -> None:
    """预演：只返回计划，不落库、不投递。"""

    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session, title="内容", url="https://a.example.com/4", source=source, category=category
    )
    subscription = confirmed_subscription(db_session)

    sender = RecordingMailSender()
    result = digest_scheduler_service.run_manual_digest(
        db_session,
        sender=sender,
        settings=build_settings(),
        now=NOW,
        subscription_id=subscription.id,
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.planned[0]["planned_items"] == 1
    assert result.planned[0]["note"] == "可发送"
    assert "reader" not in str(result.planned[0]["email"])  # 邮箱脱敏
    assert sender.messages == []
    assert db_session.scalar(select(func.count()).select_from(Digest)) == 0


def test_manual_run_is_idempotent_within_period(db_session: Session) -> None:
    """单订阅重跑不会重复发送（同周期幂等）。"""

    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session, title="内容", url="https://a.example.com/5", source=source, category=category
    )
    subscription = confirmed_subscription(db_session, frequency="weekly", confirmed_days_ago=8)

    sender = RecordingMailSender()
    first = digest_scheduler_service.run_manual_digest(
        db_session,
        sender=sender,
        settings=build_settings(),
        now=NOW,
        subscription_id=subscription.id,
    )
    second = digest_scheduler_service.run_manual_digest(
        db_session,
        sender=sender,
        settings=build_settings(),
        now=NOW + timedelta(minutes=30),
        subscription_id=subscription.id,
    )

    assert len(first.digests) == 1 and first.digests[0].status is DigestStatus.SENT
    assert len(second.digests) == 1 and second.digests[0].id == first.digests[0].id
    assert len(sender.messages) == 1
    assert db_session.scalar(select(func.count()).select_from(Digest)) == 1


def test_backlog_stats_counts_each_status(db_session: Session) -> None:
    subscription = confirmed_subscription(db_session)
    for index, status in enumerate(
        (DigestStatus.SENT, DigestStatus.FAILED, DigestStatus.SKIPPED_EMPTY)
    ):
        db_session.add(
            Digest(
                subscription_id=subscription.id,
                period_start=NOW - timedelta(days=index + 1),
                period_end=NOW - timedelta(days=index),
                status=status,
                item_count=0,
            )
        )
    db_session.commit()

    stats = digest_scheduler_service.backlog_stats(db_session)

    assert stats["sent"] == 1 and stats["failed"] == 1 and stats["skipped_empty"] == 1


# ---------------------------------------------------------------------------
# HTTP 层（维护者接口）
# ---------------------------------------------------------------------------


@pytest.fixture()
def admin_sender() -> RecordingMailSender:
    return RecordingMailSender()


@pytest.fixture()
def admin_client(api_app: FastAPI, admin_sender: RecordingMailSender) -> TestClient:
    """覆盖维护者推送接口的邮件发送器（不真实发信）。"""

    api_app.dependency_overrides[admin_notifications.get_mail_sender] = lambda: admin_sender
    with TestClient(api_app) as test_client:
        yield test_client
    api_app.dependency_overrides.pop(admin_notifications.get_mail_sender, None)


def test_admin_settings_and_history_api(
    admin_client: TestClient, admin_headers: dict[str, str]
) -> None:
    current = admin_client.get("/api/v1/admin/notification-settings", headers=admin_headers)
    assert current.status_code == 200
    assert current.json()["sends_paused"] is False

    updated = admin_client.patch(
        "/api/v1/admin/notification-settings",
        headers=admin_headers,
        json={"max_items_per_digest": 6, "sends_paused": True},
    )
    assert updated.status_code == 200
    assert updated.json()["max_items_per_digest"] == 6
    assert updated.json()["sends_paused"] is True

    history = admin_client.get("/api/v1/admin/notification-settings/history", headers=admin_headers)
    assert history.status_code == 200
    keys = {row["key"] for row in history.json()}
    assert {"max_items_per_digest", "sends_paused"} <= keys
    assert all(row["actor"] == "test-admin" for row in history.json())

    invalid = admin_client.patch(
        "/api/v1/admin/notification-settings",
        headers=admin_headers,
        json={"send_window_start_hour": 20, "send_window_end_hour": 6},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"


def test_admin_subscriptions_and_digests_api(
    admin_client: TestClient, admin_headers: dict[str, str], api_session: Session, admin_sender
) -> None:
    category = make_category(api_session)
    source = make_source(api_session)
    make_article(
        api_session, title="内容", url="https://a.example.com/api", source=source, category=category
    )
    subscription = confirmed_subscription(
        api_session, email="api@example.com", frequency="weekly", confirmed_days_ago=8
    )

    listing = admin_client.get("/api/v1/admin/subscriptions", headers=admin_headers)
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == "ap*@example.com"
    assert body["items"][0]["topic_count"] == 1

    filtered = admin_client.get(
        "/api/v1/admin/subscriptions",
        headers=admin_headers,
        params={"status": "pending_confirmation"},
    )
    assert filtered.json()["total"] == 0

    bad_filter = admin_client.get(
        "/api/v1/admin/subscriptions", headers=admin_headers, params={"status": "unknown"}
    )
    assert bad_filter.status_code == 400

    # 手动触发 → 产生一条已发送记录
    run = admin_client.post(
        "/api/v1/admin/digests/run",
        headers=admin_headers,
        json={"subscription_id": subscription.id},
    )
    assert run.status_code == 200
    assert run.json()["sent"] == 1
    assert len(admin_sender.messages) == 1

    digests = admin_client.get("/api/v1/admin/digests", headers=admin_headers)
    assert digests.json()["total"] == 1
    digest_id = digests.json()["items"][0]["id"]

    detail = admin_client.get(f"/api/v1/admin/digests/{digest_id}", headers=admin_headers)
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["status"] == "sent"
    assert detail_body["items"][0]["matched_topics"] == ["类别：AI/机器学习"]
    assert detail_body["items"][0]["title"] == "内容"

    missing = admin_client.get("/api/v1/admin/digests/digest_missing", headers=admin_headers)
    assert missing.status_code == 404

    backlog = admin_client.get("/api/v1/admin/notification-backlog", headers=admin_headers)
    assert backlog.status_code == 200
    assert backlog.json()["sent"] == 1


def test_admin_dry_run_api_does_not_send(
    admin_client: TestClient, admin_headers: dict[str, str], api_session: Session, admin_sender
) -> None:
    category = make_category(api_session)
    source = make_source(api_session)
    make_article(
        api_session, title="内容", url="https://a.example.com/dry", source=source, category=category
    )
    subscription = confirmed_subscription(api_session, email="dry@example.com")

    preview = admin_client.post(
        "/api/v1/admin/digests/run",
        headers=admin_headers,
        json={"subscription_id": subscription.id, "dry_run": True},
    )

    assert preview.status_code == 200
    payload = preview.json()
    assert payload["dry_run"] is True
    assert payload["planned"][0]["planned_items"] == 1
    assert admin_sender.messages == []
    assert api_session.scalar(select(func.count()).select_from(Digest)) == 0


def test_delivery_health_api(admin_client: TestClient, admin_headers: dict[str, str]) -> None:
    response = admin_client.get("/api/v1/admin/delivery-health", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["paused"] is False
    assert any("SPF" in item["item"] for item in body["checklist"])


def test_admin_notification_endpoints_require_authorization(admin_client: TestClient) -> None:
    for method, path in (
        ("get", "/api/v1/admin/subscriptions"),
        ("get", "/api/v1/admin/digests"),
        ("get", "/api/v1/admin/notification-settings"),
        ("patch", "/api/v1/admin/notification-settings"),
        ("post", "/api/v1/admin/digests/run"),
        ("get", "/api/v1/admin/delivery-health"),
        ("get", "/api/v1/admin/notification-backlog"),
    ):
        client_call = getattr(admin_client, method)
        response = client_call(path) if method == "get" else client_call(path, json={})
        assert response.status_code in (401, 403), f"{method} {path} 未拒绝未授权访问"


def test_subscription_frequency_filter_and_status_lifecycle(db_session: Session) -> None:
    """状态与节奏筛选在服务层生效（含未确认订阅不出现在推送范围）。"""

    subscription = confirmed_subscription(db_session, frequency="weekly")

    total, items = digest_scheduler_service.list_subscriptions(db_session, frequency="weekly")
    assert total == 1 and items[0]["frequency"] == "weekly"

    total_daily, _ = digest_scheduler_service.list_subscriptions(db_session, frequency="daily")
    assert total_daily == 0

    subscription.status = SubscriptionStatus.UNSUBSCRIBED
    db_session.commit()
    total_confirmed, _ = digest_scheduler_service.list_subscriptions(db_session, status="confirmed")
    assert total_confirmed == 0

    from app.core.errors import ApiError

    with pytest.raises(ApiError):
        digest_scheduler_service.list_digests(db_session, status="unknown")


def test_digest_entries_view_and_get_digest(db_session: Session) -> None:
    """明细视图返回条目标题与原链接；不存在的记录抛 404。"""

    category = make_category(db_session)
    source = make_source(db_session)
    article = make_article(
        db_session,
        title="明细内容",
        url="https://a.example.com/detail",
        source=source,
        category=category,
    )
    subscription = confirmed_subscription(db_session)
    sender = RecordingMailSender()
    digest = digest_service.process_subscription(
        db_session, subscription, sender=sender, settings=build_settings(), now=NOW
    )
    assert digest is not None

    view = digest_service.digest_entries_view(db_session, digest)
    assert view[0]["article_id"] == article.id
    assert view[0]["title"] == "明细内容"
    assert view[0]["url"] == "https://a.example.com/detail"

    assert digest_scheduler_service.get_digest(db_session, digest.id).id == digest.id

    from app.core.errors import ApiError

    with pytest.raises(ApiError):
        digest_scheduler_service.get_digest(db_session, "digest_missing")


def test_subscription_frequency_enum_guard() -> None:
    """节奏枚举与订阅服务保持一致（daily/weekly）。"""

    assert {item.value for item in SubscriptionFrequency} == {"daily", "weekly"}
    assert SubscriptionStatus.CONFIRMED.value == "confirmed"
