"""维护者：知识 Wiki 与知识点提炼接口（T25，需 T03 访问控制）。

对应 `plan.md` API 契约第 10 节：
- ``GET   /admin/wiki/entries``            条目列表（可按状态与关键字筛选）
- ``POST  /admin/wiki/entries``            新增条目
- ``PATCH /admin/wiki/entries/{id}``       编辑条目
- ``POST  /admin/wiki/entries/{id}/retire`` 废止条目（不再作为覆盖依据）
- ``POST  /admin/wiki/entries/merge``      合并条目
- ``POST  /admin/knowledge/extract/{article_id}`` 对单篇文章执行知识点提炼（幂等、带缓存）
- ``GET   /admin/knowledge/usage``         LLM 当日调用量与 token 消耗
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.security import AdminPrincipal, require_admin
from app.db.models import Article
from app.db.session import get_db
from app.knowledge.llm_client import LlmClient, build_llm_client
from app.schemas.wiki import (
    KnowledgeExtractionRead,
    LlmUsageRead,
    WikiEntryCreateRequest,
    WikiEntryList,
    WikiEntryMergeRequest,
    WikiEntryRead,
    WikiEntryUpdateRequest,
)
from app.services import knowledge_service, wiki_service

router = APIRouter(prefix="/admin", tags=["admin: knowledge wiki"])


def get_llm_client(settings: Settings = Depends(get_settings)) -> LlmClient:
    """LLM 客户端依赖：测试覆盖为替身，绝不访问真实 API。"""

    return build_llm_client(settings)


def _entry_view(session: Session, entry) -> WikiEntryRead:  # noqa: ANN001
    view = WikiEntryRead.model_validate(entry)
    view.source_article_ids = wiki_service.entry_article_ids(session, entry.id)
    return view


@router.get("/wiki/entries", response_model=WikiEntryList)
def list_entries(
    status: str | None = Query(default=None),
    query: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> WikiEntryList:
    """知识点条目列表（默认按创建时间倒序）。"""

    total, rows = wiki_service.list_entries(
        session, status=status, query=query, page=page, page_size=page_size
    )
    return WikiEntryList(
        total=total,
        page=page,
        page_size=page_size,
        items=[_entry_view(session, entry) for entry in rows],
    )


@router.post("/wiki/entries", response_model=WikiEntryRead, status_code=201)
def create_entry(
    payload: WikiEntryCreateRequest,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> WikiEntryRead:
    """人工新增知识点条目。"""

    entry = wiki_service.create_entry(
        session,
        name=payload.name,
        summary=payload.summary,
        article_ids=payload.article_ids,
        human_note=payload.note,
    )
    return _entry_view(session, entry)


@router.patch("/wiki/entries/{entry_id}", response_model=WikiEntryRead)
def update_entry(
    entry_id: str,
    payload: WikiEntryUpdateRequest,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> WikiEntryRead:
    """编辑条目（名称/摘要/备注/支撑文章）。"""

    entry = wiki_service.update_entry(
        session,
        entry_id,
        name=payload.name,
        summary=payload.summary,
        human_note=payload.note,
        article_ids=payload.article_ids,
    )
    return _entry_view(session, entry)


@router.post("/wiki/entries/{entry_id}/retire", response_model=WikiEntryRead)
def retire_entry(
    entry_id: str,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> WikiEntryRead:
    """废止条目：后续判定不再把它当作"已覆盖"的依据。"""

    entry = wiki_service.retire_entry(session, entry_id)
    return _entry_view(session, entry)


@router.post("/wiki/entries/merge", response_model=WikiEntryRead)
def merge_entries(
    payload: WikiEntryMergeRequest,
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> WikiEntryRead:
    """合并条目：来源条目标记为 merged 并指向新条目。"""

    entry = wiki_service.merge_entries(
        session,
        source_entry_ids=payload.source_entry_ids,
        target_name=payload.name,
        target_summary=payload.summary,
    )
    return _entry_view(session, entry)


@router.post("/knowledge/extract/{article_id}", response_model=KnowledgeExtractionRead)
def extract_article(
    article_id: str,
    force: bool = Query(default=False, description="忽略缓存强制重新提炼"),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    client: LlmClient = Depends(get_llm_client),
    principal: AdminPrincipal = Depends(require_admin),
) -> KnowledgeExtractionRead:
    """对单篇文章执行知识点提炼（同一内容默认命中缓存，不重复调用模型）。"""

    article = session.get(Article, article_id)
    if article is None:
        raise ApiError(404, "NOT_FOUND", "文章不存在")
    row = knowledge_service.extract_points(
        session, article, client=client, settings=settings, force=force
    )
    return KnowledgeExtractionRead.model_validate(row)


@router.get("/knowledge/usage", response_model=LlmUsageRead)
def read_usage(
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> LlmUsageRead:
    """LLM 当日调用量、失败数与 token 消耗。"""

    return LlmUsageRead(**knowledge_service.usage_stats(session))
