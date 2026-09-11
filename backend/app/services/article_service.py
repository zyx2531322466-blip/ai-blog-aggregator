"""解析结果落库服务（T06 / T16）。

将 T05 保存的原始页面解析为文章记录：
- 成功：写入标题/正文/发布时间/作者，状态置为"待分类"（pending）；
- 低质量/不相关（T16）：状态置为"已过滤"（filtered），不进入分类流程；
- 失败：状态置为"异常"（error），并保留记录，不中断整体流程。
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ArticleStatus, CrawlStatus
from app.db.models import Article, CrawlPage, Source
from app.filtering import evaluate_quality
from app.parser.html_parser import ParseError, ParsedArticle, parse_html

Parser = Callable[[str, str], ParsedArticle]

SUMMARY_LENGTH = 200


@dataclass
class ParseOutcome:
    """单页解析结果。"""

    article: Article
    parsed: bool
    error: str | None = None
    filtered: bool = False
    filter_reason: str | None = None


def summarize(content: str, limit: int = SUMMARY_LENGTH) -> str:
    """从正文生成摘要（按字符截断，统一空白）。"""

    flattened = " ".join(content.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[:limit].rstrip() + "…"


def parse_crawl_page(
    session: Session,
    page: CrawlPage,
    *,
    parser: Parser = parse_html,
) -> ParseOutcome:
    """解析单个抓取页面并写入文章表（按 URL 幂等）。"""

    article = session.scalars(select(Article).where(Article.url == page.url)).first()
    if article is None:
        article = Article(url=page.url, title=page.url, content="", status=ArticleStatus.ERROR)
        session.add(article)

    article.source_id = page.source_id
    article.crawled_at = page.fetched_at

    if not page.raw_html:
        article.status = ArticleStatus.ERROR
        session.commit()
        session.refresh(article)
        return ParseOutcome(article=article, parsed=False, error="缺少原始 HTML")

    try:
        parsed = parser(page.raw_html, page.url)
    except ParseError as exc:
        article.status = ArticleStatus.ERROR
        session.commit()
        session.refresh(article)
        return ParseOutcome(article=article, parsed=False, error=str(exc))

    article.title = parsed.title
    article.content = parsed.content
    article.summary = summarize(parsed.content)
    article.published_at = parsed.published_at
    article.author = parsed.author

    decision = evaluate_quality(
        title=parsed.title,
        content=parsed.content,
        raw_html=page.raw_html,
        exclude_keywords=_exclude_keywords(session, page.source_id),
    )
    if decision.filtered:
        article.status = ArticleStatus.FILTERED
        session.commit()
        session.refresh(article)
        return ParseOutcome(
            article=article,
            parsed=True,
            filtered=True,
            filter_reason=decision.reason,
        )

    article.status = ArticleStatus.PENDING
    session.commit()
    session.refresh(article)
    return ParseOutcome(article=article, parsed=True)


def parse_crawl_pages(session: Session, *, source_id: str | None = None) -> list[ParseOutcome]:
    """批量解析已成功抓取但尚未处理的页面。"""

    statement = select(CrawlPage).where(CrawlPage.status == CrawlStatus.FETCHED)
    if source_id is not None:
        statement = statement.where(CrawlPage.source_id == source_id)
    statement = statement.order_by(CrawlPage.fetched_at)

    return [parse_crawl_page(session, page) for page in session.scalars(statement)]


def _exclude_keywords(session: Session, source_id: str | None) -> list[str]:
    if not source_id:
        return []
    source = session.get(Source, source_id)
    if source is None or not source.exclude_keywords:
        return []
    return list(source.exclude_keywords)
