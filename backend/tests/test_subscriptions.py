"""T22 订阅生命周期与反滥用测试。

覆盖：创建（待确认）→ 确认 → 自助查询 → 退订 → 删除；
以及凭证安全（过期/无效/一次性）、方向校验、重复订阅、频控与脱敏。
"""

from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.subscriptions import get_mail_sender
from app.core.errors import ApiError
from app.db.base import utcnow
from app.db.enums import (
    CategoryStatus,
    SubscriptionFrequency,
    SubscriptionStatus,
    SubscriptionTopicType,
)
from app.db.models import Category, Source, Subscription, SubscriptionTopic
from app.notifications.mailer import RecordingMailSender
from app.services import subscription_service
from app.services.subscription_service import TopicInput


def make_category(session: Session, name: str = "AI/机器学习") -> Category:
    category = Category(name=name, status=CategoryStatus.ACTIVE)
    session.add(category)
    session.commit()
    return category


def make_source(session: Session, site_url: str = "https://blog.example.com/") -> Source:
    source = Source(name="示例博客", site_url=site_url)
    session.add(source)
    session.commit()
    return source


def topics_for(**kwargs: str) -> list[TopicInput]:
    mapping = {
        "category": SubscriptionTopicType.CATEGORY,
        "tag": SubscriptionTopicType.TAG,
        "source": SubscriptionTopicType.SOURCE,
        "keyword": SubscriptionTopicType.KEYWORD,
    }
    return [TopicInput(topic_type=mapping[key], topic_value=value) for key, value in kwargs.items()]


def test_create_subscription_is_pending_until_confirmed(db_session: Session) -> None:
    """未确认的订阅不应生效；确认后才转为已确认。"""

    make_category(db_session)
    sender = RecordingMailSender()

    subscription, token = subscription_service.create_subscription(
        db_session,
        email="Reader@Example.com ",
        topics=topics_for(category="AI/机器学习"),
        frequency="daily",
        max_items=5,
        sender=sender,
    )

    assert subscription.email == "reader@example.com"  # 归一化
    assert subscription.status is SubscriptionStatus.PENDING_CONFIRMATION
    assert subscription.frequency is SubscriptionFrequency.DAILY
    assert subscription.max_items == 5
    assert subscription.confirm_token_hash != token  # 只存哈希
    assert subscription.confirmed_at is None

    message = sender.last
    assert message is not None and "/subscriptions/confirm?token=" in message.text_body

    confirmed = subscription_service.confirm_subscription(db_session, token)
    assert confirmed.status is SubscriptionStatus.CONFIRMED
    assert confirmed.confirmed_at is not None


def test_confirm_is_idempotent_and_expired_token_is_rejected(db_session: Session) -> None:
    """确认凭证一次性但可重复点击；过期凭证必须被拒绝。"""

    make_category(db_session)
    subscription, token = subscription_service.create_subscription(
        db_session, email="a@example.com", topics=topics_for(category="AI/机器学习")
    )

    first = subscription_service.confirm_subscription(db_session, token)
    second = subscription_service.confirm_subscription(db_session, token)  # 重复点击无副作用
    assert first.status is second.status is SubscriptionStatus.CONFIRMED
    assert second.confirmed_at == first.confirmed_at  # 未被刷新，说明没有重复副作用

    _, expired_token = subscription_service.create_subscription(
        db_session, email="b@example.com", topics=topics_for(category="AI/机器学习")
    )
    expired_subscription = subscription_service._find_by_hash(
        db_session, Subscription.confirm_token_hash, expired_token
    )
    assert expired_subscription is not None
    expired_subscription.confirm_expires_at = utcnow() - timedelta(hours=1)
    db_session.commit()

    with pytest.raises(ApiError) as error:
        subscription_service.confirm_subscription(db_session, expired_token)
    assert error.value.status_code == 410
    assert error.value.code == "CONFIRM_TOKEN_EXPIRED"


def test_invalid_confirm_token_is_rejected(db_session: Session) -> None:
    with pytest.raises(ApiError) as error:
        subscription_service.confirm_subscription(db_session, "not-a-real-token")

    assert error.value.status_code == 404
    assert error.value.code == "CONFIRM_TOKEN_INVALID"


def test_duplicate_subscription_with_same_topics_is_rejected(db_session: Session) -> None:
    """同一邮箱 + 完全相同的方向集合且已确认 → 409，而不是静默建重复记录。"""

    make_category(db_session)
    _, token = subscription_service.create_subscription(
        db_session, email="dup@example.com", topics=topics_for(category="AI/机器学习")
    )
    subscription_service.confirm_subscription(db_session, token)

    with pytest.raises(ApiError) as error:
        subscription_service.create_subscription(
            db_session, email="dup@example.com", topics=topics_for(category="AI/机器学习")
        )
    assert error.value.status_code == 409
    assert error.value.code == "ALREADY_SUBSCRIBED"

    # 未确认的重复请求不触发 409（用户可能只是没收到邮件，需要重发）
    _, pending_again = subscription_service.create_subscription(
        db_session,
        email="pending@example.com",
        topics=topics_for(category="AI/机器学习"),
    )
    assert pending_again


