"""订阅生命周期与反滥用服务（T22）。

对应 `tickets.md` T22：
- 匿名订阅：身份仅由邮箱表示（不引入账号体系）；
- 确认与退订凭证只存哈希且**一次性**，确认链接带有效期；
- 未确认的订阅不参与任何推送；
- 反滥用：同邮箱重复提交去重、按邮箱/来源 IP 的小时级频控。

邮件正文渲染属于 T23 的摘要模板范畴，本模块只负责"确认邮件"这一事务性通知，
且通过 ``MailSender`` 抽象发送，测试中不触网、不发信。
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.base import utcnow
from app.db.enums import (
    CategoryStatus,
    SourceListType,
    SubscriptionFrequency,
    SubscriptionStatus,
    SubscriptionTopicType,
)
from app.db.models import Category, Source, Subscription, SubscriptionTopic, Tag
from app.notifications.mailer import MailMessage, MailSender

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_TOPICS = 20
MAX_KEYWORD_LENGTH = 50
MIN_MAX_ITEMS = 1
MAX_MAX_ITEMS = 50
UNSUBSCRIBE_SCOPE_SELF = "self"
UNSUBSCRIBE_SCOPE_ALL = "all"


@dataclass(frozen=True)
class TopicInput:
    """订阅方向输入（类别/标签/来源/关键词）。"""

    topic_type: SubscriptionTopicType
    topic_value: str


def hash_token(token: str) -> str:
    """凭证以 SHA-256 哈希落库（数据库泄露也无法复用凭证）。"""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mask_email(email: str) -> str:
    """邮箱脱敏，用于维护者列表与自助查询返回。"""

    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    visible = local[:2]
    return f"{visible}{'*' * max(len(local) - 2, 1)}@{domain}"


def normalize_email(email: str) -> str:
    """归一化并校验邮箱格式。"""

    normalized = (email or "").strip().lower()
    if not EMAIL_PATTERN.match(normalized):
        raise ApiError(400, "VALIDATION_ERROR", "邮箱格式不正确", {"email": email})
    return normalized


def parse_frequency(value: str | None, settings: Settings) -> SubscriptionFrequency:
    """解析推送节奏（缺省取全局默认）。"""

    raw = (value or settings.digest_default_frequency).strip().lower()
    try:
        return SubscriptionFrequency(raw)
    except ValueError:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "推送节奏只支持 daily 或 weekly",
            {"frequency": value},
        ) from None


def parse_max_items(value: int | None, settings: Settings) -> int:
    """解析单封邮件条数上限（缺省取全局默认）。"""

    resolved = settings.digest_max_items if value is None else value
    if not MIN_MAX_ITEMS <= resolved <= MAX_MAX_ITEMS:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            f"条数上限必须位于 {MIN_MAX_ITEMS} 到 {MAX_MAX_ITEMS} 之间",
            {"max_items": value},
        )
    return resolved


def build_confirm_link(settings: Settings, token: str) -> str:
    """生成确认链接（指向前端确认页）。"""

    base = settings.public_base_url.rstrip("/")
    return f"{base}/subscriptions/confirm?token={token}"


def build_unsubscribe_link(settings: Settings, token: str) -> str:
    """生成退订链接（每封邮件都必须包含）。"""

    base = settings.public_base_url.rstrip("/")
    return f"{base}/subscriptions/unsubscribe?token={token}"


def list_topic_options(session: Session) -> dict[str, list[dict[str, object]]]:
    """返回可订阅方向清单（类别/标签/来源）。"""

    categories = session.scalars(
        select(Category).where(Category.status == CategoryStatus.ACTIVE).order_by(Category.name)
    ).all()
    tags = session.scalars(select(Tag).order_by(Tag.name)).all()
    sources = session.scalars(
        select(Source)
        .where(Source.is_active.is_(True), Source.list_type != SourceListType.BLACKLIST)
        .order_by(Source.name)
    ).all()
    return {
        "categories": [{"value": category.name} for category in categories],
        "tags": [{"value": tag.name} for tag in tags],
        "sources": [
            {"value": source.id, "name": source.name, "site_url": source.site_url}
            for source in sources
        ],
    }


def _resolve_topic_value(session: Session, topic_type: SubscriptionTopicType, value: str) -> str:
    """校验方向取值合法，并返回落库使用的规范值。"""

    candidate = (value or "").strip()
    if not candidate:
        raise ApiError(
            400, "VALIDATION_ERROR", "订阅方向不能为空", {"topic_type": topic_type.value}
        )

    if topic_type is SubscriptionTopicType.CATEGORY:
        category = session.scalars(
            select(Category).where(
                Category.name == candidate, Category.status == CategoryStatus.ACTIVE
            )
        ).first()
        if category is None:
            raise ApiError(
                400, "VALIDATION_ERROR", f"类别不存在或已停用：{candidate}", {"value": value}
            )
        return category.name

    if topic_type is SubscriptionTopicType.TAG:
        tag = session.scalars(select(Tag).where(Tag.name == candidate)).first()
        if tag is None:
            raise ApiError(400, "VALIDATION_ERROR", f"标签不存在：{candidate}", {"value": value})
        return tag.name

    if topic_type is SubscriptionTopicType.SOURCE:
        source = session.get(Source, candidate)
        if source is None:
            source = session.scalars(select(Source).where(Source.site_url == candidate)).first()
        if source is None or source.list_type is SourceListType.BLACKLIST:
            raise ApiError(400, "VALIDATION_ERROR", f"来源不存在或不可订阅：{candidate}")
        return source.id

    if len(candidate) > MAX_KEYWORD_LENGTH:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            f"关键词长度不能超过 {MAX_KEYWORD_LENGTH} 个字符",
            {"value": value},
        )
    return candidate


def validate_topics(
    session: Session, topics: list[TopicInput]
) -> list[tuple[SubscriptionTopicType, str]]:
    """校验并归一化订阅方向集合（去重、限量）。"""

    if not topics:
        raise ApiError(400, "VALIDATION_ERROR", "至少需要选择一个订阅方向")
    if len(topics) > MAX_TOPICS:
        raise ApiError(400, "VALIDATION_ERROR", f"订阅方向最多 {MAX_TOPICS} 个")

    resolved: list[tuple[SubscriptionTopicType, str]] = []
    seen: set[tuple[str, str]] = set()
    for topic in topics:
        try:
            topic_type = SubscriptionTopicType(topic.topic_type)
        except ValueError:
            raise ApiError(
                400,
                "VALIDATION_ERROR",
                "方向类型只支持 category / tag / source / keyword",
                {"topic_type": str(topic.topic_type)},
            ) from None
        value = _resolve_topic_value(session, topic_type, topic.topic_value)
        key = (topic_type.value, value)
        if key not in seen:
            seen.add(key)
            resolved.append((topic_type, value))
    return resolved


def _topic_signature(topics: list[tuple[SubscriptionTopicType, str]]) -> set[tuple[str, str]]:
    return {(topic_type.value, value) for topic_type, value in topics}


def _existing_signature(session: Session, subscription: Subscription) -> set[tuple[str, str]]:
    rows = session.scalars(
        select(SubscriptionTopic).where(SubscriptionTopic.subscription_id == subscription.id)
    ).all()
    return {(row.topic_type.value, row.topic_value) for row in rows}


def _enforce_rate_limit(
    session: Session, *, email: str, ip: str | None, now: datetime, limit: int
) -> None:
    """按邮箱与来源 IP 做小时级频控（反滥用）。"""

    window_start = now - timedelta(hours=1)
    by_email = session.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.email == email, Subscription.created_at >= window_start)
    )
    if by_email and by_email >= limit:
        raise ApiError(429, "RATE_LIMITED", "该邮箱提交过于频繁，请稍后再试")
    if ip:
        by_ip = session.scalar(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.created_ip == ip, Subscription.created_at >= window_start)
        )
        if by_ip and by_ip >= limit:
            raise ApiError(429, "RATE_LIMITED", "提交过于频繁，请稍后再试")


def send_confirmation_mail(
    subscription: Subscription, token: str, *, settings: Settings, sender: MailSender
) -> None:
    """发送双确认邮件（事务性通知，不包含摘要内容）。"""

    link = build_confirm_link(settings, token)
    ttl_hours = settings.subscription_confirm_ttl_hours
    text_body = (
        "你好，\n\n"
        "我们收到了这个邮箱的订阅请求。请点击下面的链接完成确认：\n"
        f"{link}\n\n"
        f"链接 {ttl_hours} 小时内有效；如果不是你本人操作，忽略本邮件即可，我们不会向你发送任何内容。\n"
    )
    html_body = (
        "<p>你好，</p>"
        "<p>我们收到了这个邮箱的订阅请求。请点击下面的链接完成确认：</p>"
        f'<p><a href="{link}">{link}</a></p>'
        f"<p>链接 {ttl_hours} 小时内有效；如果不是你本人操作，忽略本邮件即可，我们不会向你发送任何内容。</p>"
    )
    sender.send(
        MailMessage(
            to=subscription.email,
            subject="请确认你的订阅",
            text_body=text_body,
            html_body=html_body,
        )
    )


def create_subscription(
    session: Session,
    *,
    email: str,
    topics: list[TopicInput],
    frequency: str | None = None,
    max_items: int | None = None,
    settings: Settings | None = None,
    sender: MailSender | None = None,
    ip: str | None = None,
    now: datetime | None = None,
) -> tuple[Subscription, str]:
    """创建（待确认的）订阅并发送确认邮件；返回订阅与确认凭证明文。"""

    settings = settings or get_settings()
    moment = now or utcnow()
    normalized_email = normalize_email(email)
    resolved_topics = validate_topics(session, topics)
    resolved_frequency = parse_frequency(frequency, settings)
    resolved_max_items = parse_max_items(max_items, settings)

    # 同一邮箱 + 完全相同的方向集合且已确认 → 视为重复订阅
    confirmed = session.scalars(
        select(Subscription).where(
            Subscription.email == normalized_email,
            Subscription.status == SubscriptionStatus.CONFIRMED,
        )
    ).all()
    wanted = _topic_signature(resolved_topics)
    for existing in confirmed:
        if _existing_signature(session, existing) == wanted:
            raise ApiError(409, "ALREADY_SUBSCRIBED", "该邮箱已订阅相同方向")

    _enforce_rate_limit(
        session,
        email=normalized_email,
        ip=ip,
        now=moment,
        limit=settings.subscription_rate_limit_per_hour,
    )

    confirm_token = secrets.token_urlsafe(32)
    unsubscribe_token = secrets.token_urlsafe(32)
    subscription = Subscription(
        email=normalized_email,
        status=SubscriptionStatus.PENDING_CONFIRMATION,
        frequency=resolved_frequency,
        max_items=resolved_max_items,
        confirm_token_hash=hash_token(confirm_token),
        confirm_expires_at=moment + timedelta(hours=settings.subscription_confirm_ttl_hours),
        unsubscribe_token_hash=hash_token(unsubscribe_token),
        created_ip=ip,
    )
    session.add(subscription)
    session.flush()
    for topic_type, value in resolved_topics:
        session.add(
            SubscriptionTopic(
                subscription_id=subscription.id, topic_type=topic_type, topic_value=value
            )
        )
    session.commit()
    session.refresh(subscription)

    if sender is not None:
        send_confirmation_mail(subscription, confirm_token, settings=settings, sender=sender)
    return subscription, confirm_token


def _find_by_hash(session: Session, column, token: str) -> Subscription | None:  # noqa: ANN001
    if not token:
        return None
    return session.scalars(select(Subscription).where(column == hash_token(token))).first()


def confirm_subscription(
    session: Session, token: str, *, now: datetime | None = None
) -> Subscription:
    """确认订阅（双确认）；凭证一次性、带有效期。"""

    moment = now or utcnow()
    subscription = _find_by_hash(session, Subscription.confirm_token_hash, token)
    if subscription is None:
        raise ApiError(404, "CONFIRM_TOKEN_INVALID", "确认凭证无效")
    if subscription.status is SubscriptionStatus.UNSUBSCRIBED:
        raise ApiError(410, "CONFIRM_TOKEN_EXPIRED", "该订阅已退订，请重新发起订阅")
    if subscription.status is SubscriptionStatus.PENDING_CONFIRMATION:
        expires_at = subscription.confirm_expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=moment.tzinfo)
        if expires_at is not None and expires_at < moment:
            raise ApiError(410, "CONFIRM_TOKEN_EXPIRED", "确认链接已过期，请重新发起订阅")
        subscription.status = SubscriptionStatus.CONFIRMED
        subscription.confirmed_at = moment
        session.commit()
        session.refresh(subscription)
    return subscription


def unsubscribe(
    session: Session,
    token: str,
    *,
    scope: str = UNSUBSCRIBE_SCOPE_SELF,
    now: datetime | None = None,
) -> list[Subscription]:
    """退订：``self`` 只退当前订阅，``all`` 退同一邮箱的全部订阅。立即生效。"""

    moment = now or utcnow()
    subscription = _find_by_hash(session, Subscription.unsubscribe_token_hash, token)
    if subscription is None:
        raise ApiError(404, "UNSUBSCRIBE_TOKEN_INVALID", "退订凭证无效")

    targets = [subscription]
    if scope == UNSUBSCRIBE_SCOPE_ALL:
        targets = list(
            session.scalars(
                select(Subscription).where(Subscription.email == subscription.email)
            ).all()
        )
    elif scope != UNSUBSCRIBE_SCOPE_SELF:
        raise ApiError(400, "VALIDATION_ERROR", "范围只支持 self 或 all", {"scope": scope})

    for target in targets:
        target.status = SubscriptionStatus.UNSUBSCRIBED
        target.unsubscribed_at = moment
    session.commit()
    for target in targets:
        session.refresh(target)
    return targets


def get_subscription_by_token(session: Session, token: str) -> Subscription:
    """凭退订凭证自助查询订阅（无需登录）。"""

    subscription = _find_by_hash(session, Subscription.unsubscribe_token_hash, token)
    if subscription is None:
        raise ApiError(404, "UNSUBSCRIBE_TOKEN_INVALID", "凭证无效")
    return subscription


def delete_subscription(session: Session, token: str) -> None:
    """删除订阅及其偏好数据（个人数据可删除）。"""

    subscription = get_subscription_by_token(session, token)
    session.delete(subscription)
    session.commit()


def subscription_topics(session: Session, subscription: Subscription) -> list[SubscriptionTopic]:
    """返回订阅方向明细。"""

    return list(
        session.scalars(
            select(SubscriptionTopic)
            .where(SubscriptionTopic.subscription_id == subscription.id)
            .order_by(SubscriptionTopic.topic_type, SubscriptionTopic.topic_value)
        ).all()
    )
