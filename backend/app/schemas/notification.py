"""推送与通知的请求/响应模型（T24）。"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.db.enums import DigestStatus


class NotificationSettingsRead(BaseModel):
    """推送全局设置。"""

    default_frequency: str
    max_items_per_digest: int
    send_window_start_hour: int
    send_window_end_hour: int
    send_empty_digest: bool
    max_retries: int
    sends_paused: bool
    bounce_pause_threshold: float


class NotificationSettingsUpdate(BaseModel):
    """更新推送设置（只需传要改的字段）。"""

    default_frequency: Optional[str] = None
    max_items_per_digest: Optional[int] = Field(default=None, ge=1, le=50)
    send_window_start_hour: Optional[int] = Field(default=None, ge=0, le=24)
    send_window_end_hour: Optional[int] = Field(default=None, ge=0, le=24)
    send_empty_digest: Optional[bool] = None
    max_retries: Optional[int] = Field(default=None, ge=0, le=10)
    sends_paused: Optional[bool] = None
    bounce_pause_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class NotificationSettingHistoryRead(BaseModel):
    """设置变更记录。"""

    model_config = {"from_attributes": True}

    id: str
    key: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    actor: Optional[str] = None
    created_at: datetime


class AdminSubscriptionRead(BaseModel):
    """维护者视角的订阅（邮箱脱敏）。"""

    id: str
    email: str
    status: str
    frequency: str
    max_items: int
    topic_count: int
    last_sent_at: Optional[datetime] = None
    created_at: datetime


class AdminSubscriptionList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[AdminSubscriptionRead]


class DigestItemRead(BaseModel):
    """推送条目明细。"""

    article_id: str
    position: int
    matched_topics: list[str]
    title: str = ""
    url: str = ""


class DigestRead(BaseModel):
    """推送记录。"""

    model_config = {"from_attributes": True}

    id: str
    subscription_id: str
    period_start: datetime
    period_end: datetime
    status: DigestStatus
    item_count: int
    retry_count: int
    sent_at: Optional[datetime] = None
    error: Optional[str] = None
    created_at: datetime


class DigestDetailRead(DigestRead):
    """推送记录 + 条目明细。"""

    items: list[DigestItemRead] = Field(default_factory=list)


class DigestList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[DigestRead]


class DigestRunRequest(BaseModel):
    """手动触发推送：可指定单个订阅，支持"只生成不投递"预演。"""

    subscription_id: Optional[str] = None
    dry_run: bool = False


class DigestPlanItemRead(BaseModel):
    """预演结果中的一条计划。"""

    subscription_id: str
    email: str
    planned_items: int
    note: str


class DigestRunResponse(BaseModel):
    """手动触发结果。"""

    dry_run: bool
    planned: list[DigestPlanItemRead] = Field(default_factory=list)
    generated: int = 0
    sent: int = 0
    failed: int = 0
    skipped_empty: int = 0


class DeliveryChecklistItem(BaseModel):
    """合规自检项。"""

    item: str
    ok: bool
    detail: Optional[str] = None


class DeliveryHealthRead(BaseModel):
    """送达健康与合规自检。"""

    sampled: int
    sent: int
    failed: int
    skipped_empty: int
    failure_rate: float
    threshold: float
    paused: bool
    checklist: list[DeliveryChecklistItem]


class NotificationBacklogRead(BaseModel):
    """运维视图：推送积压统计。"""

    pending: int
    sent: int
    failed: int
    skipped_empty: int
    checklist: list[dict[str, Any]] = Field(default_factory=list)
