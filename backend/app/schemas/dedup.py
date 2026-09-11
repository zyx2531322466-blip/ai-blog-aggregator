"""去重策略配置与审计的请求/响应模型（T13 / T15）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DedupSettingsRead(BaseModel):
    """去重策略配置读取结果。"""

    near_duplicate_threshold: float


class DedupSettingsUpdate(BaseModel):
    """去重策略配置更新。"""

    near_duplicate_threshold: float = Field(ge=0.0, le=1.0)


class DedupSettingHistoryRead(BaseModel):
    """阈值变更记录（谁在何时把值从多少改为多少）。"""

    model_config = {"from_attributes": True}

    id: str
    key: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    actor: Optional[str] = None
    created_at: datetime


class DedupRollbackRequest(BaseModel):
    """回滚到某次变更之前的配置。"""

    history_id: str = Field(min_length=1)


class DedupPreviewRequest(BaseModel):
    """阈值变更预览请求。"""

    near_duplicate_threshold: float = Field(ge=0.0, le=1.0)


class DedupPreviewChangeRead(BaseModel):
    """单对文章的判定差异。"""

    article_id: str
    other_article_id: str
    similarity: float
    current: str
    proposed: str


class DedupPreviewRead(BaseModel):
    """阈值变更预览结果。"""

    current_threshold: float
    proposed_threshold: float
    would_merge: list[DedupPreviewChangeRead]
    would_unmerge: list[DedupPreviewChangeRead]
    would_relate: list[DedupPreviewChangeRead]
    would_unrelate: list[DedupPreviewChangeRead]
    unchanged_count: int


class DedupArticleRef(BaseModel):
    """去重命中记录中涉及的文章/来源。"""

    id: str
    title: str
    url: str
    source_name: Optional[str] = None


class DedupHitRead(BaseModel):
    """去重命中记录：判定类型、依据与涉及来源。"""

    id: str
    group_key: Optional[str] = None
    relation_type: str
    similarity: Optional[float] = None
    evidence: Optional[str] = None
    created_at: datetime
    primary: Optional[DedupArticleRef] = None
    duplicate: Optional[DedupArticleRef] = None


class DedupHitList(BaseModel):
    """去重命中记录列表。"""

    total: int
    items: list[DedupHitRead]


class DedupGroupMemberRead(BaseModel):
    """合并组成员（T18），展示权重/时间/完整度/可访问性等信息。"""

    id: str
    title: str
    url: str
    source_name: Optional[str] = None
    weight: float
    published_at: Optional[datetime] = None
    content_length: int
    is_accessible: bool
    is_primary: bool


class DedupGroupRead(BaseModel):
    """合并组：主记录与全部成员。"""

    group_key: str
    primary_id: Optional[str] = None
    members: list[DedupGroupMemberRead]


class DedupGroupList(BaseModel):
    """合并组列表。"""

    total: int
    items: list[DedupGroupRead]


class PrimaryRefreshResultRead(BaseModel):
    """主记录刷新结果。"""

    group_key: str
    previous_primary_id: Optional[str] = None
    primary_id: str
    changed: bool


class PrimaryRefreshResponse(BaseModel):
    """主记录刷新汇总。"""

    refreshed: int
    changed: int
    results: list[PrimaryRefreshResultRead]


class ArticleInaccessibleResponse(BaseModel):
    """标记原文不可访问后的主记录切换结果。"""

    article_id: str
    is_accessible: bool
    group_refreshed: bool
    primary_id: Optional[str] = None
    changed: bool = False
