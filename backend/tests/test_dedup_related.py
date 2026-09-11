"""T14 同一事件不同视角识别与关联推荐（不合并）测试。"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ArticleStatus, DedupRelationType, SourceListType
from app.db.models import Article, DuplicateRelation, Source
from app.parser.html_parser import parse_html
from app.services import dedup_service, dedup_settings_service
from tests.fakes import load_fixture

BASE = (
    "昨天，某科技公司在一场发布会上正式推出了新一代人工智能模型。"
    "该模型在多项基准测试中取得了领先成绩，并支持更长的上下文。"
    "公司表示，新模型将在下个月面向开发者开放接口。"
    "业内专家认为，这次发布可能会改变现有的竞争格局。"
)
REPOST = (
    "昨天，某科技公司在一场发布会上正式推出了新一代人工智能模型。"
    "该模型在多项基准测试中取得了领先成绩，并支持更长的上下文。"
    "公司表示，新模型将在下个月面向开发者开放接口。"
    "业内专家认为，这次发布或将改变现有的竞争格局。"
)
# 同一事件、不同视角（竞争对手/开发者的反应）
REACTION = (
    "针对某科技公司昨天发布的新一代人工智能模型，多家竞争对手今天作出了回应。"
    "有公司宣布将加快自家模型的迭代节奏，也有开发者担心价格与合规问题。"
)
# 主题相关但改写幅度较大、证据不充分
UNCERTAIN = (
    "某公司昨日发布了一款新的人工智能模型。"
    "据介绍，该模型在若干测试中表现优异，上下文长度也有所提升。"
    "开发者预计可以在下月获得接口。"
    "有分析人士指出，此举或许会重塑行业竞争态势。"
)
UNRELATED = (
    "本文介绍了如何使用 Postgres 的索引优化慢查询，并给出了几个实际案例。"
    "同时讨论了事务隔离级别对并发性能的影响。"
)

BASE_TIME = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def make_source(session: Session) -> Source:
    source = Source(
        name="站点A", site_url="https://a.example.com", list_type=SourceListType.WHITELIST
    )
    session.add(source)
    session.flush()
    return source


def make_article(
    session: Session, source: Source, *, title: str, content: str, url: str, created_at: datetime
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


def _add(
    session: Session, source: Source, title: str, content: str, url: str, hours: int
) -> Article:
    return make_article(
        session,
        source,
        title=title,
        content=content,
        url=url,
        created_at=BASE_TIME + timedelta(hours=hours),
    )


def test_different_view_is_not_merged_but_related(db_session: Session) -> None:
    source = make_source(db_session)
    base = _add(db_session, source, "原新闻", BASE, "https://a.example.com/1", 0)
    reaction = _add(db_session, source, "行业反应", REACTION, "https://b.example.com/1", 1)

    dedup_service.process_article(db_session, base)
    outcome = dedup_service.process_article(db_session, reaction)

    assert outcome.is_duplicate is False
    assert outcome.related_article is not None
    assert outcome.relation is not None
    assert outcome.relation.relation_type is DedupRelationType.RELATED

    # 两篇文章均独立保留（未被合并）
    assert dedup_service.is_merged_member(db_session, reaction) is False
    assert {article.id for article in dedup_service.get_group_members(db_session, base)} == {
        base.id
    }
    assert {article.id for article in dedup_service.get_related_articles(db_session, base)} == {
        reaction.id
    }


def test_insufficient_evidence_defaults_to_related_not_merged(db_session: Session) -> None:
    source = make_source(db_session)
    base = _add(db_session, source, "原新闻", BASE, "https://a.example.com/1", 0)
    uncertain = _add(db_session, source, "改写稿", UNCERTAIN, "https://b.example.com/1", 1)

    dedup_service.process_article(db_session, base)
    outcome = dedup_service.process_article(db_session, uncertain)

    assert outcome.is_duplicate is False
    assert outcome.relation.relation_type is DedupRelationType.RELATED
    assert dedup_service.is_merged_member(db_session, uncertain) is False


def test_unrelated_content_has_no_relation(db_session: Session) -> None:
    source = make_source(db_session)
    base = _add(db_session, source, "原新闻", BASE, "https://a.example.com/1", 0)
    unrelated = _add(db_session, source, "数据库文章", UNRELATED, "https://b.example.com/1", 1)

    dedup_service.process_article(db_session, base)
    outcome = dedup_service.process_article(db_session, unrelated)

    assert outcome.is_duplicate is False
    assert outcome.relation is None
    assert db_session.scalars(select(DuplicateRelation)).all() == []
    assert dedup_service.get_related_articles(db_session, base) == []


def test_related_relation_is_idempotent(db_session: Session) -> None:
    source = make_source(db_session)
    base = _add(db_session, source, "原新闻", BASE, "https://a.example.com/1", 0)
    reaction = _add(db_session, source, "行业反应", REACTION, "https://b.example.com/1", 1)

    dedup_service.process_article(db_session, base)
    dedup_service.process_article(db_session, reaction)
    dedup_service.process_article(db_session, reaction)

    relations = db_session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.relation_type == DedupRelationType.RELATED
        )
    ).all()
    assert len(relations) == 1


def test_merge_takes_precedence_and_cleans_related(db_session: Session) -> None:
    source = make_source(db_session)
    base = _add(db_session, source, "原新闻", BASE, "https://a.example.com/1", 0)
    rewrite = _add(db_session, source, "改写稿", UNCERTAIN, "https://b.example.com/1", 1)

    dedup_service.process_article(db_session, base)
    assert dedup_service.process_article(db_session, rewrite).relation.relation_type is (
        DedupRelationType.RELATED
    )

    # 阈值调低后应真正合并，并清理先前的关联关系
    dedup_settings_service.set_near_duplicate_threshold(db_session, 0.6)
    outcome = dedup_service.process_article(db_session, rewrite)

    assert outcome.is_duplicate is True
    assert {article.id for article in dedup_service.get_group_members(db_session, base)} == {
        base.id,
        rewrite.id,
    }
    assert dedup_service.get_related_articles(db_session, base) == []


def test_regression_exact_duplicate_still_merges(db_session: Session) -> None:
    source = make_source(db_session)
    content_a = load_fixture("dup_a.html")
    content_b = load_fixture("dup_b.html")
    parsed_a = parse_html(content_a, "https://a.example.com/1")
    parsed_b = parse_html(content_b, "https://b.example.com/1")
    first = _add(db_session, source, parsed_a.title, parsed_a.content, "https://a.example.com/1", 0)
    second = _add(
        db_session, source, parsed_b.title, parsed_b.content, "https://b.example.com/1", 1
    )

    dedup_service.process_article(db_session, first)
    outcome = dedup_service.process_article(db_session, second)

    assert outcome.is_duplicate is True
    assert outcome.relation.relation_type is DedupRelationType.EXACT_DUPLICATE


def test_regression_near_duplicate_still_merges(db_session: Session) -> None:
    source = make_source(db_session)
    base = _add(db_session, source, "原新闻", BASE, "https://a.example.com/1", 0)
    repost = _add(db_session, source, "转载", REPOST, "https://b.example.com/1", 1)

    dedup_service.process_article(db_session, base)
    outcome = dedup_service.process_article(db_session, repost)

    assert outcome.is_duplicate is True
    assert outcome.relation.relation_type is DedupRelationType.NEAR_DUPLICATE


def test_detail_api_exposes_related_articles(client: TestClient, api_session: Session) -> None:
    source = Source(
        name="站点A", site_url="https://a.example.com", list_type=SourceListType.WHITELIST
    )
    api_session.add(source)
    api_session.flush()
    base = _add(api_session, source, "原新闻", BASE, "https://a.example.com/1", 0)
    reaction = _add(api_session, source, "行业反应", REACTION, "https://b.example.com/1", 1)
    api_session.commit()

    dedup_service.process_article(api_session, base)
    dedup_service.process_article(api_session, reaction)

    # 两篇都独立出现在列表中
    listing = client.get("/api/v1/articles").json()
    assert listing["total"] == 2

    detail = client.get(f"/api/v1/articles/{base.id}").json()
    assert len(detail["sources"]) == 1
    related = detail["related_articles"]
    assert [item["id"] for item in related] == [reaction.id]
    assert related[0]["url"] == "https://b.example.com/1"
