"""T16 低质量/不相关内容过滤测试。"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ArticleStatus, CrawlStatus, SourceListType
from app.db.models import Article, CrawlPage, Source
from app.filtering import evaluate_quality, is_entry_page, link_text_ratio
from app.services import classifier_service
from app.services.article_service import parse_crawl_page, parse_crawl_pages
from tests.fakes import load_fixture

FIXED_TIME = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def make_source(session: Session, **overrides: object) -> Source:
    defaults: dict[str, object] = {
        "name": "示例博客",
        "site_url": "https://blog.example.com/",
        "list_type": SourceListType.WHITELIST,
    }
    defaults.update(overrides)
    source = Source(**defaults)  # type: ignore[arg-type]
    session.add(source)
    session.flush()
    return source


def make_page(session: Session, source: Source, url: str, html: str) -> CrawlPage:
    page = CrawlPage(
        source_id=source.id,
        url=url,
        raw_html=html,
        http_status=200,
        status=CrawlStatus.FETCHED,
        fetched_at=FIXED_TIME,
    )
    session.add(page)
    session.flush()
    return page


# --- 判定单元测试 ---------------------------------------------------------------


def test_short_content_is_filtered() -> None:
    assert evaluate_quality(title="x", content="短").filtered is True


def test_ad_page_is_filtered() -> None:
    decision = evaluate_quality(
        title="限时优惠",
        content="立即购买即可享受折扣，点击购买还有礼品，扫码关注领取优惠。",
    )
    assert decision.filtered is True
    assert "广告" in (decision.reason or "")


def test_exclude_keyword_hit_is_filtered() -> None:
    decision = evaluate_quality(
        title="正常标题",
        content="这是一段正常长度的正文内容，但包含招聘信息。",
        exclude_keywords=["招聘"],
    )
    assert decision.filtered is True
    assert "排除词" in (decision.reason or "")


def test_is_entry_page_ignores_scheme_and_trailing_slash() -> None:
    assert is_entry_page("https://blog.example.com/", "https://blog.example.com") is True
    assert is_entry_page("http://blog.example.com/", "https://blog.example.com/") is True
    assert is_entry_page("https://blog.example.com/posts/1", "https://blog.example.com/") is False
    assert is_entry_page("https://other.example.com/", "https://blog.example.com/") is False
    assert is_entry_page("", "https://blog.example.com/") is False


def test_source_entry_page_is_not_stored_as_article(db_session: Session) -> None:
    """站点首页（入口页）只用于发现文章链接，本身不应进入正式文章表。"""

    source = make_source(db_session)
    homepage = (
        "<html><head><title>示例博客</title></head><body><article><h1>示例博客</h1>"
        "<p>这是站点首页的长正文，用于验证入口页不会被当作文章入库。</p>"
        "</article></body></html>"
    )
    page = make_page(db_session, source, "https://blog.example.com/", homepage)

    outcome = parse_crawl_page(db_session, page)

    assert outcome.filtered is True
    assert outcome.article.status is ArticleStatus.FILTERED
    assert "入口页" in (outcome.filter_reason or "")


def test_article_subpage_is_not_treated_as_entry_page(db_session: Session) -> None:
    source = make_source(db_session)
    page = make_page(
        db_session, source, "https://blog.example.com/posts/1", load_fixture("blog_post_1.html")
    )

    outcome = parse_crawl_page(db_session, page)

    assert outcome.filtered is False
    assert outcome.article.status is ArticleStatus.PENDING


def test_high_link_density_is_filtered() -> None:
    html = (
        "<html><body><main>"
        + "".join(f'<a href="/p/{index}">栏目{index}</a>' for index in range(10))
        + "</main></body></html>"
    )
    assert link_text_ratio(html) >= 0.5
    decision = evaluate_quality(title="某站", content="栏目0 栏目1 栏目2 栏目3", raw_html=html)
    assert decision.filtered is True


def test_normal_content_is_not_filtered() -> None:
    decision = evaluate_quality(
        title="机器学习入门",
        content="这是第一篇关于机器学习的文章正文，介绍基本概念与常见算法。",
        raw_html=load_fixture("blog_post_1.html"),
    )
    assert decision.filtered is False


# --- 解析流程集成 ---------------------------------------------------------------


def test_ad_page_does_not_enter_formal_article_flow(db_session: Session) -> None:
    source = make_source(db_session)
    page = make_page(
        db_session, source, "https://blog.example.com/ad", load_fixture("ad_page.html")
    )

    outcome = parse_crawl_page(db_session, page)

    assert outcome.filtered is True
    assert outcome.article.status is ArticleStatus.FILTERED
    assert outcome.filter_reason


def test_nav_page_is_filtered(db_session: Session) -> None:
    source = make_source(db_session)
    page = make_page(
        db_session, source, "https://blog.example.com/nav", load_fixture("nav_page.html")
    )

    outcome = parse_crawl_page(db_session, page)

    assert outcome.filtered is True
    assert outcome.article.status is ArticleStatus.FILTERED


def test_exclude_keyword_from_source_filters_content(db_session: Session) -> None:
    source = make_source(db_session, exclude_keywords=["机器学习"])
    page = make_page(
        db_session, source, "https://blog.example.com/1", load_fixture("blog_post_1.html")
    )

    outcome = parse_crawl_page(db_session, page)

    assert outcome.filtered is True
    assert "排除词" in (outcome.filter_reason or "")


def test_normal_article_still_enters_classification(db_session: Session) -> None:
    source = make_source(db_session)
    page = make_page(
        db_session, source, "https://blog.example.com/1", load_fixture("blog_post_1.html")
    )

    outcome = parse_crawl_page(db_session, page)

    assert outcome.filtered is False
    assert outcome.article.status is ArticleStatus.PENDING


def test_filtered_articles_are_skipped_by_classification(db_session: Session) -> None:
    source = make_source(db_session)
    make_page(db_session, source, "https://blog.example.com/ad", load_fixture("ad_page.html"))
    normal_page = make_page(
        db_session, source, "https://blog.example.com/1", load_fixture("blog_post_1.html")
    )
    db_session.commit()
    outcomes = parse_crawl_pages(db_session)
    assert len(outcomes) == 2

    from app.services import category_service

    category_service.ensure_default_categories(db_session)
    results = classifier_service.classify_pending_articles(db_session)

    # 只应处理未被过滤的正常文章
    assert len(results) == 1
    assert results[0].article.url == normal_page.url
    filtered_article = db_session.scalars(
        select(Article).where(Article.url == "https://blog.example.com/ad")
    ).one()
    assert filtered_article.status is ArticleStatus.FILTERED


def test_filtered_articles_are_not_listed(client: TestClient, api_session: Session) -> None:
    source = make_source(api_session)
    make_page(api_session, source, "https://blog.example.com/ad", load_fixture("ad_page.html"))
    make_page(api_session, source, "https://blog.example.com/1", load_fixture("blog_post_1.html"))
    api_session.commit()
    parse_crawl_pages(api_session)

    listing = client.get("/api/v1/articles").json()
    assert listing["total"] == 1
    assert listing["items"][0]["title"] == "机器学习入门"


def test_unparseable_entry_page_is_filtered_not_error(db_session: Session) -> None:
    """入口页即使无法解析（内容过短/无 HTML），也应标记为 filtered 而不是 error。"""

    source = make_source(db_session)
    page = make_page(
        db_session, source, "https://blog.example.com/", "<html><body><p>短</p></body></html>"
    )

    outcome = parse_crawl_page(db_session, page)
    assert outcome.filtered is True
    assert outcome.article.status is ArticleStatus.FILTERED
    assert "入口页" in (outcome.filter_reason or "")

    # 同一入口页没有原始 HTML 时同样应被过滤，而不是变成 error
    page.raw_html = ""
    db_session.commit()
    outcome = parse_crawl_page(db_session, page)
    assert outcome.filtered is True
    assert outcome.article.status is ArticleStatus.FILTERED


def test_parse_error_articles_are_not_listed(client: TestClient, api_session: Session) -> None:
    """解析失败（error）的记录保留在库中，但不出现在公开列表里。"""

    source = make_source(api_session)
    api_session.add_all(
        [
            Article(
                title="https://blog.example.com/broken",
                content="",
                url="https://blog.example.com/broken",
                source_id=source.id,
                status=ArticleStatus.ERROR,
            ),
            Article(
                title="正常文章",
                content="正文内容",
                url="https://blog.example.com/ok",
                source_id=source.id,
                status=ArticleStatus.NORMAL,
            ),
        ]
    )
    api_session.commit()

    listing = client.get("/api/v1/articles").json()

    assert listing["total"] == 1
    assert listing["items"][0]["title"] == "正常文章"
