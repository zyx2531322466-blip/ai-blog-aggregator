"""知识级去重判定与复核的请求/响应模型（T26）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.db.enums import DecisionActor, KnowledgeDecisionType, KnowledgeStatus


class KnowledgePointVerdictRead(BaseModel):
    """单个知识点的判定结果。"""

    name: str
    summary: str = ""
    is_new: bool
    similarity: float = 0.0
    wiki_entry_id: Optional[str] = None
    matched_entry_id: Optional[str] = None


class KnowledgeDecisionRead(BaseModel):
    """一条知识判定记录（含依据与版本信息）。"""

    model_config = {"from_attributes": True}

    id: str
    article_id: str
    decision: KnowledgeDecisionType
    matched_entry_id: Optional[str] = None
    similarity: Optional[float] = None
    rationale: Optional[str] = None
    points: list[KnowledgePointVerdictRead] = Field(default_factory=list)
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    actor: DecisionActor
    created_at: datetime


class KnowledgeDecisionList(BaseModel):
    """判定记录分页列表。"""

    total: int
    page: int
    page_size: int
    items: list[KnowledgeDecisionRead]


class KnowledgeOverrideRequest(BaseModel):
    """人工改判：人工结论优先于系统判定。"""

    decision: KnowledgeDecisionType
    reason: str = Field(min_length=1, max_length=500)


class KnowledgeRunRequest(BaseModel):
    """手动触发一轮知识判定。"""

    article_ids: Optional[list[str]] = None
    limit: Optional[int] = Field(default=None, ge=1, le=200)


class KnowledgeRunResponse(BaseModel):
    """判定结果摘要。"""

    processed: int
    archived: int
    partial: int
    created_new: int
    pending: int


class LlmUsageSummaryRead(BaseModel):
    """LLM 用量摘要。"""

    calls_today: int
    failures_today: int
    tokens_today: int
    records_total: int


class KnowledgeStatsRead(BaseModel):
    """知识去重统计（维护者评估"是否过严/过松"）。"""

    filtered_total: int
    by_category: dict[str, int]
    pending_total: int
    partial_total: int
    llm_usage: LlmUsageSummaryRead


class ArticleKnowledgeRead(BaseModel):
    """文章详情中的知识信息。"""

    status: KnowledgeStatus
    points: list[KnowledgePointVerdictRead] = Field(default_factory=list)
    decision_reason: Optional[str] = None
