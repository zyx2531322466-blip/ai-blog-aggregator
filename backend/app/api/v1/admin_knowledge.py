"""维护者：知识判定复核与改判接口（T26，需 T03 访问控制）。

对应 `plan.md` API 契约第 11 节：
- ``GET  /admin/knowledge-decisions``            判定记录（可按结论筛选）
- ``POST /admin/articles/{id}/knowledge-override`` 人工改判（人工结论优先）
- ``GET  /admin/knowledge-stats``                误筛统计与模型用量
- ``POST /admin/knowledge/run``                  手动触发一轮判定（含待判定重试）
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import AdminPrincipal, require_admin
from app.db.session import get_db
from app.knowledge.llm_client import LlmClient
from app.schemas.knowledge import (
    KnowledgeDecisionList,
    KnowledgeDecisionRead,
    KnowledgeOverrideRequest,
    KnowledgeRunRequest,
    KnowledgeRunResponse,
    KnowledgeStatsRead,
    LlmUsageSummaryRead,
)
from app.api.v1.admin_wiki import get_llm_client
from app.services import knowledge_dedup_service, knowledge_service

router = APIRouter(prefix="/admin", tags=["admin: knowledge dedup"])


@router.get("/knowledge-decisions", response_model=KnowledgeDecisionList)
def list_decisions(
    decision: str | None = Query(default=None, description="new_knowledge/partial/covered/pending"),
    article_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> KnowledgeDecisionList:
    """判定记录列表：包含结论、依据、相似度、模型与提示词版本。"""

    total, rows = knowledge_dedup_service.list_decisions(
        session, decision=decision, article_id=article_id, page=page, page_size=page_size
    )
    return KnowledgeDecisionList(
        total=total,
        page=page,
        page_size=page_size,
        items=[KnowledgeDecisionRead.model_validate(row) for row in rows],
    )


@router.post("/articles/{article_id}/knowledge-override", response_model=KnowledgeDecisionRead)
def override(
    article_id: str,
    payload: KnowledgeOverrideRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: AdminPrincipal = Depends(require_admin),
) -> KnowledgeDecisionRead:
    """人工改判：把文章标记为"确认为知识重复"或"不是知识重复"，人工结论优先。"""

    row = knowledge_dedup_service.override_article(
        session,
        article_id,
        decision=payload.decision,
        reason=payload.reason,
        actor=principal.actor,
        settings=settings,
    )
    return KnowledgeDecisionRead.model_validate(row)


@router.get("/knowledge-stats", response_model=KnowledgeStatsRead)
def read_stats(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    principal: AdminPrincipal = Depends(require_admin),
) -> KnowledgeStatsRead:
    """被筛文章数量与分布、待判定数量、模型用量（用于判断是否过严/过松）。"""

    stats = knowledge_dedup_service.knowledge_stats(session, settings=settings)
    return KnowledgeStatsRead(
        filtered_total=stats["filtered_total"],
        by_category=stats["by_category"],
        pending_total=stats["pending_total"],
        partial_total=stats["partial_total"],
        llm_usage=LlmUsageSummaryRead(**stats["llm_usage"]),
    )


@router.post("/knowledge/run", response_model=KnowledgeRunResponse)
def run_judgements(
    payload: KnowledgeRunRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    client: LlmClient = Depends(get_llm_client),
    principal: AdminPrincipal = Depends(require_admin),
) -> KnowledgeRunResponse:
    """手动触发一轮知识判定（默认处理"待判定 + 尚未判定"的文章）。"""

    outcomes = knowledge_dedup_service.process_articles(
        session,
        client=client,
        settings=settings,
        limit=payload.limit,
        article_ids=payload.article_ids,
    )
    return KnowledgeRunResponse(
        processed=len(outcomes),
        archived=sum(1 for item in outcomes if item.archived),
        partial=sum(1 for item in outcomes if item.decision.value == "partial"),
        created_new=sum(1 for item in outcomes if item.decision.value == "new_knowledge"),
        pending=sum(1 for item in outcomes if item.decision.value == "pending"),
    )


@router.get("/knowledge/usage", response_model=LlmUsageSummaryRead)
def read_usage(
    session: Session = Depends(get_db),
    principal: AdminPrincipal = Depends(require_admin),
) -> LlmUsageSummaryRead:
    """LLM 用量（当日调用量、失败数、token 消耗）。"""

    return LlmUsageSummaryRead(**knowledge_service.usage_stats(session))
