"""合并组主记录的选择、失效检测与切换（T18）。"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.enums import DedupRelationType
from app.db.models import Article, DuplicateRelation
from app.dedup.primary import choose_primary

MERGE_TYPES = (DedupRelationType.EXACT_DUPLICATE, DedupRelationType.NEAR_DUPLICATE)
PRIMARY_EVIDENCE = "合并组主记录"


@dataclass
class PrimaryRefreshResult:
    """一次主记录刷新结果。"""

    group_key: str
    previous_primary_id: str | None
    primary_id: str
    changed: bool


def get_group_members_by_key(session: Session, group_key: str) -> list[Article]:
    """按合并组键返回全部成员。"""

    member_ids = session.scalars(
        select(DuplicateRelation.article_id).where(
            DuplicateRelation.group_key == group_key,
            DuplicateRelation.relation_type.in_(MERGE_TYPES),
        )
    ).all()
    members = [session.get(Article, member_id) for member_id in set(member_ids)]
    return [member for member in members if member is not None]


def get_group_keys(session: Session) -> list[str]:
    """返回全部合并组键。"""

    keys = session.scalars(
        select(DuplicateRelation.group_key)
        .where(
            DuplicateRelation.group_key.is_not(None),
            DuplicateRelation.relation_type.in_(MERGE_TYPES),
        )
        .distinct()
    ).all()
    return [key for key in keys if key]


def group_key_for_article(session: Session, article_id: str) -> str | None:
    """返回文章所属合并组键（不在任何合并组时返回 None）。"""

    relation = session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.article_id == article_id,
            DuplicateRelation.group_key.is_not(None),
            DuplicateRelation.relation_type.in_(MERGE_TYPES),
        )
    ).first()
    return relation.group_key if relation is not None else None


def current_primary_id(session: Session, group_key: str) -> str | None:
    """返回合并组当前主记录 ID（主记录行 / 成员指向的目标）。"""

    primary_row = session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.group_key == group_key,
            DuplicateRelation.relation_type.in_(MERGE_TYPES),
            DuplicateRelation.is_primary.is_(True),
        )
    ).first()
    if primary_row is not None:
        return primary_row.article_id
    member_row = session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.group_key == group_key,
            DuplicateRelation.relation_type.in_(MERGE_TYPES),
        )
    ).first()
    return member_row.target_article_id if member_row is not None else None


def apply_primary(session: Session, group_key: str, primary_id: str) -> None:
    """将合并组主记录切换为 ``primary_id``，并重建组内关系行。"""

    relations = session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.group_key == group_key,
            DuplicateRelation.relation_type.in_(MERGE_TYPES),
        )
    ).all()
    if not relations:
        return

    relation_type = DedupRelationType.EXACT_DUPLICATE
    member_info: dict[str, tuple[float | None, str | None]] = {}
    member_ids: set[str] = set()
    for relation in relations:
        if relation.relation_type is DedupRelationType.NEAR_DUPLICATE:
            relation_type = DedupRelationType.NEAR_DUPLICATE
        member_ids.add(relation.article_id)
        if not relation.is_primary and relation.article_id != primary_id:
            member_info[relation.article_id] = (relation.similarity, relation.evidence)

    primary = session.get(Article, primary_id)
    if primary is None:
        return

    for relation in relations:
        session.delete(relation)
    session.flush()

    session.add(
        DuplicateRelation(
            group_key=group_key,
            relation_type=relation_type,
            article_id=primary.id,
            target_article_id=primary.id,
            is_primary=True,
            similarity=1.0,
            evidence=PRIMARY_EVIDENCE,
        )
    )
    for member_id in member_ids:
        if member_id == primary.id:
            continue
        similarity, evidence = member_info.get(member_id, (1.0, None))
        session.add(
            DuplicateRelation(
                group_key=group_key,
                relation_type=relation_type,
                article_id=member_id,
                target_article_id=primary.id,
                is_primary=False,
                similarity=similarity,
                evidence=evidence,
            )
        )
    session.flush()


def select_and_apply_primary(session: Session, group_key: str) -> PrimaryRefreshResult | None:
    """按优先级重新选择主记录，必要时切换。"""

    members = get_group_members_by_key(session, group_key)
    if not members:
        return None

    previous = current_primary_id(session, group_key)
    chosen = choose_primary(members)
    if previous != chosen.id:
        apply_primary(session, group_key, chosen.id)
        session.commit()
    return PrimaryRefreshResult(
        group_key=group_key,
        previous_primary_id=previous,
        primary_id=chosen.id,
        changed=previous != chosen.id,
    )


def refresh_all_group_primaries(session: Session) -> list[PrimaryRefreshResult]:
    """对所有合并组重新应用主记录选择规则（自动检测失效并切换）。"""

    results = []
    for group_key in get_group_keys(session):
        result = select_and_apply_primary(session, group_key)
        if result is not None:
            results.append(result)
    return results


def mark_article_inaccessible(session: Session, article_id: str) -> None:
    """标记文章原文不可访问（供失效检测/切换使用）。"""

    article = session.get(Article, article_id)
    if article is None:
        return
    article.is_accessible = False
    article.accessibility_checked_at = utcnow()
    session.flush()
