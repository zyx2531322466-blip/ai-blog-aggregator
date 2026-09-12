"""公开订阅接口（T22，无需鉴权）。

对应 `plan.md` API 契约第 6–8 节：
- ``GET  /subscription-topics``        可选方向清单
- ``POST /subscriptions``              创建订阅（返回"待确认"）
- ``GET  /subscriptions/confirm``      邮箱双确认
- ``POST /subscriptions/unsubscribe``  一键退订（self / all）
- ``GET  /subscriptions/me``           自助查询（脱敏）
- ``DELETE /subscriptions/me``         删除订阅数据

订阅是匿名的：身份仅由邮箱与凭证表示，不引入账号体系。
"""

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.session import get_db
from app.notifications.mailer import MailSender, build_mail_sender
from app.schemas.subscription import (
    SubscriptionConfirmResponse,
    SubscriptionCreatedResponse,
    SubscriptionCreateRequest,
    SubscriptionMeResponse,
    SubscriptionTopicRead,
    TopicOptionRead,
    TopicOptionsRead,
    UnsubscribeRequest,
    UnsubscribeResponse,
)
from app.services import subscription_service
from app.services.subscription_service import TopicInput

router = APIRouter(tags=["subscriptions"])

FREQUENCIES = ["daily", "weekly"]


def get_mail_sender(settings: Settings = Depends(get_settings)) -> MailSender:
    """邮件发送器依赖：测试可覆盖为记录型实现，确保不发真实邮件。"""

    return build_mail_sender(settings)


def get_client_ip(
    request: Request, x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For")
) -> str | None:
    """获取调用方 IP（优先取代理链首个地址），仅用于反滥用频控与审计。"""

    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


@router.get("/subscription-topics", response_model=TopicOptionsRead)
def list_topic_options(session: Session = Depends(get_db)) -> TopicOptionsRead:
    """返回可订阅的方向清单（类别/标签/来源）与可用节奏。"""

    options = subscription_service.list_topic_options(session)
    return TopicOptionsRead(
        categories=[TopicOptionRead(**item) for item in options["categories"]],
        tags=[TopicOptionRead(**item) for item in options["tags"]],
        sources=[TopicOptionRead(**item) for item in options["sources"]],
        frequencies=FREQUENCIES,
    )


@router.post("/subscriptions", response_model=SubscriptionCreatedResponse, status_code=202)
def create_subscription(
    payload: SubscriptionCreateRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    sender: MailSender = Depends(get_mail_sender),
    ip: str | None = Depends(get_client_ip),
) -> SubscriptionCreatedResponse:
    """创建订阅并发送确认邮件；确认前不会产生任何推送。"""

    subscription, _ = subscription_service.create_subscription(
        session,
        email=payload.email,
        topics=[
            TopicInput(topic_type=topic.type, topic_value=topic.value) for topic in payload.topics
        ],
        frequency=payload.frequency,
        max_items=payload.max_items,
        settings=settings,
        sender=sender,
        ip=ip,
    )
    return SubscriptionCreatedResponse(
        id=subscription.id,
        status=subscription.status.value,
        confirm_expires_at=subscription.confirm_expires_at,
        message="确认邮件已发送，请在有效期内点击邮件中的确认链接",
    )


@router.get("/subscriptions/confirm", response_model=SubscriptionConfirmResponse)
def confirm_subscription(
    token: str = Query(min_length=8),
    session: Session = Depends(get_db),
) -> SubscriptionConfirmResponse:
    """确认订阅（凭证一次性；重复点击不会产生副作用）。"""

    subscription = subscription_service.confirm_subscription(session, token)
    return SubscriptionConfirmResponse(
        id=subscription.id,
        status=subscription.status.value,
        confirmed_at=subscription.confirmed_at,
    )


@router.post("/subscriptions/unsubscribe", response_model=UnsubscribeResponse)
def unsubscribe(
    payload: UnsubscribeRequest,
    session: Session = Depends(get_db),
) -> UnsubscribeResponse:
    """一键退订，立即生效且无需登录。"""

    targets = subscription_service.unsubscribe(session, payload.token, scope=payload.scope)
    unsubscribe_time = targets[0].unsubscribed_at
    if unsubscribe_time is None:  # pragma: no cover - 服务层保证已写入
        raise ApiError(500, "UNSUBSCRIBE_FAILED", "退订未生效，请稍后重试")
    return UnsubscribeResponse(
        status=targets[0].status.value,
        unsubscribed_at=unsubscribe_time,
        affected=len(targets),
    )


@router.get("/subscriptions/me", response_model=SubscriptionMeResponse)
def read_my_subscription(
    token: str = Query(min_length=8),
    session: Session = Depends(get_db),
) -> SubscriptionMeResponse:
    """凭凭证自助查询订阅（邮箱脱敏返回）。"""

    subscription = subscription_service.get_subscription_by_token(session, token)
    topics = subscription_service.subscription_topics(session, subscription)
    return SubscriptionMeResponse(
        id=subscription.id,
        email=subscription_service.mask_email(subscription.email),
        status=subscription.status.value,
        frequency=subscription.frequency.value,
        max_items=subscription.max_items,
        created_at=subscription.created_at,
        topics=[
            SubscriptionTopicRead(type=topic.topic_type.value, value=topic.topic_value)
            for topic in topics
        ],
    )


@router.delete("/subscriptions/me", status_code=204)
def delete_my_subscription(
    payload: UnsubscribeRequest,
    session: Session = Depends(get_db),
) -> Response:
    """删除订阅及其偏好数据（个人数据可删除）。"""

    subscription_service.delete_subscription(session, payload.token)
    return Response(status_code=204)
