"""种子来源（`app.scripts.seed_sources`）测试。

不访问真实网络：只校验种子数据能通过 T04 的接口校验模型，且写入逻辑幂等。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Source
from app.schemas.source import SourceCreate
from app.scripts.seed_sources import SEED_SOURCES, seed_sources


def _payload(entry) -> dict:
    return {
        "name": entry.name,
        "site_url": entry.site_url,
        "focus_area_name": entry.focus_area_name,
        "focus_area_description": entry.focus_area_description,
        "keywords": list(entry.keywords),
        "exclude_keywords": list(entry.exclude_keywords),
        "example_urls": list(entry.example_urls),
        "weight": entry.weight,
        "update_frequency": entry.update_frequency.value,
    }


def test_seed_source_urls_are_unique() -> None:
    urls = [entry.site_url for entry in SEED_SOURCES]

    assert len(urls) == len(set(urls))


def test_seed_entries_pass_source_validation() -> None:
    """每条种子都必须能通过 T04 的新增来源校验（白名单需完整的关注领域信息）。"""

    for entry in SEED_SOURCES:
        SourceCreate(**_payload(entry))


def test_seed_sources_is_idempotent(db_session: Session) -> None:
    first = seed_sources(db_session)

    assert len(first.created) == len(SEED_SOURCES)
    assert first.skipped == []
    assert db_session.scalar(select(func.count()).select_from(Source)) == len(SEED_SOURCES)

    second = seed_sources(db_session)

    assert second.created == []
    assert len(second.skipped) == len(SEED_SOURCES)
    assert db_session.scalar(select(func.count()).select_from(Source)) == len(SEED_SOURCES)


def test_seed_sources_dry_run_does_not_write(db_session: Session) -> None:
    report = seed_sources(db_session, dry_run=True)

    assert len(report.created) == len(SEED_SOURCES)
    assert db_session.scalar(select(func.count()).select_from(Source)) == 0


def test_seed_sources_keeps_existing_configuration(db_session: Session) -> None:
    """已存在的同站点配置不会被种子覆盖（保留维护者的手工调整）。"""

    existing = Source(name="自定义名字", site_url=SEED_SOURCES[0].site_url, weight=9.0)
    db_session.add(existing)
    db_session.commit()

    report = seed_sources(db_session)

    assert SEED_SOURCES[0].name in report.skipped
    db_session.refresh(existing)
    assert existing.name == "自定义名字"
    assert existing.weight == 9.0
