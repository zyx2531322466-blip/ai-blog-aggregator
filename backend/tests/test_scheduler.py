"""T17 来源级周期性采集调度测试。"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import ArticleStatus, SourceListType, UpdateFrequency
from app.db.models import Article, CrawlPage, DuplicateRelation, Source
from app.scheduler.frequency import (
    DEFAULT_FREQUENCY_INTERVALS,
    interval_for_source,
    is_due,
)
from app.services import scheduler_service
from app.services.pipeline_service import process_source
from tests.fakes import StaticFetcher, load_fixture

POST_1 = "https://blog.example.com/posts/1"
POST_2 = "https://blog.example.com/posts/2"
FIXED_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
TIERS_URL = "/api/v1/admin/sources/frequency-tiers"


def make_source(session: Session, **overrides: object) -> Source:
    defaults: dict[str, object] = {
        "name": "示例博客",
        "site_url": "https://blog.example.com/",
        "list_type": SourceListType.WHITELIST,
        "update_frequency": UpdateFrequency.NORMAL,
    }
    defaults.update(overrides)
    source = Source(**defaults)  # type: ignore[arg-type]
    session.add(source)
    session.flush()
    return source


# --- 频率档位与到期判定 ---------------------------------------------------------


def test_default_frequency_tiers(db_session: Session) -> None:
    high = make_source(
        db_session, site_url="https://high.example", update_frequency=UpdateFrequency.HIGH
    )
    normal = make_source(
        db_session, site_url="https://normal.example", update_frequency=UpdateFrequency.NORMAL
    )
    low = make_source(
        db_session, site_url="https://low.example", update_frequency=UpdateFrequency.LOW
    )

    assert interval_for_source(high) == DEFAULT_FREQUENCY_INTERVALS[UpdateFrequency.HIGH]
    assert interval_for_source(normal) == 24 * 3600
    assert interval_for_source(low) == 7 * 24 * 3600


def test_custom_frequency_uses_configured_interval(db_session: Session) -> None:
    source = make_source(
        db_session,
        update_frequency=UpdateFrequency.CUSTOM,
        update_interval_seconds=120,
    )
    assert interval_for_source(source) == 120


def test_is_due_logic(db_session: Session) -> None:
    source = make_source(db_session)
    assert is_due(source, now=FIXED_NOW) is True  # 从未抓取

    source.last_crawled_at = FIXED_NOW - timedelta(hours=1)
    assert is_due(source, now=FIXED_NOW) is False  # 普通档位未到 24 小时

    source.last_crawled_at = FIXED_NOW - timedelta(hours=25)
    assert is_due(source, now=FIXED_NOW) is True

    source.is_active = False
    assert is_due(source, now=FIXED_NOW) is False


def test_due_sources_excludes_blacklist(db_session: Session) -> None:
    make_source(db_session, site_url="https://white.example")
    make_source(db_session, site_url="https://black.example", list_type=SourceListType.BLACKLIST)
    db_session.commit()

    due = scheduler_service.due_sources(db_session, now=FIXED_NOW)
    assert [source.site_url for source in due] == ["https://white.example"]


# --- 调度触发与流水线 -----------------------------------------------------------


def test_due_source_is_crawled_and_processed(db_session: Session) -> None:
    # 让分类可用
    from app.services import category_service

    category_service.ensure_default_categories(db_session)

    due_source = make_source(db_session, site_url="https://due.example")
    not_due = make_source(db_session, site_url="https://fresh.example")
    not_due.last_crawled_at = FIXED_NOW
    db_session.commit()

    index_html = '<html><body><a href="https://due.example/posts/1">文章一</a></body></html>'
    fetcher = StaticFetcher(
        {
            "https://due.example": index_html,
            "https://due.example/posts/1": load_fixture("blog_post_1.html"),
        }
    )
    reports = scheduler_service.run_due_sources(
        db_session,
        fetcher_factory=lambda source: fetcher,
        now_factory=lambda: FIXED_NOW,
    )

    assert len(reports) == 1
    assert reports[0].source_id == due_source.id
    # 首页 + 发现的一篇文章
    assert reports[0].crawl.fetched == 2
    assert reports[0].parsed == 1

    # 新文章进入处理流程并被分类
    article = db_session.scalars(select(Article).where(Article.title == "机器学习入门")).one()
    assert article.status is ArticleStatus.NORMAL

    # 抓取时间被更新，下一次 tick 不再重复抓取
    assert due_source.last_crawled_at is not None
    assert not_due.last_crawled_at is not None


def test_scheduler_does_not_retrigger_before_interval(db_session: Session) -> None:
    source = make_source(db_session, site_url="https://due.example")
    db_session.commit()
    fetcher = StaticFetcher({POST_1: load_fixture("blog_post_1.html")})

    scheduler_service.run_due_sources(
        db_session,
        fetcher_factory=lambda s: fetcher,
        now_factory=lambda: FIXED_NOW,
    )
    calls_after_first = len(fetcher.calls)

    second = scheduler_service.run_due_sources(
        db_session,
        fetcher_factory=lambda s: fetcher,
        now_factory=lambda: FIXED_NOW,
    )

    assert second == []
    assert len(fetcher.calls) == calls_after_first
    assert source.last_crawled_at is not None


def test_pipeline_handles_new_content_on_later_run(db_session: Session) -> None:
    from app.services import category_service

    category_service.ensure_default_categories(db_session)
    source = make_source(db_session)

    first_fetcher = StaticFetcher({POST_1: load_fixture("blog_post_1.html")})
    process_source(
        db_session,
        source,
        fetcher=first_fetcher,
        article_urls=[POST_1],
        now=FIXED_NOW,
    )
    assert db_session.scalar(select(func.count()).select_from(Article)) == 1

    second_fetcher = StaticFetcher(
        {
            POST_1: load_fixture("blog_post_1.html"),
            POST_2: load_fixture("blog_post_2.html"),
        }
    )
    report = process_source(
        db_session,
        source,
        fetcher=second_fetcher,
        article_urls=[POST_1, POST_2],
        now=FIXED_NOW,
    )

    assert report.crawl.fetched == 2
    titles = {article.title for article in db_session.scalars(select(Article)).all()}
    assert titles == {"机器学习入门", "深度学习实践"}


def test_repeated_runs_do_not_create_dirty_data(db_session: Session) -> None:
    from app.services import category_service

    category_service.ensure_default_categories(db_session)
    source = make_source(db_session)
    fetcher = StaticFetcher({POST_1: load_fixture("blog_post_1.html")})

    def counts() -> tuple[int, int, int]:
        return (
            db_session.scalar(select(func.count()).select_from(CrawlPage)) or 0,
            db_session.scalar(select(func.count()).select_from(Article)) or 0,
            db_session.scalar(select(func.count()).select_from(DuplicateRelation)) or 0,
        )

    process_source(db_session, source, fetcher=fetcher, article_urls=[POST_1], now=FIXED_NOW)
    first_counts = counts()

    process_source(db_session, source, fetcher=fetcher, article_urls=[POST_1], now=FIXED_NOW)

    assert counts() == first_counts
    assert first_counts == (1, 1, 0)


# --- 频率档位接口 ---------------------------------------------------------------


def test_frequency_tiers_endpoint(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get(TIERS_URL, headers=admin_headers)
    assert response.status_code == 200
    tiers = response.json()
    assert {tier["frequency"] for tier in tiers} == {"high", "normal", "low"}
    assert all(tier["label"] and tier["interval_seconds"] > 0 for tier in tiers)


def test_frequency_tiers_requires_authorization(client: TestClient) -> None:
    assert client.get(TIERS_URL).status_code == 401