def test_rate_limit_blocks_abuse(db_session: Session) -> None:
    """同一邮箱或 IP 小时内提交次数超限 → 429 且不落库。"""

    make_category(db_session)
    for index in range(3):
        subscription_service.create_subscription(
            db_session,
            email="spam@example.com",
            topics=topics_for(keyword=f"关键词{index}"),
            ip="203.0.113.7",
        )

    before = db_session.scalar(select(func.count()).select_from(Subscription))
    with pytest.raises(ApiError) as error:
        subscription_service.create_subscription(
            db_session,
            email="spam@example.com",
            topics=topics_for(keyword="又一个"),
            ip="203.0.113.7",
        )
    assert error.value.status_code == 429
    assert error.value.code == "RATE_LIMITED"
    assert db_session.scalar(select(func.count()).select_from(Subscription)) == before

    # 不同 IP 但同邮箱同样受限（邮箱维度）
    with pytest.raises(ApiError) as error:
        subscription_service.create_subscription(
            db_session,
            email="spam@example.com",
            topics=topics_for(keyword="换IP"),
            ip="198.51.100.9",
        )
    assert error.value.code == "RATE_LIMITED"


def test_topic_validation_rejects_unknown_values(db_session: Session) -> None:
    """不存在的类别/标签/来源必须被拒绝，且不落库。"""

    with pytest.raises(ApiError) as error:
        subscription_service.create_subscription(
            db_session, email="x@example.com", topics=topics_for(category="不存在的类别")
        )
    assert error.value.code == "VALIDATION_ERROR"

    with pytest.raises(ApiError):
        subscription_service.create_subscription(
            db_session, email="x@example.com", topics=topics_for(tag="不存在的标签")
        )

    with pytest.raises(ApiError):
        subscription_service.create_subscription(
            db_session, email="x@example.com", topics=topics_for(source="source_missing")
        )

    with pytest.raises(ApiError) as empty_error:
        subscription_service.create_subscription(db_session, email="x@example.com", topics=[])
    assert empty_error.value.code == "VALIDATION_ERROR"

    assert db_session.scalar(select(func.count()).select_from(Subscription)) == 0


def test_keyword_and_max_items_bounds(db_session: Session) -> None:
    with pytest.raises(ApiError):
        subscription_service.create_subscription(
            db_session, email="k@example.com", topics=topics_for(keyword="字" * 51)
        )

    make_category(db_session)
    with pytest.raises(ApiError):
        subscription_service.create_subscription(
            db_session,
            email="k@example.com",
            topics=topics_for(keyword="合法关键词"),
            max_items=999,
        )

    with pytest.raises(ApiError):
        subscription_service.create_subscription(
            db_session,
            email="k@example.com",
            topics=topics_for(keyword="合法关键词"),
            frequency="hourly",
        )


def test_source_topic_accepts_source_id_and_rejects_blacklist(db_session: Session) -> None:
    source = make_source(db_session)
    subscription, _ = subscription_service.create_subscription(
        db_session, email="s@example.com", topics=topics_for(source=source.id)
    )
    stored = subscription_service.subscription_topics(db_session, subscription)
    assert stored[0].topic_type is SubscriptionTopicType.SOURCE
    assert stored[0].topic_value == source.id

    # 黑名单来源不可订阅
    source.list_type = source.list_type.BLACKLIST
    db_session.commit()
    with pytest.raises(ApiError):
        subscription_service.create_subscription(
            db_session, email="s2@example.com", topics=topics_for(source=source.id)
        )


def test_unsubscribe_self_and_all(db_session: Session) -> None:
    """退订立即生效；scope=all 覆盖同邮箱全部订阅。"""

    make_category(db_session)
    sender = RecordingMailSender()
    first, _ = subscription_service.create_subscription(
        db_session,
        email="u@example.com",
        topics=topics_for(category="AI/机器学习"),
        sender=sender,
    )
    second, _ = subscription_service.create_subscription(
        db_session, email="u@example.com", topics=topics_for(keyword="另一个方向")
    )
    token = _unsubscribe_token(db_session, first)
    only_first = subscription_service.unsubscribe(db_session, token, scope="self")
    assert [item.id for item in only_first] == [first.id]
    assert only_first[0].status is SubscriptionStatus.UNSUBSCRIBED
    assert only_first[0].unsubscribed_at is not None
    assert db_session.get(Subscription, second.id).status is SubscriptionStatus.PENDING_CONFIRMATION

    second_token = _unsubscribe_token(db_session, second)
    both = subscription_service.unsubscribe(db_session, second_token, scope="all")
    assert {item.status for item in both} == {SubscriptionStatus.UNSUBSCRIBED}
    assert len(both) == 2

    with pytest.raises(ApiError) as error:
        subscription_service.unsubscribe(db_session, token, scope="everyone")
    assert error.value.code == "VALIDATION_ERROR"


def test_mask_email_hides_local_part(db_session: Session) -> None:
    make_category(db_session)
    subscription, _ = subscription_service.create_subscription(
        db_session, email="reader@example.com", topics=topics_for(category="AI/机器学习")
    )

    masked = subscription_service.mask_email(subscription.email)
    assert masked.endswith("@example.com")
    assert "reader" not in masked
    assert "*" in masked


