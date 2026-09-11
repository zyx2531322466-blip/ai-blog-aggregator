"""ORM 模型定义（T02 核心数据模型）。

表结构对应 `tickets.md` T02：
- ``articles``：文章（标题、正文、来源、发布时间、采集时间、主类别、状态）
- ``categories`` / ``category_history``：受控类别及其创建/重命名/合并历史
- ``tags`` / ``article_tags``：标签与文章多对多
- ``sources``：站点地址、关注领域定义、黑白名单、权重、更新频率
- ``duplicate_relations``：完全重复/近重复的合并关系，以及不同视角的关联推荐

本模块只描述数据结构，不包含任何业务逻辑。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, generate_id, utcnow
from app.db.enums import (
    ArticleStatus,
    CategoryAction,
    CategoryStatus,
    CrawlStatus,
    DedupRelationType,
    SourceListType,
    UpdateFrequency,
)


def _enum(enum_cls: type, length: int = 32) -> SAEnum:
    """构造以英文枚举值（而非成员名）落库的可移植枚举列类型。"""

    return SAEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda cls: [member.value for member in cls],
    )


class TimestampMixin:
    """统一的创建/更新时间戳。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


article_tags = Table(
    "article_tags",
    Base.metadata,
    Column(
        "article_id", String(64), ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("tag_id", String(64), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Source(TimestampMixin, Base):
    """内容来源（站点）配置，同时承载维护者定义的关注领域。"""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("source")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    site_url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 关注领域定义（T04）
    focus_area_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    focus_area_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    exclude_keywords: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    example_urls: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    counter_example_urls: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # 采集范围控制（T04 / T05）
    list_type: Mapped[SourceListType] = mapped_column(
        _enum(SourceListType), default=SourceListType.WHITELIST, nullable=False
    )
    # 来源权重：默认与其他来源相等（T04），供 T18 主记录选择消费
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    # 更新频率（T17）
    update_frequency: Mapped[UpdateFrequency] = mapped_column(
        _enum(UpdateFrequency), default=UpdateFrequency.NORMAL, nullable=False
    )
    update_interval_seconds: Mapped[Optional[int]] = mapped_column(nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_crawled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    articles: Mapped[list[Article]] = relationship(back_populates="source")

    __table_args__ = (Index("ix_sources_list_type", "list_type"),)


class Category(TimestampMixin, Base):
    """受控类别（T07）。分类体系由维护者管理，不写死在代码里。"""

    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("category")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    status: Mapped[CategoryStatus] = mapped_column(
        _enum(CategoryStatus), default=CategoryStatus.ACTIVE, nullable=False
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    history: Mapped[list[CategoryHistory]] = relationship(
        back_populates="category", foreign_keys="CategoryHistory.category_id"
    )


class CategoryHistory(Base):
    """类别的创建/重命名/合并/停用历史（T07）。"""

    __tablename__ = "category_history"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("category_history")
    )
    category_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[CategoryAction] = mapped_column(_enum(CategoryAction), nullable=False)
    old_name: Mapped[Optional[str]] = mapped_column(String(200))
    new_name: Mapped[Optional[str]] = mapped_column(String(200))
    target_category_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True
    )
    actor: Mapped[Optional[str]] = mapped_column(String(200))
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    category: Mapped[Optional[Category]] = relationship(
        back_populates="history", foreign_keys=[category_id]
    )


class Tag(Base):
    """标签（T08）：一篇文章一个主类别 + 多个标签。"""

    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("tag")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    articles: Mapped[list[Article]] = relationship(secondary=article_tags, back_populates="tags")


class Article(TimestampMixin, Base):
    """文章记录。"""

    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("article")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1000), nullable=False, unique=True)
    author: Mapped[Optional[str]] = mapped_column(String(200))

    source_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    primary_category_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )

    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    status: Mapped[ArticleStatus] = mapped_column(
        _enum(ArticleStatus), default=ArticleStatus.PENDING, nullable=False, index=True
    )

    # 去重指纹（T09 精确 / T13 近似）
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    simhash: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)

    # 主记录有效性（T18）
    is_accessible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    accessibility_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    source: Mapped[Optional[Source]] = relationship(back_populates="articles")
    primary_category: Mapped[Optional[Category]] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary=article_tags, back_populates="articles")

    __table_args__ = (
        Index("ix_articles_status_published", "status", "published_at"),
        Index("ix_articles_source_published", "source_id", "published_at"),
    )


class DuplicateRelation(Base):
    """去重关系（T09 完全重复 / T13 近重复 / T14 关联推荐）。

    语义：
    - ``exact_duplicate`` / ``near_duplicate``：``target_article_id`` 指向合并组的
      主记录，``is_primary`` 标记该行对应的文章是否为主记录；同一 ``group_key``
      下的文章构成一个合并组。
    - ``related``：两篇"同一事件不同视角"的文章，不合并，仅通过本表建立关联推荐。
    """

    __tablename__ = "duplicate_relations"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("dedup")
    )
    group_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    relation_type: Mapped[DedupRelationType] = mapped_column(
        _enum(DedupRelationType), nullable=False, index=True
    )
    article_id: Mapped[str] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_article_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("articles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    similarity: Mapped[Optional[float]] = mapped_column(Float)
    evidence: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    article: Mapped[Article] = relationship(foreign_keys=[article_id])
    target_article: Mapped[Optional[Article]] = relationship(foreign_keys=[target_article_id])

    __table_args__ = (
        UniqueConstraint(
            "article_id", "target_article_id", "relation_type", name="uq_duplicate_relation"
        ),
    )


class CrawlPage(Base):
    """抓取到的原始页面（T05），作为解析（T06）前的"待处理"数据。

    保存原始 HTML 与抓取元信息（原始来源地址、HTTP 状态、抓取时间、失败原因），
    使抓取与解析解耦：抓取失败也不会影响后续流程。
    """

    __tablename__ = "crawl_pages"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("crawl")
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    raw_html: Mapped[Optional[str]] = mapped_column(Text)
    http_status: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[CrawlStatus] = mapped_column(_enum(CrawlStatus), nullable=False, index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    source: Mapped[Source] = relationship()

    __table_args__ = (
        UniqueConstraint("source_id", "url", name="uq_crawl_page_source_url"),
        Index("ix_crawl_pages_status_fetched", "status", "fetched_at"),
    )


class DedupSetting(Base):
    """去重策略配置（T13 阈值，T15 在此基础上做审计与回滚）。

    以键值形式存储，便于维护者运行时调整，而不必写死在代码或环境变量里。
    """

    __tablename__ = "dedup_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class DedupSettingHistory(Base):
    """去重策略变更记录（T15）：谁在何时把某个配置从多少改为多少。"""

    __tablename__ = "dedup_setting_history"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("dedup_history")
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    old_value: Mapped[Optional[str]] = mapped_column(String(255))
    new_value: Mapped[Optional[str]] = mapped_column(String(255))
    actor: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
