"""T05 单站点抓取（含白名单/黑名单执行）测试。"""

from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.discovery import discover_article_urls
from app.crawler.fetcher import HttpxFetcher
from app.crawler.rate_limit import RateLimiter
from app.crawler.robots import DenyAllRobots, RobotFilePolicy
from app.crawler.service import crawl_source
from app.db.enums import CrawlStatus, SourceListType
from app.db.models import CrawlPage, Source
from tests.fakes import RaisingFetcher, StaticFetcher, load_fixture

INDEX_URL = "https://blog.example.com/"
POST_1 = "https://blog.example.com/posts/1"
POST_2 = "https://blog.example.com/posts/2"
ABOUT = "https://blog.example.com/about"
FIXED_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def make_source(session: Session, **overrides: object) -> Source:
    defaults: dict[str, object] = {
        "name": "示例博客",
        "site_url": INDEX_URL,
        "list_type": SourceListType.WHITELIST,
    }
    defaults.update(overrides)
    source = Source(**defaults)  # type: ignore[arg-type]
    session.add(source)
    session.flush()
    return source


def blog_fetcher(**kwargs: object) -> StaticFetcher:
    return StaticFetcher(
        {
            INDEX_URL: load_fixture("blog_index.html"),
            POST_1: load_fixture("blog_post_1.html"),
            POST_2: load_fixture("blog_post_2.html"),
            ABOUT: "<html><body>关于我们</body></html>",
        },
        **kwargs,  # type: ignore[arg-type]
    )


def assert_same_moment(actual: datetime | None, expected: datetime) -> None:
    """比较时间点，兼容 SQLite 返回 naive datetime 的行为。"""

    assert actual is not None
    if actual.tzinfo is None:
        actual = actual.replace(tzinfo=timezone.utc)
    assert actual == expected


def test_whitelist_source_is_crawled_and_raw_html_saved(db_session: Session) -> None:
    source = make_source(db_session)
    fetcher = blog_fetcher()

    report = crawl_source(db_session, source, fetcher=fetcher, now=lambda: FIXED_NOW)

    assert report.skipped is False
    assert report.fetched == 4
    assert report.failed == 0

    pages = db_session.scalars(select(CrawlPage)).all()
    assert len(pages) == 4
    post_1 = next(page for page in pages if page.url == POST_1)
    assert post_1.status is CrawlStatus.FETCHED
    assert post_1.http_status == 200
    assert post_1.raw_html is not None and "机器学习入门" in post_1.raw_html
    assert post_1.source_id == source.id
    assert post_1.fetched_at is not None
    assert_same_moment(post_1.fetched_at, FIXED_NOW)

    # 记录抓取时间（原始来源地址由 source_id + url 记录）
    assert_same_moment(source.last_crawled_at, FIXED_NOW)
    assert_same_moment(source.last_success_at, FIXED_NOW)


def test_blacklist_source_is_skipped_not_fetched(db_session: Session) -> None:
    source = make_source(db_session, list_type=SourceListType.BLACKLIST)
    fetcher = blog_fetcher()

    report = crawl_source(db_session, source, fetcher=fetcher, now=lambda: FIXED_NOW)

    assert report.skipped is True
    assert report.skip_reason == "blacklist"
    assert fetcher.calls == []
    assert db_session.scalars(select(CrawlPage)).all() == []
    assert source.last_crawled_at is None


def test_inactive_source_is_skipped(db_session: Session) -> None:
    source = make_source(db_session, is_active=False)
    fetcher = blog_fetcher()

    report = crawl_source(db_session, source, fetcher=fetcher, now=lambda: FIXED_NOW)

    assert report.skipped is True
    assert report.skip_reason == "inactive"
    assert fetcher.calls == []


def test_single_page_failure_does_not_break_the_run(db_session: Session) -> None:
    source = make_source(db_session)
    fetcher = RaisingFetcher(
        {
            INDEX_URL: load_fixture("blog_index.html"),
            POST_1: load_fixture("blog_post_1.html"),
            POST_2: load_fixture("blog_post_2.html"),
            ABOUT: "<html>about</html>",
        },
        raise_for={POST_1},
    )

    report = crawl_source(db_session, source, fetcher=fetcher, now=lambda: FIXED_NOW)

    assert report.failed == 1
    assert report.fetched == 3

    pages = {page.url: page for page in db_session.scalars(select(CrawlPage)).all()}
    assert pages[POST_1].status is CrawlStatus.FAILED
    assert pages[POST_1].error_message is not None
    assert "无法连接" in pages[POST_1].error_message
    assert pages[POST_2].status is CrawlStatus.FETCHED
    # 有部分成功，仍更新最后成功时间
    assert_same_moment(source.last_success_at, FIXED_NOW)


