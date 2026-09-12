"""订阅相关请求/响应模型（T22）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.db.enums import SubscriptionTopicType


class TopicOptionRead(BaseModel):
    """可选方向取值（来源额外带名称与站点地址，便于前端展示）。"""

    value: str
    name: Optional[str] = None
    site_url: Optional[str] = None


class TopicOptionsRead(BaseModel):
    """可订阅方向清单。"""

    categories: list[TopicOptionRead]
    tags: list[TopicOptionRead]
    sources: list[TopicOptionRead]
    frequencies: list[str]


class SubscriptionTopicInput(BaseModel):
    """订阅方向输入。"""

    type: SubscriptionTopicType
    value: str


class SubscriptionCreateRequest(BaseModel):
    """创建订阅（匿名 + 双确认）。"""

    email: str = Field(min_length=3, max_length=320)
    topics: list[SubscriptionTopicInput] = Field(default_factory=list)
    frequency: Optional[str] = None
    max_items: Optional[int] = None


class SubscriptionCreatedResponse(BaseModel):
    """创建结果：此时订阅尚未生效，需用户到邮箱确认。"""

    id: str
    status: str
    confirm_expires_at: datetime
    message: str


class SubscriptionConfirmResponse(BaseModel):
    """确认结果。"""

    id: str
    status: str
    confirmed_at: Optional[datetime] = None


class UnsubscribeRequest(BaseModel):
    """退订请求：``self`` 仅本订阅，``all`` 同邮箱全部订阅。"""

    token: str = Field(min_length=8)
    scope: str = "self"


class UnsubscribeResponse(BaseModel):
    """退订结果。"""

    status: str
    unsubscribed_at: datetime
    affected: int


class SubscriptionTopicRead(BaseModel):
    """订阅方向明细。"""

    type: str
    value: str


class SubscriptionMeResponse(BaseModel):
    """自助查询结果（邮箱脱敏）。"""

    id: str
    email: str
    status: str
    frequency: str
    max_items: int
    created_at: datetime
    topics: list[SubscriptionTopicRead]
