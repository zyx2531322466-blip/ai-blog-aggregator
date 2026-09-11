"""抓取 → 解析 → 过滤 → 分类 → 去重 的流水线编排（T17 / T21）。

单个来源的一次处理流程；调度器（T17）与端到端验收（T21）都复用本模块。
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.crawler.fetcher import Fetcher
from app.crawler.rate_limit import RateLimiter
from app.crawler.robots import RobotsChecker
from app.crawler.service import CrawlReport, crawl_source
from app.db.models import Source
from app.services import classifier_service, dedup_service
from app.services.article_service import parse_crawl_pages


@dataclass
class PipelineReport:
    """一次来源级流水线的统计结果。"""

    source_id: str
    crawl: CrawlReport
    parsed: int = 0
    filtered: int = 0
    classified: int = 0
    merged: int = 0
    related: int = 0


def process_source(
    session: Session,
    source: Source,
    *,
    fetcher: Fetcher,
    robots: RobotsChecker | None = None,
    rate_limiter: RateLimiter | None = None,
    article_urls: list[str] | None = None,
    max_pages: int | None = None,
    now: datetime | None = None,
) -> PipelineReport:
    """处理单个来源：抓取 → 解析/过滤 → 分类 → 去重。"""

    crawl = crawl_source(
        session,
        source,
        fetcher=fetcher,
        robots=robots,
        rate_limiter=rate_limiter,
        article_urls=article_urls,
        max_pages=max_pages,
        now=(lambda: now) if now is not None else None,
    )

    outcomes = parse_crawl_pages(session, source_id=source.id)
    parsed = sum(1 for outcome in outcomes if outcome.parsed and not outcome.filtered)
    filtered = sum(1 for outcome in outcomes if outcome.filtered)

    classifications = classifier_service.classify_pending_articles(session, source_id=source.id)

    merged = 0
    related = 0
    for outcome in outcomes:
        if not outcome.parsed or outcome.filtered:
            continue
        result = dedup_service.process_article(session, outcome.article)
        if result.is_duplicate:
            merged += 1
        elif result.related_article is not None:
            related += 1

    return PipelineReport(
        source_id=source.id,
        crawl=crawl,
        parsed=parsed,
        filtered=filtered,
        classified=len(classifications),
        merged=merged,
        related=related,
    )
