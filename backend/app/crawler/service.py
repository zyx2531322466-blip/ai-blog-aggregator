"""单站点抓取编排（T05）。

职责：
- 依据白名单发起抓取，黑名单站点直接跳过；
- 遵守 robots.txt 与按主机限流；
- 保存原始 HTML 与元信息（原始来源地址、HTTP 状态、抓取时间、失败原因）；
- 单个 URL 抓取失败不影响整体流程（失败被记录而非抛出）。
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawler.discovery import discover_article_urls
from app.crawler.fetcher import FetchResult, Fetcher
from app.crawler.rate_limit import RateLimiter
from app.crawler.robots import AllowAllRobots, RobotsChecker
from app.db.base import utcnow
from app.db.enums import CrawlStatus, SourceListType
from app.db.models import CrawlPage, Source

DEFAULT_MAX_PAGES = 20


@dataclass
class CrawlReport:
    """一次抓取的统计结果。"""

    source_id: str
    skipped: bool = False
    skip_reason: str | None = None
    fetched: int = 0
    failed: int = 0
    robots_denied: int = 0
    urls: list[str] = field(default_factory=list)


@dataclass
class _PageOutcome:
    url: str
    status: CrawlStatus
    result: FetchResult | None = None


def crawl_source(
    session: Session,
    source: Source,
    *,
    fetcher: Fetcher,
    robots: RobotsChecker | None = None,
    rate_limiter: RateLimiter | None = None,
    article_urls: Iterable[str] | None = None,
    max_pages: int | None = None,
    now: Callable[[], datetime] | None = None,
) -> CrawlReport:
    """抓取单个来源。

    ``article_urls`` 为 ``None`` 时，先抓取站点首页并从中发现候选链接；
    显式传入时则直接抓取给定链接（便于调度与测试）。
    """

    robots = robots or AllowAllRobots()
    rate_limiter = rate_limiter or RateLimiter(0.0)
    now_fn = now or utcnow
    limit = max_pages if max_pages is not None else DEFAULT_MAX_PAGES

    if source.list_type is SourceListType.BLACKLIST:
        return CrawlReport(source_id=source.id, skipped=True, skip_reason="blacklist")
    if not source.is_active:
        return CrawlReport(source_id=source.id, skipped=True, skip_reason="inactive")

    report = CrawlReport(source_id=source.id)

    if article_urls is None:
        index_outcome = _fetch_page(
            session, source, source.site_url, fetcher, robots, rate_limiter, now_fn
        )
        report.urls.append(index_outcome.url)
        if index_outcome.status is CrawlStatus.ROBOTS_DENIED:
            report.robots_denied += 1
            _finalize(session, source, report, now_fn)
            return report
        if index_outcome.status is CrawlStatus.FAILED:
            report.failed += 1
            _finalize(session, source, report, now_fn)
            return report

        report.fetched += 1
        html = (index_outcome.result.text if index_outcome.result else "") or ""
        candidates = discover_article_urls(html, source.site_url, limit=limit)
    else:
        candidates = list(dict.fromkeys(article_urls))

    for url in candidates[:limit]:
        outcome = _fetch_page(session, source, url, fetcher, robots, rate_limiter, now_fn)
        report.urls.append(url)
        if outcome.status is CrawlStatus.FETCHED:
            report.fetched += 1
        elif outcome.status is CrawlStatus.FAILED:
            report.failed += 1
        else:
            report.robots_denied += 1

    _finalize(session, source, report, now_fn)
    return report


def _fetch_page(
    session: Session,
    source: Source,
    url: str,
    fetcher: Fetcher,
    robots: RobotsChecker,
    rate_limiter: RateLimiter,
    now_fn: Callable[[], datetime],
) -> _PageOutcome:
    """抓取单个页面并写入待处理表，任何失败都转为状态而非异常。"""

    if not robots.can_fetch(url):
        _upsert_page(session, source, url, status=CrawlStatus.ROBOTS_DENIED, fetched_at=now_fn())
        return _PageOutcome(url=url, status=CrawlStatus.ROBOTS_DENIED)

    rate_limiter.wait(url)
    try:
        result = fetcher.fetch(url)
    except Exception as exc:  # noqa: BLE001 - 抓取失败不允许中断整体流程
        result = FetchResult(url=url, status_code=None, text=None, error=str(exc))

    if result.ok:
        _upsert_page(
            session,
            source,
            url,
            status=CrawlStatus.FETCHED,
            raw_html=result.text,
            http_status=result.status_code,
            fetched_at=now_fn(),
        )
        return _PageOutcome(url=url, status=CrawlStatus.FETCHED, result=result)

    _upsert_page(
        session,
        source,
        url,
        status=CrawlStatus.FAILED,
        http_status=result.status_code,
        error_message=result.error or f"HTTP {result.status_code}",
        fetched_at=now_fn(),
    )
    return _PageOutcome(url=url, status=CrawlStatus.FAILED, result=result)


def _upsert_page(
    session: Session,
    source: Source,
    url: str,
    *,
    status: CrawlStatus,
    raw_html: str | None = None,
    http_status: int | None = None,
    error_message: str | None = None,
    fetched_at: datetime,
) -> CrawlPage:
    """按 (source_id, url) 幂等写入，重复抓取不会产生脏数据。"""

    page = session.scalars(
        select(CrawlPage).where(CrawlPage.source_id == source.id, CrawlPage.url == url)
    ).first()
    if page is None:
        page = CrawlPage(source_id=source.id, url=url)
        session.add(page)
    page.status = status
    page.raw_html = raw_html
    page.http_status = http_status
    page.error_message = error_message
    page.fetched_at = fetched_at
    session.flush()
    return page


def _finalize(
    session: Session,
    source: Source,
    report: CrawlReport,
    now_fn: Callable[[], datetime],
) -> None:
    source.last_crawled_at = now_fn()
    if report.fetched > 0:
        source.last_success_at = source.last_crawled_at
    session.commit()