def test_unreachable_index_is_recorded_not_raised(db_session: Session) -> None:
    source = make_source(db_session)
    fetcher = StaticFetcher(failures={INDEX_URL: "connection timeout"})

    report = crawl_source(db_session, source, fetcher=fetcher, now=lambda: FIXED_NOW)

    assert report.failed == 1
    pages = db_session.scalars(select(CrawlPage)).all()
    assert len(pages) == 1
    assert pages[0].status is CrawlStatus.FAILED
    assert pages[0].error_message == "connection timeout"
    assert_same_moment(source.last_crawled_at, FIXED_NOW)
    assert source.last_success_at is None


def test_robots_denied_pages_are_not_fetched(db_session: Session) -> None:
    source = make_source(db_session)
    fetcher = blog_fetcher()

    report = crawl_source(
        db_session, source, fetcher=fetcher, robots=DenyAllRobots(), now=lambda: FIXED_NOW
    )

    assert report.robots_denied == 1
    assert report.fetched == 0
    assert fetcher.calls == []
    pages = db_session.scalars(select(CrawlPage)).all()
    assert pages[0].status is CrawlStatus.ROBOTS_DENIED


def test_rate_limiter_applies_min_interval(db_session: Session) -> None:
    source = make_source(db_session)
    fetcher = blog_fetcher()
    sleeps: list[float] = []
    limiter = RateLimiter(5.0, sleep=lambda seconds: sleeps.append(seconds))

    crawl_source(db_session, source, fetcher=fetcher, rate_limiter=limiter, now=lambda: FIXED_NOW)

    # 首页 + 3 个候选页共 4 次请求，除第一次外都应触发限流等待
    assert len(sleeps) >= 3
    assert all(seconds > 0 for seconds in sleeps)


def test_repeated_crawl_is_idempotent(db_session: Session) -> None:
    source = make_source(db_session)
    fetcher = blog_fetcher()

    crawl_source(db_session, source, fetcher=fetcher, now=lambda: FIXED_NOW)
    count_after_first = len(db_session.scalars(select(CrawlPage)).all())

    crawl_source(db_session, source, fetcher=fetcher, now=lambda: FIXED_NOW)

    assert len(db_session.scalars(select(CrawlPage)).all()) == count_after_first == 4


def test_single_url_source_falls_back_to_site_page(db_session: Session) -> None:
    source = make_source(db_session, site_url="https://solo.example.com/only-post")
    fetcher = StaticFetcher({"https://solo.example.com/only-post": "<html>单页内容</html>"})

    report = crawl_source(db_session, source, fetcher=fetcher, now=lambda: FIXED_NOW)

    assert report.fetched == 1
    pages = db_session.scalars(select(CrawlPage)).all()
    assert len(pages) == 1
    assert pages[0].url == "https://solo.example.com/only-post"
    assert pages[0].raw_html == "<html>单页内容</html>"


def test_explicit_article_urls_skip_index_discovery(db_session: Session) -> None:
    source = make_source(db_session)
    fetcher = StaticFetcher({POST_1: load_fixture("blog_post_1.html")})

    report = crawl_source(
        db_session,
        source,
        fetcher=fetcher,
        article_urls=[POST_1],
        now=lambda: FIXED_NOW,
    )

    assert report.fetched == 1
    assert fetcher.calls == [POST_1]  # 未请求首页


def test_discover_article_urls_filters_and_deduplicates() -> None:
    html = load_fixture("blog_index.html")

    urls = discover_article_urls(html, INDEX_URL)

    assert POST_1 in urls
    assert POST_2 in urls
    assert ABOUT in urls
    assert len(urls) == len(set(urls))
    assert all("other.example.com" not in url for url in urls)
    assert all(not url.startswith("mailto:") for url in urls)

    assert len(discover_article_urls(html, INDEX_URL, limit=2)) == 2
    assert "https://other.example.com/external" in discover_article_urls(
        html, INDEX_URL, same_domain=False
    )


def test_robot_file_policy_respects_rules() -> None:
    robots_txt = "User-agent: *\nDisallow: /private\n"
    fetcher = StaticFetcher({"https://blog.example.com/robots.txt": robots_txt})
    policy = RobotFilePolicy(fetcher, user_agent="BlogAggregatorBot")

    assert policy.can_fetch("https://blog.example.com/public") is True
    assert policy.can_fetch("https://blog.example.com/private") is False

    # robots.txt 不可用时按允许处理
    missing = RobotFilePolicy(StaticFetcher(), user_agent="BlogAggregatorBot")
    assert missing.can_fetch("https://blog.example.com/anything") is True


def test_httpx_fetcher_success_and_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ok":
            return httpx.Response(200, text="<html>ok</html>")
        if request.url.path == "/boom":
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(500, text="error")

    with HttpxFetcher(transport=httpx.MockTransport(handler)) as fetcher:
        ok = fetcher.fetch("https://example.com/ok")
        assert ok.ok is True
        assert ok.text == "<html>ok</html>"

        server_error = fetcher.fetch("https://example.com/fail")
        assert server_error.ok is False
        assert server_error.status_code == 500

        network_error = fetcher.fetch("https://example.com/boom")
        assert network_error.ok is False
        assert network_error.error is not None
