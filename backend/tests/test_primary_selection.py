"""T18 合并组主记录选择与展示测试。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.enums import ArticleStatus, SourceListType
from app.db.models import Article, Source
from app.dedup.primary import choose_primary, title_quality
from app.services import dedup_service, primary_selection_service, query_service

BASE_TIME = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
GROUPS_URL = "/api/v1/admin/dedup/groups"


class FakeArticle:
    """用于纯规则单元测试的轻量文章对象。"""

    def __init__(
        self,
        article_id: str,
        *,
        weight: float = 1.0,
        published_at: datetime | None = None,
        content: str = "内容",
        is_accessible: bool = True,
        title: str = "正常标题",
        created_at: datetime = BASE_TIME,
    ) -> None:
        self.id = article_id
        self.source = SimpleNamespace(weight=weight)
        self.published_at = published_at
        self.content = content
        self.is_accessible = is_accessible
        self.title = title
        self.created_at = created_at


# --- 规则单元测试 ---------------------------------------------------------------


def test_source_weight_has_highest_priority() -> None:
    low = FakeArticle("a", weight=1.0, published_at=BASE_TIME, content="很长的正文" * 5)
    high = FakeArticle("b", weight=9.0, published_at=BASE_TIME + timedelta(days=5))

    assert choose_primary([low, high]).id == "b"


def test_earliest_published_wins_when_weight_equal() -> None:
    earlier = FakeArticle("a", published_at=BASE_TIME)
    later = FakeArticle("b", published_at=BASE_TIME + timedelta(days=1))

    assert choose_primary([earlier, later]).id == "a"


def test_longer_content_wins_when_weight_and_time_equal() -> None:
    short = FakeArticle("a", content="短")
    long = FakeArticle("b", content="更完整的正文" * 10)

    assert choose_primary([short, long]).id == "b"


def test_accessible_article_wins_when_other_factors_equal() -> None:
    broken = FakeArticle("a", is_accessible=False)
    alive = FakeArticle("b", is_accessible=True)

    assert choose_primary([broken, alive]).id == "b"


def test_title_quality_is_last_priority() -> None:
    placeholder = FakeArticle("a", title="首页")
    proper = FakeArticle("b", title="一篇内容完整的文章标题")

    assert title_quality("首页") < title_quality("一篇内容完整的文章标题")
    assert choose_primary([placeholder, proper]).id == "b"


def test_choose_primary_rejects_empty_group() -> None:
    with pytest.raises(ValueError):
        choose_primary([])


# --- 与数据库/合并流程集成 --------------------------------------------------------


def _make_source(session: Session, url: str, weight: float) -> Source:
    source = Source(name=url, site_url=url, list_type=SourceListType.WHITELIST, weight=weight)
    session.add(source)
    session.flush()
    return source


def _make_article(
    session: Session, source: Source, *, url: str, content: str, created_at: datetime, title: str
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


def test_merge_primary_follows_weight_over_recency(db_session: Session) -> None:
    low = _make_source(db_session, "https://low.example", weight=1.0)
    high = _make_source(db_session, "https://high.example", weight=9.0)
    content = "完全相同的正文内容，用于触发完全重复合并。" * 3

    first = _make_article(
        db_session,
        low,
        url="https://low.example/a",
        content=content,
        created_at=BASE_TIME,
        title="原文章",
    )
    second = _make_article(
        db_session,
        high,
        url="https://high.example/b",
        content=content,
        created_at=BASE_TIME + timedelta(hours=1),
        title="转载文章",
    )

    dedup_service.process_article(db_session, first)
    dedup_service.process_article(db_session, second)

    group_key = primary_selection_service.group_key_for_article(db_session, first.id)
    assert group_key is not None
    # 权重更高的来源胜出（即便发布时间更晚）
    assert primary_selection_service.current_primary_id(db_session, group_key) == second.id

    detail = query_service.get_article_detail(db_session, first.id)
    assert detail.id == second.id
    assert len(detail.sources) == 2
    primary_urls = {source.url for source in detail.sources if source.is_primary}
    assert primary_urls == {"https://high.example/b"}


def test_inaccessible_primary_triggers_switch(db_session: Session) -> None:
    source_a = _make_source(db_session, "https://a.example", weight=1.0)
    source_b = _make_source(db_session, "https://b.example", weight=1.0)
    content = "完全相同的正文内容，用于触发完全重复合并。" * 3

    first = _make_article(
        db_session,
        source_a,
        url="https://a.example/a",
        content=content,
        created_at=BASE_TIME,
        title="一篇完整的原文章标题",
    )
    second = _make_article(
        db_session,
        source_b,
        url="https://b.example/b",
        content=content,
        created_at=BASE_TIME + timedelta(hours=1),
        title="转载",
    )

    dedup_service.process_article(db_session, first)
    dedup_service.process_article(db_session, second)
    group_key = primary_selection_service.group_key_for_article(db_session, first.id)
    assert group_key is not None
    assert primary_selection_service.current_primary_id(db_session, group_key) == first.id

    # 主记录原文不可访问 → 切换到组内其他有效来源
    primary_selection_service.mark_article_inaccessible(db_session, first.id)
    db_session.commit()
    result = primary_selection_service.select_and_apply_primary(db_session, group_key)

    assert result is not None and result.changed is True
    assert result.primary_id == second.id
    assert primary_selection_service.current_primary_id(db_session, group_key) == second.id

    detail = query_service.get_article_detail(db_session, second.id)
    primary_flags = {source.url: source.is_primary for source in detail.sources}
    assert primary_flags["https://b.example/b"] is True


def test_detail_shows_all_sources_regression(db_session: Session) -> None:
    source_a = _make_source(db_session, "https://a.example", weight=1.0)
    source_b = _make_source(db_session, "https://b.example", weight=1.0)
    content = "相同正文" * 20

    first = _make_article(
        db_session,
        source_a,
        url="https://a.example/a",
        content=content,
        created_at=BASE_TIME,
        title="标题A",
    )
    second = _make_article(
        db_session,
        source_b,
        url="https://b.example/b",
        content=content,
        created_at=BASE_TIME + timedelta(hours=1),
        title="标题B",
    )
    dedup_service.process_article(db_session, first)
    dedup_service.process_article(db_session, second)

    detail = query_service.get_article_detail(db_session, first.id)
    assert {source.url for source in detail.sources} == {
        "https://a.example/a",
        "https://b.example/b",
    }


# --- API 层 ---------------------------------------------------------------------


def test_admin_groups_and_refresh_api(
    client: TestClient, admin_headers: dict[str, str], api_session: Session
) -> None:
    source_a = _make_source(api_session, "https://a.example", weight=1.0)
    source_b = _make_source(api_session, "https://b.example", weight=1.0)
    content = "相同正文内容用于合并。" * 5
    first = _make_article(
        api_session,
        source_a,
        url="https://a.example/a",
        content=content,
        created_at=BASE_TIME,
        title="标题A",
    )
    second = _make_article(
        api_session,
        source_b,
        url="https://b.example/b",
        content=content,
        created_at=BASE_TIME + timedelta(hours=1),
        title="标题B",
    )
    api_session.commit()
    dedup_service.process_article(api_session, first)
    dedup_service.process_article(api_session, second)

    groups = client.get(GROUPS_URL, headers=admin_headers)
    assert groups.status_code == 200
    body = groups.json()
    assert body["total"] == 1
    group = body["items"][0]
    assert group["primary_id"] == first.id
    assert len(group["members"]) == 2
    assert sum(1 for member in group["members"] if member["is_primary"]) == 1

    refreshed = client.post(f"{GROUPS_URL}/refresh", headers=admin_headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["refreshed"] == 1
    assert refreshed.json()["changed"] == 0


def test_admin_inaccessible_switches_primary_api(
    client: TestClient, admin_headers: dict[str, str], api_session: Session
) -> None:
    source_a = _make_source(api_session, "https://a.example", weight=1.0)
    source_b = _make_source(api_session, "https://b.example", weight=1.0)
    content = "相同正文内容用于合并。" * 5
    first = _make_article(
        api_session,
        source_a,
        url="https://a.example/a",
        content=content,
        created_at=BASE_TIME,
        title="标题A",
    )
    second = _make_article(
        api_session,
        source_b,
        url="https://b.example/b",
        content=content,
        created_at=BASE_TIME + timedelta(hours=1),
        title="标题B",
    )
    api_session.commit()
    dedup_service.process_article(api_session, first)
    dedup_service.process_article(api_session, second)

    response = client.post(f"/api/v1/admin/articles/{first.id}/inaccessible", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["is_accessible"] is False
    assert body["group_refreshed"] is True
    assert body["changed"] is True
    assert body["primary_id"] == second.id


def test_primary_admin_endpoints_require_authorization(client: TestClient) -> None:
    assert client.get(GROUPS_URL).status_code == 401
    assert client.post(f"{GROUPS_URL}/refresh").status_code == 401
    assert client.post(f"{GROUPS_URL}/group_x/refresh").status_code == 401