# ---------------------------------------------------------------------------
# HTTP 层
# ---------------------------------------------------------------------------


@pytest.fixture()
def shared_sender() -> RecordingMailSender:
    return RecordingMailSender()


@pytest.fixture()
def subscribe_client(api_app: FastAPI, shared_sender: RecordingMailSender) -> TestClient:
    """带记录型邮件发送器的匿名客户端（测试中不真实发信）。"""

    api_app.dependency_overrides[get_mail_sender] = lambda: shared_sender
    with TestClient(api_app) as test_client:
        yield test_client
    api_app.dependency_overrides.pop(get_mail_sender, None)


def _raw_token_for(sender: RecordingMailSender, subscription: Subscription) -> str:
    """从确认邮件里取出确认凭证明文（测试辅助）。"""

    for message in sender.messages:
        if message.to == subscription.email and "confirm?token=" in message.text_body:
            return message.text_body.split("confirm?token=")[1].split("\n")[0].strip()
    raise AssertionError("未找到确认邮件")


def _unsubscribe_token(session: Session, subscription: Subscription) -> str:
    """为测试生成可用的退订凭证（真实系统里由邮件携带）。"""

    token = f"unsub-{subscription.id}"
    subscription.unsubscribe_token_hash = subscription_service.hash_token(token)
    session.commit()
    return token


def test_subscription_endpoints_lifecycle(
    subscribe_client: TestClient, api_session: Session, shared_sender: RecordingMailSender
) -> None:
    """公开接口全链路：方向清单 → 创建 → 确认 → 自助查询 → 退订 → 删除。"""

    make_category(api_session, "数据库")
    make_source(api_session, "https://db.example.com/")

    options = subscribe_client.get("/api/v1/subscription-topics").json()
    assert [item["value"] for item in options["categories"]] == ["数据库"]
    assert options["frequencies"] == ["daily", "weekly"]
    assert options["sources"][0]["site_url"] == "https://db.example.com/"

    created = subscribe_client.post(
        "/api/v1/subscriptions",
        json={
            "email": "http@example.com",
            "topics": [{"type": "category", "value": "数据库"}],
            "frequency": "weekly",
        },
    )
    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "pending_confirmation"

    subscription = api_session.get(Subscription, body["id"])
    assert subscription is not None
    confirm_token = _raw_token_for(shared_sender, subscription)

    confirmed = subscribe_client.get(
        "/api/v1/subscriptions/confirm", params={"token": confirm_token}
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"

    unsubscribe_token = _unsubscribe_token(api_session, subscription)
    me = subscribe_client.get("/api/v1/subscriptions/me", params={"token": unsubscribe_token})
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["email"] == "ht**@example.com"
    assert me_body["topics"] == [{"type": "category", "value": "数据库"}]

    unsubscribed = subscribe_client.post(
        "/api/v1/subscriptions/unsubscribe",
        json={"token": unsubscribe_token, "scope": "self"},
    )
    assert unsubscribed.status_code == 200
    assert unsubscribed.json()["status"] == "unsubscribed"
    assert unsubscribed.json()["affected"] == 1

    deleted = subscribe_client.request(
        "DELETE", "/api/v1/subscriptions/me", json={"token": unsubscribe_token}
    )
    assert deleted.status_code == 204
    assert api_session.scalar(select(func.count()).select_from(SubscriptionTopic)) == 0


def test_subscription_endpoints_reject_bad_input(
    subscribe_client: TestClient, api_session: Session
) -> None:
    """参数与凭证错误返回统一错误体。"""

    make_category(api_session, "运维")

    bad_email = subscribe_client.post(
        "/api/v1/subscriptions",
        json={"email": "not-an-email", "topics": [{"type": "category", "value": "运维"}]},
    )
    assert bad_email.status_code == 400
    assert bad_email.json()["error"]["code"] == "VALIDATION_ERROR"

    unknown_confirm = subscribe_client.get(
        "/api/v1/subscriptions/confirm", params={"token": "unknown-token-value"}
    )
    assert unknown_confirm.status_code == 404
    assert unknown_confirm.json()["error"]["code"] == "CONFIRM_TOKEN_INVALID"

    unknown_me = subscribe_client.get(
        "/api/v1/subscriptions/me", params={"token": "unknown-token-value"}
    )
    assert unknown_me.status_code == 404
    assert unknown_me.json()["error"]["code"] == "UNSUBSCRIBE_TOKEN_INVALID"

    unknown_unsubscribe = subscribe_client.post(
        "/api/v1/subscriptions/unsubscribe", json={"token": "unknown-token-value"}
    )
    assert unknown_unsubscribe.status_code == 404
    assert unknown_unsubscribe.json()["error"]["code"] == "UNSUBSCRIBE_TOKEN_INVALID"

    # 未确认的订阅不产生推送候选：状态断言（T23 的发送范围只取 confirmed）
    assert (
        api_session.scalar(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.status == SubscriptionStatus.CONFIRMED)
        )
        == 0
    )
