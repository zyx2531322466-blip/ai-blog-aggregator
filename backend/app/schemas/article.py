"""文章浏览接口的请求/响应模型（T10）。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import ArticleStatus, KnowledgeStatus


class CategoryRef(BaseModel):
    """类别引用。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str


class SourceSummary(BaseModel):
    """列表页使用的来源摘要。"""

    name: str
    url: str


class ArticleListItem(BaseModel):
    """列表项，字段满足列表展示需要。"""

    id: str
    title: str
    summary: Optional[str] = None
    # 与 plan.md 契约保持一致：category 为字符串列表（主类别 + 标签之外的主题）
    category: list[str]
    primary_category: Optional[CategoryRef] = None
    tags: list[str]
    published_at: Optional[datetime] = None
    crawled_at: datetime
    primary_source: Optional[SourceSummary] = None
    sources_count: int
    merged_sources_count: int
    status: ArticleStatus
    # T26：知识级状态与知识点（已覆盖的文章不会出现在公开列表中）
    knowledge_status: Optional[KnowledgeStatus] = None
    knowledge_points: list[str] = []


class ArticleListResponse(BaseModel):
    """分页列表响应。"""

    total: int
    page: int
    page_size: int
    items: list[ArticleListItem]


class SourceDetail(BaseModel):
    """详情页来源条目（用于展示合并组的全部来源）。"""

    name: Optional[str] = None
    url: str
    crawled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    is_primary: bool = False


class RelatedArticleRef(BaseModel):
    """关联推荐文章引用（T14，不合并）。"""

    id: str
    title: str
    url: str


class ArticleDetail(BaseModel):
    """文章详情，含合并组的全部来源。"""

    id: str
    title: str
    content: str
    summary: Optional[str] = None
    category: list[str]
    primary_category: Optional[CategoryRef] = None
    tags: list[str]
    published_at: Optional[datetime] = None
    crawled_at: datetime
    sources: list[SourceDetail]
    status: ArticleStatus
    related_articles: list[RelatedArticleRef] = Field(default_factory=list)
    # T26：知识判定明细（状态、知识点、判定理由）
    knowledge: Optional["ArticleKnowledgeRead"] = None


class ArticleReclassifyRequest(BaseModel):
    """维护者重新归类请求（T12）。"""

    category_id: str = Field(min_length=1)


from app.schemas.knowledge import ArticleKnowledgeRead  # noqa: E402  （T26 知识字段）

ArticleDetail.model_rebuild()
