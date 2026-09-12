"""知识级去重与文章处置（T26）。

三层去重的最后一层：**文本级**（完全重复 / 近重复）先合并，**知识级**再判定
"这篇讲的 knowledge 是否已经被 Wiki 覆盖"。核心原则：

- **保守优先**：证据不足、模型不可用、判定结果不确定 → 一律视为"全新知识"或"待判定"，
  绝不判为"已覆盖"。知识级误筛会让用户"看不到内容"，后果比漏筛严重得多；
- **人工优先**：维护者改判（``actor=human``）覆盖系统判定，并在后续查询中生效；
- **不干扰既有去重**：本层只"归档"，不修改合并组与主记录选择逻辑；
- **可追溯**：每次判定记录命中条目、相似度、理由、模型与提示词版本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db.base import utcnow
from app.db.enums import (
    ArticleStatus,
    DecisionActor,
    ExtractionStatus,
    KnowledgeDecisionType,
    KnowledgeStatus,
    WikiEntrySourceType,
)
from app.db.models import Article, Category, KnowledgeDecision, WikiEntry
from app.knowledge.llm_client import KnowledgePoint, LlmClient
from app.knowledge.vector import VectorIndex
from app.services import knowledge_service, wiki_service

DEFAULT_HIGH_THRESHOLD = 0.92
DEFAULT_LOW_THRESHOLD = 0.80


@dataclass
class PointVerdict:
    """单个知识点的判定结果。"""

    point: KnowledgePoint
    is_new: bool
    similarity: float
    matched_entry_id: str | None = None
    wiki_entry_id: str | None = None
    rationale: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.point.name,
            "summary": self.point.summary,
            "is_new": self.is_new,
            "similarity": round(self.similarity, 4),
            "wiki_entry_id": self.wiki_entry_id,
            "matched_entry_id": self.matched_entry_id,
        }


@dataclass
class DecisionOutcome:
    """一次知识级判定的完整结果。"""

    article: Article
    decision: KnowledgeDecisionType
    similarity: float | None
    matched_entry_id: str | None
    rationale: str
    points: list[PointVerdict] = field(default_factory=list)
    archived: bool = False
    skipped: bool = False


def _thresholds(settings: Settings) -> tuple[float, float]:
    high = settings.knowledge_similarity_high or DEFAULT_HIGH_THRESHOLD
    low = settings.knowledge_similarity_low or DEFAULT_LOW_THRESHOLD
    if low > high:  # 配置异常时回退到保守默认
        low, high = DEFAULT_LOW_THRESHOLD, DEFAULT_HIGH_THRESHOLD
    return low, high


def point_text(point: KnowledgePoint) -> str:
    """知识点用于向量化与相似度比较的文本。"""

    return "\n".join([point.name, point.summary, *point.claims]).strip()


def _recall(
    session: Session, query: KnowledgePoint, *, client: LlmClient, low: float
) -> tuple[list[tuple[str, float]], list[float] | None]:
    """召回相似条目（返回 (entry_id, similarity) 列表与查询向量）。"""

    candidates = wiki_service.active_candidates(session)
    if not candidates:
        return [], None

    text = point_text(query)
    try:
        embedding = client.embed(text)
    except Exception:  # noqa: BLE001 - 向量服务不可用时退化为文本相似度
        embedding = None

    index = VectorIndex(min_similarity=low)
    found = index.search(
        embedding,
        [(item.entry_id, item.embedding, f"{item.name}\n{item.summary}") for item in candidates],
        query_text=text,
    )
    return [(item.entry_id, item.similarity) for item in found], embedding


def decide_point(
    session: Session,
    point: KnowledgePoint,
    *,
    client: LlmClient,
    settings: Settings,
) -> PointVerdict:
    """判定单个知识点：已覆盖 / 新增（保守兜底）。"""

    low, high = _thresholds(settings)
    recalled, _ = _recall(session, point, client=client, low=low)
    if not recalled:
        return PointVerdict(
            point=point, is_new=True, similarity=0.0, rationale="Wiki 中暂无相似知识点"
        )

    entry_id, similarity = recalled[0]
    if similarity >= high:
        return PointVerdict(
            point=point,
            is_new=False,
            similarity=similarity,
            matched_entry_id=entry_id,
            rationale=f"与条目相似度 {similarity:.2f} ≥ {high:.2f}，判定已被覆盖",
        )

    # 中间区间：交模型二次判定；任何不确定（含异常）都判为"新增"
    entry = session.get(WikiEntry, entry_id)
    entry_name = entry.name if entry else ""
    entry_summary = entry.summary if entry else ""
    try:
        covered = client.judge_coverage(
            point=point, entry_name=entry_name, entry_summary=entry_summary
        )
    except Exception:  # noqa: BLE001 - 二次判定失败必须回退为"新增"
        covered = False

    if covered:
        return PointVerdict(
            point=point,
            is_new=False,
            similarity=similarity,
            matched_entry_id=entry_id,
            rationale=f"相似度 {similarity:.2f} 处于中间区间，模型二次判定为已覆盖",
        )
    return PointVerdict(
        point=point,
        is_new=True,
        similarity=similarity,
        matched_entry_id=entry_id,
        rationale=f"相似度 {similarity:.2f} 未达到覆盖阈值，保守判定为新增知识",
    )


def _record_decision(
    session: Session,
    article: Article,
    *,
    decision: KnowledgeDecisionType,
    similarity: float | None,
    matched_entry_id: str | None,
    rationale: str,
    points: list[dict[str, object]],
    settings: Settings,
    actor: DecisionActor = DecisionActor.SYSTEM,
) -> KnowledgeDecision:
    row = KnowledgeDecision(
        article_id=article.id,
        decision=decision,
        similarity=similarity,
        matched_entry_id=matched_entry_id,
        rationale=rationale,
        points=points,
        model=settings.llm_model,
        prompt_version=settings.knowledge_prompt_version,
        actor=actor,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _apply_article_state(article: Article, decision: KnowledgeDecisionType) -> None:
    """按判定结果处置文章：已覆盖 → 归档；其他 → 正常展示。"""

    if decision is KnowledgeDecisionType.COVERED:
        article.status = ArticleStatus.KNOWLEDGE_DUPLICATE
        article.knowledge_status = KnowledgeStatus.COVERED
    elif decision is KnowledgeDecisionType.PARTIAL:
        article.knowledge_status = KnowledgeStatus.PARTIAL
        if article.status is ArticleStatus.KNOWLEDGE_DUPLICATE:
            article.status = ArticleStatus.NORMAL
    elif decision is KnowledgeDecisionType.NEW:
        article.knowledge_status = KnowledgeStatus.NEW
        if article.status is ArticleStatus.KNOWLEDGE_DUPLICATE:
            article.status = ArticleStatus.NORMAL
    else:  # pending
        article.knowledge_status = KnowledgeStatus.PENDING


def judge_article(
    session: Session,
    article: Article,
    *,
    client: LlmClient,
    settings: Settings | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> DecisionOutcome:
    """判定一篇文章的知识级状态，并按保守原则处置与留痕。"""

    base = settings or get_settings()
    if not base.knowledge_enabled and not force:
        return DecisionOutcome(
            article=article,
            decision=KnowledgeDecisionType.PENDING,
            similarity=None,
            matched_entry_id=None,
            rationale="知识级去重未启用（APP_KNOWLEDGE_ENABLED=false）",
            skipped=True,
        )

    extraction = knowledge_service.extract_points(session, article, client=client, settings=base)
    if extraction.status is not ExtractionStatus.OK:
        _apply_article_state(article, KnowledgeDecisionType.PENDING)
        session.commit()
        _record_decision(
            session,
            article,
            decision=KnowledgeDecisionType.PENDING,
            similarity=None,
            matched_entry_id=None,
            rationale=f"知识点提炼失败，待后续重试：{extraction.error or '未知原因'}",
            points=[],
            settings=base,
        )
        return DecisionOutcome(
            article=article,
            decision=KnowledgeDecisionType.PENDING,
            similarity=None,
            matched_entry_id=None,
            rationale="知识点提炼失败，已排队重试（不影响展示与推送过滤的保守处理）",
        )

    points = knowledge_service.points_from_row(extraction)
    if not points:
        _apply_article_state(article, KnowledgeDecisionType.NEW)
        session.commit()
        _record_decision(
            session,
            article,
            decision=KnowledgeDecisionType.NEW,
            similarity=None,
            matched_entry_id=None,
            rationale="未提炼出可复用的知识点，视为全新内容",
            points=[],
            settings=base,
        )
        return DecisionOutcome(
            article=article,
            decision=KnowledgeDecisionType.NEW,
            similarity=None,
            matched_entry_id=None,
            rationale="未提炼出可复用的知识点",
        )

    verdicts: list[PointVerdict] = []
    for point in points:
        verdict = decide_point(session, point, client=client, settings=base)
        if verdict.is_new:
            entry = wiki_service.find_active_by_name(session, point.name)
            if entry is None:
                embedding = None
                try:
                    embedding = client.embed(point_text(point))
                except Exception:  # noqa: BLE001 - 向量失败不影响条目落库
                    embedding = None
                entry = wiki_service.create_entry(
                    session,
                    name=point.name,
                    summary=point.summary,
                    embedding=embedding,
                    created_by=WikiEntrySourceType.LLM,
                    article_ids=[article.id],
                    commit=False,
                )
            else:
                wiki_service.link_articles(session, entry, [article.id])
            verdict.wiki_entry_id = entry.id
            session.commit()
        verdicts.append(verdict)

    new_verdicts = [verdict for verdict in verdicts if verdict.is_new]
    covered_verdicts = [verdict for verdict in verdicts if not verdict.is_new]
    best = max(verdicts, key=lambda verdict: verdict.similarity)
    similarity = best.similarity
    matched_entry_id = covered_verdicts[0].matched_entry_id if covered_verdicts else None

    if not new_verdicts:
        decision = KnowledgeDecisionType.COVERED
        rationale = (
            f"{len(verdicts)} 个知识点均已在 Wiki 中覆盖"
            f"（最高相似度 {similarity:.2f}），判定为知识重复"
        )
    elif covered_verdicts:
        decision = KnowledgeDecisionType.PARTIAL
        rationale = (
            f"{len(covered_verdicts)} 个知识点已覆盖、{len(new_verdicts)} 个为新增"
            f"（最高相似度 {similarity:.2f}），按部分新增处理"
        )
    else:
        decision = KnowledgeDecisionType.NEW
        rationale = f"{len(new_verdicts)} 个知识点均为新增（最高相似度 {similarity:.2f}）"

    _apply_article_state(article, decision)
    session.commit()
    _record_decision(
        session,
        article,
        decision=decision,
        similarity=similarity,
        matched_entry_id=matched_entry_id,
        rationale=rationale,
        points=[verdict.to_dict() for verdict in verdicts],
        settings=base,
    )
    return DecisionOutcome(
        article=article,
        decision=decision,
        similarity=similarity,
        matched_entry_id=matched_entry_id,
        rationale=rationale,
        points=verdicts,
        archived=decision is KnowledgeDecisionType.COVERED,
    )


def candidate_articles(session: Session, *, limit: int = 50) -> list[Article]:
    """待判定的文章：正常展示且尚未判定（或上次判定为"待判定"）。"""

    statement = (
        select(Article)
        .where(
            Article.status.notin_(
                (ArticleStatus.FILTERED, ArticleStatus.ERROR, ArticleStatus.KNOWLEDGE_DUPLICATE)
            ),
            or_(
                Article.knowledge_status.is_(None),
                Article.knowledge_status == KnowledgeStatus.PENDING,
            ),
        )
        .order_by(Article.crawled_at.desc())
        .limit(limit)
    )
    return list(session.scalars(statement).all())


def process_articles(
    session: Session,
    *,
    client: LlmClient,
    settings: Settings | None = None,
    now: datetime | None = None,
    limit: int | None = None,
    article_ids: list[str] | None = None,
) -> list[DecisionOutcome]:
    """批量判定（供流水线与维护者手动触发使用）。

    - 受 ``knowledge_enabled`` 与单轮调用上限（``llm_max_calls_per_run``）约束；
    - 单篇失败不影响其他文章。
    """

    base = settings or get_settings()
    moment = now or utcnow()
    if not base.knowledge_enabled:
        return []

    if article_ids:
        targets = [
            article for article in (session.get(Article, item) for item in article_ids) if article
        ]
    else:
        targets = candidate_articles(session, limit=limit or base.llm_max_calls_per_run)

    outcomes: list[DecisionOutcome] = []
    for article in targets[: base.llm_max_calls_per_run]:
        try:
            outcomes.append(
                judge_article(session, article, client=client, settings=base, now=moment)
            )
        except Exception:  # noqa: BLE001 - 单篇判定异常不能中断整批
            session.rollback()
            continue
    return outcomes


def override_article(
    session: Session,
    article_id: str,
    *,
    decision: KnowledgeDecisionType,
    reason: str,
    actor: str = "admin",
    settings: Settings | None = None,
) -> KnowledgeDecision:
    """人工改判：人工结论优先于系统判定，并影响后续查询展示。"""

    base = settings or get_settings()
    article = session.get(Article, article_id)
    if article is None:
        raise ApiError(404, "NOT_FOUND", "文章不存在")

    _apply_article_state(article, decision)
    session.commit()
    return _record_decision(
        session,
        article,
        decision=decision,
        similarity=None,
        matched_entry_id=None,
        rationale=f"维护者改判：{reason}",
        points=[],
        settings=base,
        actor=DecisionActor.HUMAN,
    )


def latest_decision(session: Session, article_id: str) -> KnowledgeDecision | None:
    """最近一次判定（人工改判后以最新的为准）。"""

    return session.scalars(
        select(KnowledgeDecision)
        .where(KnowledgeDecision.article_id == article_id)
        .order_by(KnowledgeDecision.created_at.desc())
    ).first()


def latest_decisions_for(session: Session, article_ids: list[str]) -> dict[str, KnowledgeDecision]:
    """批量取最近判定（避免列表接口 N+1 查询）。"""

    if not article_ids:
        return {}
    rows = session.scalars(
        select(KnowledgeDecision)
        .where(KnowledgeDecision.article_id.in_(article_ids))
        .order_by(KnowledgeDecision.created_at.asc())
    ).all()
    latest: dict[str, KnowledgeDecision] = {}
    for row in rows:
        latest[row.article_id] = row  # 后写入的覆盖先写入的（按时间升序）
    return latest


def list_decisions(
    session: Session,
    *,
    decision: str | None = None,
    article_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[KnowledgeDecision]]:
    """判定记录列表（复核用）。"""

    statement = select(KnowledgeDecision)
    if decision:
        try:
            statement = statement.where(
                KnowledgeDecision.decision == KnowledgeDecisionType(decision)
            )
        except ValueError:
            raise ApiError(
                400,
                "VALIDATION_ERROR",
                "判定只支持 new_knowledge/partial/covered/pending",
            ) from None
    if article_id:
        statement = statement.where(KnowledgeDecision.article_id == article_id)

    total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = list(
        session.scalars(
            statement.order_by(KnowledgeDecision.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return total, rows


def knowledge_stats(session: Session, *, settings: Settings | None = None) -> dict[str, object]:
    """知识去重统计：被筛文章数、按类别分布、待判定数量与模型用量。"""

    _ = settings  # 保留入参以便未来按配置筛选统计口径
    archived = list(
        session.scalars(
            select(Article).where(Article.status == ArticleStatus.KNOWLEDGE_DUPLICATE)
        ).all()
    )
    by_category: dict[str, int] = {}
    for article in archived:
        name = "未分类"
        if article.primary_category_id:
            category = session.get(Category, article.primary_category_id)
            if category is not None:
                name = category.name
        by_category[name] = by_category.get(name, 0) + 1

    pending_total = int(
        session.scalar(
            select(func.count())
            .select_from(Article)
            .where(Article.knowledge_status == KnowledgeStatus.PENDING)
        )
        or 0
    )
    partial_total = int(
        session.scalar(
            select(func.count())
            .select_from(Article)
            .where(Article.knowledge_status == KnowledgeStatus.PARTIAL)
        )
        or 0
    )
    usage = knowledge_service.usage_stats(session)

    return {
        "filtered_total": len(archived),
        "by_category": by_category,
        "pending_total": pending_total,
        "partial_total": partial_total,
        "llm_usage": usage,
    }


def knowledge_blocked_article_ids(session: Session) -> list[str]:
    """应被推送过滤掉的文章（知识已覆盖或待判定）。"""

    rows = session.scalars(
        select(Article.id).where(
            or_(
                Article.status == ArticleStatus.KNOWLEDGE_DUPLICATE,
                Article.knowledge_status.in_((KnowledgeStatus.COVERED, KnowledgeStatus.PENDING)),
            )
        )
    ).all()
    return list(rows)


def pipeline_judge(
    session: Session, articles: list[Article], *, client: LlmClient, settings: Settings
) -> int:
    """流水线钩子：对刚解析出的文章做知识级判定，返回被归档的数量。"""

    if not settings.knowledge_enabled:
        return 0
    outcomes = process_articles(
        session,
        client=client,
        settings=settings,
        article_ids=[article.id for article in articles],
    )
    return sum(1 for outcome in outcomes if outcome.archived)
