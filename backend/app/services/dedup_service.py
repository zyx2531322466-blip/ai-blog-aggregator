"""精确去重、近重复与不同视角关联（T09 / T13 / T14）。

- 完全重复：正文指纹相同 → 强制合并，不受阈值配置影响；
- 近重复：SimHash 相似度达到（可配置的）阈值 → 合并，默认阈值取保守方向；
- 不同视角/证据不充分：相似但未达阈值 → 不合并，仅写入"关联推荐"关系；
- 合并关系写入 `duplicate_relations`；合并组内所有来源均保留。
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import generate_id
from app.db.enums import DedupRelationType
from app.db.models import Article, DuplicateRelation
from app.dedup.fingerprint import content_fingerprint
from app.dedup.simhash import compute_simhash, from_signed64, simhash_similarity, to_signed64
from app.services import dedup_settings_service, primary_selection_service

MERGE_TYPES = (DedupRelationType.EXACT_DUPLICATE, DedupRelationType.NEAR_DUPLICATE)

# T14：达到该相似度但未达合并阈值时，视为"同事件不同视角/证据不充分"，只建立关联
RELATED_MIN_SIMILARITY = 0.5


@dataclass
class DedupOutcome:
    """一次去重处理的结果。"""

    article: Article
    is_duplicate: bool
    fingerprint: str
    relation: DuplicateRelation | None = None
    primary_article: Article | None = None
    related_article: Article | None = None
    similarity: float | None = None


def compute_and_store_fingerprint(session: Session, article: Article) -> str:
    """计算并写入文章正文指纹。"""

    article.content_hash = content_fingerprint(article.content)
    session.flush()
    return article.content_hash


def find_exact_duplicates(session: Session, fingerprint: str, *, exclude_id: str) -> list[Article]:
    """查找正文指纹相同、且非自身的文章。"""

    statement = select(Article).where(Article.content_hash == fingerprint, Article.id != exclude_id)
    return list(session.scalars(statement))


def resolve_primary(session: Session, article: Article) -> Article:
    """沿合并关系回溯到合并组的主记录（无关系时返回自身）。"""

    visited: set[str] = set()
    current = article
    while current.id not in visited:
        visited.add(current.id)
        relation = session.scalars(
            select(DuplicateRelation).where(
                DuplicateRelation.article_id == current.id,
                DuplicateRelation.is_primary.is_(False),
                DuplicateRelation.relation_type.in_(MERGE_TYPES),
            )
        ).first()
        if relation is None or relation.target_article_id is None:
            break
        if relation.target_article_id == current.id:
            break
        target = session.get(Article, relation.target_article_id)
        if target is None:
            break
        current = target
    return current


def process_article(
    session: Session, article: Article, *, near_threshold: float | None = None
) -> DedupOutcome:
    """对单篇文章执行完全重复 + 近重复判定，必要时写入合并关系。"""

    existing_membership = _membership_relation(session, article.id)
    fingerprint = compute_and_store_fingerprint(session, article)
    article.simhash = to_signed64(compute_simhash(article.content))
    session.flush()

    if existing_membership is not None:
        primary = (
            session.get(Article, existing_membership.target_article_id)
            if existing_membership.target_article_id
            else None
        )
        session.commit()
        return DedupOutcome(
            article=article,
            is_duplicate=True,
            fingerprint=fingerprint,
            relation=existing_membership,
            primary_article=primary,
            similarity=existing_membership.similarity,
        )

    # 已是某个合并组的主记录：无需重复处理（幂等）
    if _primary_row(session, article.id) is not None:
        session.commit()
        return DedupOutcome(article=article, is_duplicate=False, fingerprint=fingerprint)

    candidates = [
        candidate
        for candidate in find_exact_duplicates(session, fingerprint, exclude_id=article.id)
        if not _is_empty_fingerprint(candidate)
    ]
    if candidates:
        # 以创建时间最早的文章作为初始主记录（T18 再做更精细的主记录选择）
        primary = min(candidates, key=lambda candidate: candidate.created_at)
        relation = merge_duplicate(
            session,
            duplicate=article,
            primary=primary,
            relation_type=DedupRelationType.EXACT_DUPLICATE,
            similarity=1.0,
            evidence="正文指纹相同（仅模板/导航差异）",
        )
        return DedupOutcome(
            article=article,
            is_duplicate=True,
            fingerprint=fingerprint,
            relation=relation,
            primary_article=primary,
            similarity=1.0,
        )

    if near_threshold is not None:
        threshold = near_threshold
    else:
        threshold = dedup_settings_service.get_near_duplicate_threshold(session)

    most_similar, similarity = _find_most_similar_article(session, article)
    if most_similar is not None and similarity >= threshold:
        relation = merge_duplicate(
            session,
            duplicate=article,
            primary=most_similar,
            relation_type=DedupRelationType.NEAR_DUPLICATE,
            similarity=similarity,
            evidence=f"SimHash 相似度 {similarity:.3f} ≥ 阈值 {threshold:.2f}",
        )
        return DedupOutcome(
            article=article,
            is_duplicate=True,
            fingerprint=fingerprint,
            relation=relation,
            primary_article=most_similar,
            similarity=similarity,
        )

    # T14：怀疑是"同一事件不同视角"或证据不充分 → 不合并，仅建立关联推荐
    if most_similar is not None and similarity >= RELATED_MIN_SIMILARITY:
        relation = create_related_relation(
            session,
            article=article,
            related=most_similar,
            similarity=similarity,
            evidence=f"相似度 {similarity:.3f} < 合并阈值 {threshold:.2f}，按不同视角关联（不合并）",
        )
        return DedupOutcome(
            article=article,
            is_duplicate=False,
            fingerprint=fingerprint,
            relation=relation,
            related_article=most_similar,
            similarity=similarity,
        )

    session.commit()
    return DedupOutcome(
        article=article,
        is_duplicate=False,
        fingerprint=fingerprint,
        similarity=similarity if similarity else None,
    )


def _find_most_similar_article(session: Session, article: Article) -> tuple[Article | None, float]:
    """查找与给定文章最相似的文章（不考虑阈值，由调用方决策）。"""

    if article.simhash is None or not (article.content or "").strip():
        return None, 0.0

    article_hash = from_signed64(article.simhash)
    statement = select(Article).where(Article.id != article.id, Article.simhash.is_not(None))

    best: Article | None = None
    best_similarity = 0.0
    for candidate in session.scalars(statement):
        if not (candidate.content or "").strip():
            continue
        similarity = simhash_similarity(article_hash, from_signed64(candidate.simhash or 0))
        if similarity > best_similarity:
            best, best_similarity = candidate, similarity

    return best, best_similarity


def create_related_relation(
    session: Session,
    *,
    article: Article,
    related: Article,
    similarity: float | None = None,
    evidence: str | None = None,
) -> DuplicateRelation:
    """写入"关联推荐"关系（不合并），并保证幂等。"""

    existing = session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.relation_type == DedupRelationType.RELATED,
            DuplicateRelation.article_id == article.id,
            DuplicateRelation.target_article_id == related.id,
        )
    ).first()
    if existing is not None:
        session.commit()
        return existing

    relation = DuplicateRelation(
        relation_type=DedupRelationType.RELATED,
        article_id=article.id,
        target_article_id=related.id,
        is_primary=False,
        similarity=similarity,
        evidence=evidence,
    )
    session.add(relation)
    session.commit()
    session.refresh(relation)
    return relation


def get_related_articles(session: Session, article: Article) -> list[Article]:
    """返回文章的关联推荐文章（双向），不包含合并组成员。"""

    relations = session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.relation_type == DedupRelationType.RELATED,
            (DuplicateRelation.article_id == article.id)
            | (DuplicateRelation.target_article_id == article.id),
        )
    ).all()

    related_ids: set[str] = set()
    for relation in relations:
        other_id = (
            relation.target_article_id if relation.article_id == article.id else relation.article_id
        )
        if other_id and other_id != article.id:
            related_ids.add(other_id)

    return [
        candidate for candidate in (session.get(Article, rid) for rid in related_ids) if candidate
    ]


def merge_duplicate(
    session: Session,
    *,
    duplicate: Article,
    primary: Article,
    relation_type: DedupRelationType,
    similarity: float | None = None,
    evidence: str | None = None,
) -> DuplicateRelation:
    """将 ``duplicate`` 合并到 ``primary`` 所在合并组，并写入关系记录。"""

    canonical = resolve_primary(session, primary)
    group_key = _group_key_for(session, canonical) or f"group_{generate_id('g').split('_', 1)[1]}"
    _ensure_primary_row(session, canonical, group_key, relation_type)

    # 合并优先于关联：清理两者之间已有的"关联推荐"关系
    _remove_related_relations(session, duplicate.id, canonical.id)

    relation = DuplicateRelation(
        group_key=group_key,
        relation_type=relation_type,
        article_id=duplicate.id,
        target_article_id=canonical.id,
        is_primary=False,
        similarity=similarity,
        evidence=evidence,
    )
    session.add(relation)
    session.commit()
    session.refresh(relation)

    # T18：合并后按既定优先级（权重 > 时间 > 完整度 > 可访问性 > 标题）确定主记录
    primary_selection_service.select_and_apply_primary(session, group_key)
    return relation


def _remove_related_relations(session: Session, left_id: str, right_id: str) -> None:
    relations = session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.relation_type == DedupRelationType.RELATED,
            (
                (DuplicateRelation.article_id == left_id)
                & (DuplicateRelation.target_article_id == right_id)
            )
            | (
                (DuplicateRelation.article_id == right_id)
                & (DuplicateRelation.target_article_id == left_id)
            ),
        )
    ).all()
    for relation in relations:
        session.delete(relation)
    session.flush()


def is_merged_member(session: Session, article: Article) -> bool:
    """判断文章是否为合并组中的"非主记录"成员。"""

    return _membership_relation(session, article.id) is not None


def get_group_members(session: Session, article: Article) -> list[Article]:
    """返回文章所在合并组的全部文章（含主记录）；不在组内时返回自身。"""

    canonical = resolve_primary(session, article)
    group_key = _group_key_for(session, canonical) or _group_key_for(session, article)
    if group_key is None:
        return [article]

    member_ids = session.scalars(
        select(DuplicateRelation.article_id).where(
            DuplicateRelation.group_key == group_key,
            DuplicateRelation.relation_type.in_(MERGE_TYPES),
        )
    ).all()
    articles = {member_id: session.get(Article, member_id) for member_id in set(member_ids)}
    return [candidate for candidate in articles.values() if candidate is not None]


def _membership_relation(session: Session, article_id: str) -> DuplicateRelation | None:
    return session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.article_id == article_id,
            DuplicateRelation.is_primary.is_(False),
            DuplicateRelation.relation_type.in_(MERGE_TYPES),
        )
    ).first()


def _primary_row(session: Session, article_id: str) -> DuplicateRelation | None:
    return session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.article_id == article_id,
            DuplicateRelation.is_primary.is_(True),
            DuplicateRelation.relation_type.in_(MERGE_TYPES),
        )
    ).first()


def _group_key_for(session: Session, article: Article) -> str | None:
    relation = session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.article_id == article.id, DuplicateRelation.group_key.is_not(None)
        )
    ).first()
    return relation.group_key if relation is not None else None


def _ensure_primary_row(
    session: Session,
    primary: Article,
    group_key: str,
    relation_type: DedupRelationType,
) -> DuplicateRelation:
    existing = _primary_row(session, primary.id)
    if existing is not None:
        existing.group_key = group_key
        session.flush()
        return existing
    row = DuplicateRelation(
        group_key=group_key,
        relation_type=relation_type,
        article_id=primary.id,
        target_article_id=primary.id,
        is_primary=True,
        similarity=1.0,
        evidence="合并组主记录",
    )
    session.add(row)
    session.flush()
    return row


def _is_empty_fingerprint(article: Article) -> bool:
    return not (article.content or "").strip()


# --- T15：去重命中记录与阈值变更预览 ---------------------------------------------


@dataclass
class PairChange:
    """一对文章在阈值变化前后的判定差异。"""

    article_id: str
    other_article_id: str
    similarity: float
    current: str
    proposed: str


@dataclass
class ThresholdPreview:
    """阈值变更预览结果。"""

    current_threshold: float
    proposed_threshold: float
    would_merge: list[PairChange] = field(default_factory=list)
    would_unmerge: list[PairChange] = field(default_factory=list)
    would_relate: list[PairChange] = field(default_factory=list)
    would_unrelate: list[PairChange] = field(default_factory=list)
    unchanged_count: int = 0


def list_relation_hits(session: Session) -> list[tuple[DuplicateRelation, Article, Article | None]]:
    """返回全部去重命中记录（含完全重复/近重复的合并与关联推荐）。

    每项为 ``(关系, 主记录/关联目标, 被合并文章)``。
    """

    statement = (
        select(DuplicateRelation)
        .where(DuplicateRelation.is_primary.is_(False))
        .order_by(DuplicateRelation.created_at)
    )
    hits: list[tuple[DuplicateRelation, Article, Article | None]] = []
    for relation in session.scalars(statement):
        member = session.get(Article, relation.article_id)
        target = (
            session.get(Article, relation.target_article_id) if relation.target_article_id else None
        )
        if member is not None:
            hits.append((relation, target, member))
    return hits


def preview_threshold_change(session: Session, new_threshold: float) -> ThresholdPreview:
    """基于当前数据集，模拟新阈值下哪些现有判定会发生变化。"""

    current_threshold = dedup_settings_service.get_near_duplicate_threshold(session)
    articles = [
        article
        for article in session.scalars(select(Article))
        if (article.content or "").strip() and article.content_hash
    ]

    canonical = {article.id: resolve_primary(session, article).id for article in articles}
    related_pairs = _related_pairs(session, {article.id for article in articles})

    preview = ThresholdPreview(
        current_threshold=current_threshold, proposed_threshold=new_threshold
    )

    for index, left in enumerate(articles):
        for right in articles[index + 1 :]:
            if left.content_hash == right.content_hash:
                preview.unchanged_count += 1
                continue

            similarity = simhash_similarity(
                from_signed64(left.simhash or 0), from_signed64(right.simhash or 0)
            )
            if canonical[left.id] == canonical[right.id]:
                current = DedupRelationType.NEAR_DUPLICATE.value
            elif (left.id, right.id) in related_pairs or (right.id, left.id) in related_pairs:
                current = DedupRelationType.RELATED.value
            else:
                current = "none"

            if similarity >= new_threshold:
                proposed = DedupRelationType.NEAR_DUPLICATE.value
            elif similarity >= RELATED_MIN_SIMILARITY:
                proposed = DedupRelationType.RELATED.value
            else:
                proposed = "none"

            if current == proposed:
                preview.unchanged_count += 1
                continue

            change = PairChange(
                article_id=left.id,
                other_article_id=right.id,
                similarity=round(similarity, 4),
                current=current,
                proposed=proposed,
            )
            if proposed == DedupRelationType.NEAR_DUPLICATE.value:
                preview.would_merge.append(change)
            elif current == DedupRelationType.NEAR_DUPLICATE.value:
                preview.would_unmerge.append(change)
            elif proposed == DedupRelationType.RELATED.value:
                preview.would_relate.append(change)
            else:
                preview.would_unrelate.append(change)

    return preview


def _related_pairs(session: Session, article_ids: set[str]) -> set[tuple[str, str]]:
    if not article_ids:
        return set()
    relations = session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.relation_type == DedupRelationType.RELATED,
            DuplicateRelation.article_id.in_(article_ids),
            DuplicateRelation.target_article_id.in_(article_ids),
        )
    ).all()
    return {(relation.article_id, relation.target_article_id) for relation in relations}
