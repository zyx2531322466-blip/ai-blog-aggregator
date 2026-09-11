"""T10 文章查询与浏览接口测试。"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ArticleStatus, SourceListType
from app.db.models import Article, Source, Tag
from app.services import category_service, dedup_service

ARTICLES_URL = "/api/v1/articles"


def _get_tag(session: Session, name: str) -> Tag:
    tag = session.scalars(select(Tag).where(Tag.name == name)).first()
    if tag is None:
        tag = Tag(name=name)
        session.add(tag)
        session.flush()
    return tag


def _make_article(
    session: Session,
    *,
    title: str,
    content: str,
    url: str,
    source: Source,
    category=None,
    tags: tuple[str, ...] = (),
    published_at: datetime | None = None,
    status: ArticleStatus = ArticleStatus.NORMAL,
) -> Article:
    article = Article(
        title=title,
        content=content,
        summary=content[:50],
        url=url,
        source_id=source.id,
        primary_category_id=category.id if category is not None else None,
        published_at=published_at,
        status=status,
    )
    article.tags = [_get_tag(session, name) for name in tags]
    session.add(article)
    session.flush()
    return article


@pytest.fixture()
def browsing_data(api_session: Session) -> SimpleNamespace:
    """构造：3 篇正常文章 + 1 篇完全重复（合并），覆盖各筛选维度。"""

    category_service.ensure_default_categories(api_session)
    ai = category_service.find_category_by_name(api_session, "AI/机器学习")
    db_cat = category_service.find_category_by_name(api_session, "数据库")
    web = category_service.find_category_by_name(api_session, "Web 开发")

    source_a = Source(
        name="站点A", site_url="https://a.example.com", list_type=SourceListType.WHITELIST
    )
    source_b = Source(
        name="站点B", site_url="https://b.example.com", list_type=SourceListType.WHITELIST
    )
    api_session.add_all([source_a, source_b])
    api_session.flush()

    art_ml = _make_article(
        api_session,
        title="机器学习入门",
        content="机器学习与神经网络的正文内容。",
        url="https://a.example.com/ml",
        source=source_a,
        category=ai,
        tags=("机器学习",),
        published_at=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
    )
    art_sql = _make_article(
        api_session,
        title="SQL 查询优化",
        content="数据库索引与事务的正文内容。",
        url="https://b.example.com/sql",
        source=source_b,
        category=db_cat,
        tags=("数据库",),
        published_at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
    )
    art_web = _make_article(
        api_session,
        title="React 前端实践",
        content="使用 React 与 TypeScript 构建前端界面。",
        url="https://a.example.com/react",
        source=source_a,
        category=web,
        tags=("前端", "Web 开发"),
        published_at=datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc),
    )
    duplicate = _make_article(
        api_session,
        title="React 前端实践",
        content="使用 React 与 TypeScript 构建前端界面。",
        url="https://b.example.com/react-copy",
        source=source_b,
        category=web,
        tags=("前端",),
        published_at=datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc),
    )
    api_session.commit()

    dedup_service.process_article(api_session, art_web)
    dedup_service.process_article(api_session, duplicate)

    return SimpleNamespace(
        article_ids=[art_ml.id, art_sql.id, art_web.id],
        duplicate_id=duplicate.id,
        primary_id=art_web.id,
        source_a_id=source_a.id,
        source_b_id=source_b.id,
        category_db_id=db_cat.id,
    )


def test_list_is_public_and_returns_items(
    client: TestClient, browsing_data: SimpleNamespace
) -> None:
    response = client.get(ARTICLES_URL)
    assert response.status_code == 200
    body = response.json()
    # 合并组只展示一条（重复记录被隐藏）
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert len(body["items"]) == 3

    item = next(entry for entry in body["items"] if entry["id"] == browsing_data.primary_id)
    assert item["title"] == "React 前端实践"
    assert item["primary_category"]["name"] == "Web 开发"
    assert "前端" in item["tags"]
    assert item["primary_source"]["name"] == "站点A"
    assert item["sources_count"] == 2
    assert item["merged_sources_count"] == 1


def test_filter_by_category(client: TestClient, browsing_data: SimpleNamespace) -> None:
    response = client.get(ARTICLES_URL, params={"category": "数据库"})
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "SQL 查询优化"

    by_id = client.get(ARTICLES_URL, params={"category": browsing_data.category_db_id}).json()
    assert by_id["total"] == 1


def test_filter_by_tag(client: TestClient, browsing_data: SimpleNamespace) -> None:
    body = client.get(ARTICLES_URL, params={"tag": "前端"}).json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == browsing_data.primary_id


def test_filter_by_source_id_and_name(client: TestClient, browsing_data: SimpleNamespace) -> None:
    by_id = client.get(ARTICLES_URL, params={"source": browsing_data.source_a_id}).json()
    assert by_id["total"] == 2

    by_name = client.get(ARTICLES_URL, params={"source": "站点B"}).json()
    assert by_name["total"] == 1
    assert by_name["items"][0]["title"] == "SQL 查询优化"


def test_filter_by_date_range(client: TestClient, browsing_data: SimpleNamespace) -> None:
    body = client.get(
        ARTICLES_URL,
        params={"start_date": "2026-09-04T00:00:00Z", "end_date": "2026-09-06T00:00:00Z"},
    ).json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "SQL 查询优化"


def test_pagination(client: TestClient, browsing_data: SimpleNamespace) -> None:
    first = client.get(ARTICLES_URL, params={"page": 1, "page_size": 2}).json()
    assert first["total"] == 3
    assert len(first["items"]) == 2

    second = client.get(ARTICLES_URL, params={"page": 2, "page_size": 2}).json()
    assert len(second["items"]) == 1
    assert {item["id"] for item in first["items"]} & {
        item["id"] for item in second["items"]
    } == set()


def test_detail_of_merged_article_returns_all_sources(
    client: TestClient, browsing_data: SimpleNamespace
) -> None:
    response = client.get(f"{ARTICLES_URL}/{browsing_data.primary_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == browsing_data.primary_id
    assert len(body["sources"]) == 2
    urls = {source["url"] for source in body["sources"]}
    assert urls == {"https://a.example.com/react", "https://b.example.com/react-copy"}
    assert sum(1 for source in body["sources"] if source["is_primary"]) == 1
    assert {source["name"] for source in body["sources"]} == {"站点A", "站点B"}


def test_detail_via_duplicate_member_id_resolves_group(
    client: TestClient, browsing_data: SimpleNamespace
) -> None:
    response = client.get(f"{ARTICLES_URL}/{browsing_data.duplicate_id}")
    assert response.status_code == 200
    body = response.json()
    # 请求重复记录时，返回其合并组的主记录与全部来源
    assert body["id"] == browsing_data.primary_id
    assert len(body["sources"]) == 2


def test_detail_of_single_article_has_one_source(
    client: TestClient, browsing_data: SimpleNamespace
) -> None:
    response = client.get(f"{ARTICLES_URL}/{browsing_data.article_ids[0]}")
    body = response.json()
    assert len(body["sources"]) == 1
    assert body["sources"][0]["is_primary"] is True


def test_detail_unknown_article_returns_404(client: TestClient) -> None:
    response = client.get(f"{ARTICLES_URL}/article_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_invalid_pagination_is_rejected(client: TestClient) -> None:
    assert client.get(ARTICLES_URL, params={"page": 0}).status_code == 422
    assert client.get(ARTICLES_URL, params={"page_size": 1000}).status_code == 422


def test_public_categories_endpoint_returns_counts(
    client: TestClient, browsing_data: SimpleNamespace
) -> None:
    response = client.get("/api/v1/categories")
    assert response.status_code == 200
    categories = {item["name"]: item["article_count"] for item in response.json()["categories"]}
    assert categories["数据库"] == 1
    assert categories["Web 开发"] == 1  # 合并组只计一条
    assert "其他" in categories
