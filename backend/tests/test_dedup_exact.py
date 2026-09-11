"""T09 完全重复识别与合并记录测试。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ArticleStatus, DedupRelationType, SourceListType
from app.db.models import Article, DuplicateRelation, Source
from app.dedup.fingerprint import content_fingerprint, normalize_content
from app.parser.html_parser import parse_html
from app.services import dedup_service
from tests.fakes import load_fixture

BASE_TIME = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def make_source(session: Session, name: str, url: str) -> Source:
    source = Source(name=name, site_url=url, list_type=SourceListType.WHITELIST)
    session.add(source)
    session.flush()
    return source


def make_article(
    session: Session,
    *,
    title: str,
    content: str,
    url: str,
    source: Source,
    created_at: datetime,
) -> Article:
    article = Article(
        title=title,
        content=content,
        url=url,
        source_id=source.id,
        status=ArticleStatus.NORMAL,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(article)
    session.flush()
    return article


def test_normalize_content_collapses_whitespace_and_width() -> None:
    assert normalize_content("  a   b\n\nc ") == "a b c"
    assert normalize_content("ＡＩ") == "AI"
    assert content_fingerprint("a  b") == content_fingerprint("a b")


def test_exact_duplicate_across_templates_is_merged(db_session: Session) -> None:
    parsed_a = parse_html(load_fixture("dup_a.html"), "https://a.example.com/post")
    parsed_b = parse_html(load_fixture("dup_b.html"), "https://b.example.com/post")
    # 站点模板/导航不同，但解析后的正文一致
    assert parsed_a.content == parsed_b.content

    source_a = make_source(db_session, "站点A", "https://a.example.com")
    source_b = make_source(db_session, "站点B", "https://b.example.com")

    first = make_article(
        db_session,
        title=parsed_a.title,
        content=parsed_a.content,
        url="https://a.example.com/post",
        source=source_a,
        created_at=BASE_TIME,
    )
    second = make_article(
        db_session,
        title=parsed_b.title,
        content=parsed_b.content,
        url="https://b.example.com/post",
        source=source_b,
        created_at=BASE_TIME + timedelta(hours=1),
    )

    first_outcome = dedup_service.process_article(db_session, first)
    second_outcome = dedup_service.process_article(db_session, second)

    assert first_outcome.is_duplicate is False
    assert second_outcome.is_duplicate is True
    assert second_outcome.relation is not None
    assert second_outcome.relation.relation_type is DedupRelationType.EXACT_DUPLICATE
    assert second_outcome.primary_article.id == first.id
    assert first.content_hash == second.content_hash == content_fingerprint(parsed_a.content)

    # 两篇来源均保留且可查询
    members = dedup_service.get_group_members(db_session, second)
    assert {article.id for article in members} == {first.id, second.id}
    assert {article.source_id for article in members} == {source_a.id, source_b.id}
    assert dedup_service.is_merged_member(db_session, second) is True
    assert dedup_service.is_merged_member(db_session, first) is False


def test_different_content_is_not_merged(db_session: Session) -> None:
    parsed_a = parse_html(load_fixture("blog_post_1.html"), "https://a.example.com/1")
    parsed_b = parse_html(load_fixture("blog_post_2.html"), "https://b.example.com/2")

    source = make_source(db_session, "站点A", "https://a.example.com")
    first = make_article(
        db_session,
        title=parsed_a.title,
        content=parsed_a.content,
        url="https://a.example.com/1",
        source=source,
        created_at=BASE_TIME,
    )
    second = make_article(
        db_session,
        title=parsed_b.title,
        content=parsed_b.content,
        url="https://b.example.com/2",
        source=source,
        created_at=BASE_TIME + timedelta(hours=1),
    )

    dedup_service.process_article(db_session, first)
    outcome = dedup_service.process_article(db_session, second)

    assert outcome.is_duplicate is False
    # 正文不同 → 不得判定为完全重复（允许 T14 的"关联推荐"关系存在）
    merge_relations = db_session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.relation_type.in_(
                (DedupRelationType.EXACT_DUPLICATE, DedupRelationType.NEAR_DUPLICATE)
            )
        )
    ).all()
    assert merge_relations == []


def test_processing_same_article_twice_is_idempotent(db_session: Session) -> None:
    parsed_a = parse_html(load_fixture("dup_a.html"), "https://a.example.com/post")
    parsed_b = parse_html(load_fixture("dup_b.html"), "https://b.example.com/post")
    source = make_source(db_session, "站点A", "https://a.example.com")

    first = make_article(
        db_session,
        title=parsed_a.title,
        content=parsed_a.content,
        url="https://a.example.com/post",
        source=source,
        created_at=BASE_TIME,
    )
    second = make_article(
        db_session,
        title=parsed_b.title,
        content=parsed_b.content,
        url="https://b.example.com/post",
        source=source,
        created_at=BASE_TIME + timedelta(hours=1),
    )

    dedup_service.process_article(db_session, first)
    dedup_service.process_article(db_session, second)
    dedup_service.process_article(db_session, second)

    duplicate_members = db_session.scalars(
        select(DuplicateRelation).where(DuplicateRelation.article_id == second.id)
    ).all()
    assert len(duplicate_members) == 1


def test_empty_content_is_not_treated_as_duplicate(db_session: Session) -> None:
    source = make_source(db_session, "站点A", "https://a.example.com")
    blank_a = make_article(
        db_session,
        title="空A",
        content="",
        url="https://a.example.com/a",
        source=source,
        created_at=BASE_TIME,
    )
    blank_b = make_article(
        db_session,
        title="空B",
        content="   ",
        url="https://a.example.com/b",
        source=source,
        created_at=BASE_TIME + timedelta(hours=1),
    )

    dedup_service.process_article(db_session, blank_a)
    outcome = dedup_service.process_article(db_session, blank_b)

    assert outcome.is_duplicate is False
