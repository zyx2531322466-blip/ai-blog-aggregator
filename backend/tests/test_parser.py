"""T06 内容解析与元信息提取测试。"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ArticleStatus, CrawlStatus, SourceListType
from app.db.models import Article, CrawlPage, Source
from app.parser.html_parser import ParseError, parse_html
from app.services.article_service import parse_crawl_page, parse_crawl_pages, summarize
from tests.fakes import load_fixture

POST_URL = "https://blog.example.com/posts/1"
POST_2_URL = "https://blog.example.com/posts/2"
JSONLD_URL = "https://blog.example.com/posts/jsonld"


def make_source(session: Session) -> Source:
    source = Source(
        name="示例博客", site_url="https://blog.example.com/", list_type=SourceListType.WHITELIST
    )
    session.add(source)
    session.flush()
    return source


def make_crawl_page(
    session: Session,
    source: Source,
    url: str,
    html: str | None,
    *,
    status: CrawlStatus = CrawlStatus.FETCHED,
) -> CrawlPage:
    page = CrawlPage(
        source_id=source.id,
        url=url,
        raw_html=html,
        http_status=200,
        status=status,
        fetched_at=datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc),
    )
    session.add(page)
    session.flush()
    return page


# --- 解析器：至少覆盖 2 种页面结构 -------------------------------------------------


def test_parse_standard_article_structure() -> None:
    parsed = parse_html(load_fixture("blog_post_1.html"), POST_URL)

    assert parsed.title == "机器学习入门"
    assert "机器学习" in parsed.content
    assert "第二段正文" in parsed.content
    assert parsed.author == "张三"
    assert parsed.published_at is not None
    assert (parsed.published_at.year, parsed.published_at.month, parsed.published_at.day) == (
        2026,
        9,
        1,
    )


def test_parse_second_article_structure() -> None:
    parsed = parse_html(load_fixture("blog_post_2.html"), POST_2_URL)

    assert parsed.title == "深度学习实践"
    assert "神经网络" in parsed.content
    assert parsed.published_at is None


def test_parse_jsonld_structure() -> None:
    parsed = parse_html(load_fixture("blog_post_jsonld.html"), JSONLD_URL)

    assert parsed.title == "JSON-LD 结构文章"
    assert parsed.author == "李四"
    assert parsed.published_at is not None
    assert parsed.published_at.utcoffset() is not None
    assert parsed.published_at.utcoffset().total_seconds() == 8 * 3600
    assert "第一篇段落" in parsed.content


def test_parse_empty_html_raises() -> None:
    try:
        parse_html("", POST_URL)
    except ParseError:
        pass
    else:  # pragma: no cover - 失败路径
        raise AssertionError("空 HTML 应抛出 ParseError")


def test_parse_content_too_short_raises() -> None:
    try:
        parse_html(load_fixture("empty_page.html"), POST_URL)
    except ParseError as exc:
        assert "正文" in str(exc)
    else:  # pragma: no cover - 失败路径
        raise AssertionError("正文过短应抛出 ParseError")


# --- 落库：状态与兜底 -------------------------------------------------------------


def test_parse_crawl_page_writes_pending_article(db_session: Session) -> None:
    source = make_source(db_session)
    page = make_crawl_page(db_session, source, POST_URL, load_fixture("blog_post_1.html"))

    outcome = parse_crawl_page(db_session, page)

    assert outcome.parsed is True
    article = outcome.article
    assert article.status is ArticleStatus.PENDING
    assert article.title == "机器学习入门"
    assert article.source_id == source.id
    assert article.summary is not None and article.summary
    assert article.crawled_at is not None
    assert article.published_at is not None


def test_parse_failure_marks_error_and_does_not_break_batch(db_session: Session) -> None:
    source = make_source(db_session)
    make_crawl_page(db_session, source, POST_URL, load_fixture("blog_post_1.html"))
    make_crawl_page(db_session, source, POST_2_URL, load_fixture("empty_page.html"))

    outcomes = parse_crawl_pages(db_session)

    assert len(outcomes) == 2
    by_url = {outcome.article.url: outcome for outcome in outcomes}
    assert by_url[POST_URL].parsed is True
    assert by_url[POST_URL].article.status is ArticleStatus.PENDING
    assert by_url[POST_2_URL].parsed is False
    assert by_url[POST_2_URL].article.status is ArticleStatus.ERROR
    assert by_url[POST_2_URL].error

    articles = db_session.scalars(select(Article)).all()
    assert len(articles) == 2


def test_parse_page_without_raw_html_marks_error(db_session: Session) -> None:
    source = make_source(db_session)
    page = make_crawl_page(db_session, source, POST_URL, None)

    outcome = parse_crawl_page(db_session, page)

    assert outcome.parsed is False
    assert outcome.article.status is ArticleStatus.ERROR
    assert outcome.error


def test_parse_is_idempotent_per_url(db_session: Session) -> None:
    source = make_source(db_session)
    page = make_crawl_page(db_session, source, POST_URL, load_fixture("blog_post_1.html"))

    parse_crawl_page(db_session, page)
    parse_crawl_page(db_session, page)

    articles = db_session.scalars(select(Article).where(Article.url == POST_URL)).all()
    assert len(articles) == 1


def test_summarize_truncates_long_content() -> None:
    short = summarize("很短的内容")
    assert short == "很短的内容"

    long_summary = summarize("字" * 500, limit=10)
    assert long_summary.endswith("…")
    assert len(long_summary) == 11
