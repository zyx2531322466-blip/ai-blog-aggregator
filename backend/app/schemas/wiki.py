"""知识 Wiki 与知识点提炼的请求/响应模型（T25）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.db.enums import ExtractionStatus, WikiEntryStatus


class WikiEntryRead(BaseModel):
    """知识点条目。"""

    model_config = {"from_attributes": True}

    id: str
    name: str
    summary: str = ""
    status: WikiEntryStatus
    created_by: str
    merged_into_id: Optional[str] = None
    human_note: Optional[str] = None
    source_article_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class WikiEntryList(BaseModel):
    """条目分页列表。"""

    total: int
    page: int
    page_size: int
    items: list[WikiEntryRead]


class WikiEntryCreateRequest(BaseModel):
    """人工新增条目。"""

    name: str = Field(min_length=1, max_length=300)
    summary: str = ""
    article_ids: list[str] = Field(default_factory=list)
    note: Optional[str] = None


class WikiEntryUpdateRequest(BaseModel):
    """编辑条目（只传要改的字段）。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=300)
    summary: Optional[str] = None
    note: Optional[str] = None
    article_ids: Optional[list[str]] = None


class WikiEntryMergeRequest(BaseModel):
    """合并条目：来源条目会被标记为 merged 并指向新条目。"""

    source_entry_ids: list[str] = Field(min_length=2)
    name: str = Field(min_length=1, max_length=300)
    summary: str = ""


class KnowledgePointRead(BaseModel):
    """一个知识点。"""

    name: str
    summary: str = ""
    claims: list[str] = Field(default_factory=list)


class KnowledgeExtractionRead(BaseModel):
    """提炼记录（含状态与用量，便于排障与成本核算）。"""

    model_config = {"from_attributes": True}

    id: str
    article_id: str
    status: ExtractionStatus
    points: list[KnowledgePointRead] = Field(default_factory=list)
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    attempts: int
    prompt_tokens: int
    completion_tokens: int
    error: Optional[str] = None


class LlmUsageRead(BaseModel):
    """LLM 用量与失败率。"""

    calls_today: int
    failures_today: int
    tokens_today: int
    records_total: int
