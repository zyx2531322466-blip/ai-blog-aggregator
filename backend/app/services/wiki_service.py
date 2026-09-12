"""知识 Wiki 条目维护（T25）。

职责：
- 条目的增删改查（新增 / 编辑 / 废止 / 合并）与支撑文章关联；
- 只有 ``active`` 条目参与覆盖判定：废止与已合并的条目不再作为依据（人工意志优先）；
- 提供"活跃条目 + 向量 + 文本"的候选集合，供 ``knowledge_service`` 做相似度召回。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.enums import WikiEntrySourceType, WikiEntryStatus
from app.db.models import WikiEntry, WikiEntryLink


@dataclass
class WikiCandidate:
    """相似度召回用的条目快照。"""

    entry_id: str
    name: str
    summary: str
    embedding: list[float] | None


def list_entries(
    session: Session,
    *,
    status: str | None = None,
    query: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[WikiEntry]]:
    """分页查询条目（可按状态与关键字筛选）。"""

    statement = select(WikiEntry)
    if status:
        try:
            statement = statement.where(WikiEntry.status == WikiEntryStatus(status))
        except ValueError:
            raise ApiError(400, "VALIDATION_ERROR", "状态只支持 active/retired/merged") from None
    if query:
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(WikiEntry.name.ilike(pattern), WikiEntry.summary.ilike(pattern))
        )

    total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = list(
        session.scalars(
            statement.order_by(WikiEntry.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return total, rows


def get_entry(session: Session, entry_id: str) -> WikiEntry:
    """按 id 取条目，不存在抛 404。"""

    entry = session.get(WikiEntry, entry_id)
    if entry is None:
        raise ApiError(404, "NOT_FOUND", "知识点条目不存在")
    return entry


def entry_article_ids(session: Session, entry_id: str) -> list[str]:
    """条目的支撑文章 id 列表。"""

    rows = session.scalars(
        select(WikiEntryLink.article_id).where(WikiEntryLink.entry_id == entry_id)
    ).all()
    return list(rows)


def link_articles(session: Session, entry: WikiEntry, article_ids: list[str]) -> None:
    """补充条目的支撑文章（幂等）。"""

    existing = set(entry_article_ids(session, entry.id))
    for article_id in article_ids:
        if article_id in existing:
            continue
        session.add(WikiEntryLink(entry_id=entry.id, article_id=article_id))
        existing.add(article_id)


def create_entry(
    session: Session,
    *,
    name: str,
    summary: str = "",
    embedding: list[float] | None = None,
    created_by: WikiEntrySourceType = WikiEntrySourceType.HUMAN,
    article_ids: list[str] | None = None,
    human_note: str | None = None,
    commit: bool = True,
) -> WikiEntry:
    """人工或系统新增条目。"""

    cleaned = (name or "").strip()
    if not cleaned:
        raise ApiError(400, "VALIDATION_ERROR", "知识点名称不能为空")
    entry = WikiEntry(
        name=cleaned[:300],
        summary=summary or "",
        embedding=embedding,
        created_by=created_by,
        human_note=human_note,
        status=WikiEntryStatus.ACTIVE,
    )
    session.add(entry)
    session.flush()
    if article_ids:
        link_articles(session, entry, article_ids)
    if commit:
        session.commit()
        session.refresh(entry)
    return entry


def update_entry(
    session: Session,
    entry_id: str,
    *,
    name: str | None = None,
    summary: str | None = None,
    human_note: str | None = None,
    article_ids: list[str] | None = None,
    embedding: list[float] | None = None,
) -> WikiEntry:
    """编辑条目（名称/摘要/备注/支撑文章/向量）。"""

    entry = get_entry(session, entry_id)
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise ApiError(400, "VALIDATION_ERROR", "知识点名称不能为空")
        entry.name = cleaned[:300]
    if summary is not None:
        entry.summary = summary
    if human_note is not None:
        entry.human_note = human_note
    if embedding is not None:
        entry.embedding = embedding
    if article_ids is not None:
        link_articles(session, entry, article_ids)
    session.commit()
    session.refresh(entry)
    return entry


def retire_entry(session: Session, entry_id: str) -> WikiEntry:
    """废止条目：不再作为覆盖依据（人工修正优先于系统判定）。"""

    entry = get_entry(session, entry_id)
    entry.status = WikiEntryStatus.RETIRED
    session.commit()
    session.refresh(entry)
    return entry


def merge_entries(
    session: Session,
    *,
    source_entry_ids: list[str],
    target_name: str,
    target_summary: str = "",
    embedding: list[float] | None = None,
) -> WikiEntry:
    """合并多个条目为一个新条目：被合并条目标记为 merged 并指向新条目。"""

    if len(source_entry_ids) < 2:
        raise ApiError(400, "VALIDATION_ERROR", "合并至少需要两个条目")
    sources = [get_entry(session, entry_id) for entry_id in source_entry_ids]
    for source in sources:
        if source.status is not WikiEntryStatus.ACTIVE:
            raise ApiError(409, "WIKI_ENTRY_CONFLICT", f"条目 {source.id} 不是活跃状态，无法合并")

    merged_article_ids: list[str] = []
    for source in sources:
        merged_article_ids.extend(entry_article_ids(session, source.id))

    target = create_entry(
        session,
        name=target_name,
        summary=target_summary or "；".join(source.summary for source in sources if source.summary),
        embedding=embedding,
        created_by=WikiEntrySourceType.HUMAN,
        article_ids=sorted(set(merged_article_ids)),
        commit=False,
    )
    for source in sources:
        source.status = WikiEntryStatus.MERGED
        source.merged_into_id = target.id
    session.commit()
    session.refresh(target)
    return target


def active_candidates(session: Session) -> list[WikiCandidate]:
    """所有活跃条目（用于相似度召回）。"""

    rows = session.scalars(
        select(WikiEntry).where(WikiEntry.status == WikiEntryStatus.ACTIVE)
    ).all()
    return [
        WikiCandidate(
            entry_id=entry.id,
            name=entry.name,
            summary=entry.summary or "",
            embedding=list(entry.embedding) if entry.embedding else None,
        )
        for entry in rows
    ]


def find_active_by_name(session: Session, name: str) -> WikiEntry | None:
    """按名称精确查找活跃条目（用于"同一知识点不重复建条目"）。"""

    return session.scalars(
        select(WikiEntry).where(
            WikiEntry.name == name.strip()[:300], WikiEntry.status == WikiEntryStatus.ACTIVE
        )
    ).first()
