"""来源级周期性采集调度（T17）。

读取各来源配置的更新频率，对到期的来源触发 抓取→解析→分类→去重 流水线。
重复触发依赖 T09/T13 的幂等与去重能力，不会产生脏数据。
"""

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.crawler.fetcher import Fetcher, HttpxFetcher
from app.crawler.rate_limit import RateLimiter
from app.crawler.robots import RobotFilePolicy
from app.db.base import utcnow
from app.db.enums import SourceListType
from app.db.models import Source
from app.scheduler.frequency import is_due
from app.services.pipeline_service import PipelineReport, process_source

FetcherFactory = Callable[[Source], Fetcher]


def due_sources(session: Session, *, now: datetime) -> list[Source]:
    """返回当前到期、需要抓取的来源（排除黑名单与未启用来源）。"""

    statement = select(Source).where(
        Source.is_active.is_(True),
        Source.list_type != SourceListType.BLACKLIST,
    )
    return [source for source in session.scalars(statement) if is_due(source, now=now)]


def run_due_sources(
    session: Session,
    *,
    fetcher_factory: FetcherFactory,
    now_factory: Callable[[], datetime] | None = None,
    robots: object | None = None,
    rate_limiter: RateLimiter | None = None,
) -> list[PipelineReport]:
    """对所有到期来源执行一次流水线。"""

    clock = now_factory or utcnow
    reports: list[PipelineReport] = []
    for source in due_sources(session, now=clock()):
        now = clock()
        fetcher = fetcher_factory(source)
        try:
            reports.append(
                process_source(
                    session,
                    source,
                    fetcher=fetcher,
                    robots=robots,
                    rate_limiter=rate_limiter,
                    now=now,
                )
            )
        finally:
            close = getattr(fetcher, "close", None)
            if callable(close):
                close()
    return reports


def build_fetcher_factory(settings: Settings | None = None) -> FetcherFactory:
    """构造生产环境的抓取器工厂（httpx + robots + 限流）。"""

    resolved = settings or get_settings()

    def factory(source: Source) -> Fetcher:
        return HttpxFetcher(
            user_agent=resolved.crawler_user_agent,
            timeout_seconds=resolved.crawler_timeout_seconds,
        )

    return factory


def run_scheduler_tick(
    session: Session, *, settings: Settings | None = None
) -> list[PipelineReport]:
    """调度器单次 tick：抓取所有到期来源（生产入口，供定时器调用）。"""

    resolved = settings or get_settings()
    reports: list[PipelineReport] = []

    for source in due_sources(session, now=utcnow()):
        with HttpxFetcher(
            user_agent=resolved.crawler_user_agent,
            timeout_seconds=resolved.crawler_timeout_seconds,
        ) as fetcher:
            robots = RobotFilePolicy(fetcher, user_agent=resolved.crawler_user_agent)
            rate_limiter = RateLimiter(resolved.crawler_min_interval_seconds)
            reports.append(
                process_source(
                    session,
                    source,
                    fetcher=fetcher,
                    robots=robots,
                    rate_limiter=rate_limiter,
                    max_pages=resolved.crawler_max_pages_per_run,
                )
            )
    return reports
