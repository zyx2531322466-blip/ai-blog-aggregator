"""T19 内容新鲜度信息接口测试（后端部分）。"""

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.enums import ArticleStatus, SourceListType
from app.db.models import Article, Source

SOURCES_URL = "/api/v1/sources"
FIXED_TIME = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def _source(session: Session, name: str, url: str, **overrides: object) -> Source:
    defaults: dict[str, object] = {
        "name": name,
        "site_url": url,
        "list_type": SourceListType.WHITELIST,
    }
    defaults.update(overrides)
    source = Source(**defaults)  # type: ignore[arg-type]
    session.add(source)
    session.flush()
    return source


def test_public_sources_endpoint_exposes_last_update(
    client: TestClient, api_session: Session
) -> None:
    _source(
        api_session,
        "站点A",
        "https://a.example",
        last_success_at=FIXED_TIME,
        last_crawled_at=FIXED_TIME,
    )
    api_session.commit()

    response = client.get(SOURCES_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["name"] == "站点A"
    assert item["last_success_at"] is not None
    assert item["last_crawled_at"] is not None
    # 计划更新频率默认不对外展示
    assert "update_frequency" not in item


def test_inactive_source_not_listed(client: TestClient, api_session: Session) -> None:
    _source(api_session, "已停用", "https://inactive.example", is_active=False)
    _source(api_session, "启用中", "https://active.example")
    api_session.commit()

    items = client.get(SOURCES_URL).json()["items"]
    assert [item["name"] for item in items] == ["启用中"]


def test_article_detail_exposes_both_timestamps(client: TestClient, api_session: Session) -> None:
    source = _source(api_session, "站点A", "https://a.example")
    article = Article(
        title="文章",
        content="正文内容",
        url="https://a.example/1",
        source_id=source.id,
        status=ArticleStatus.NORMAL,
        published_at=FIXED_TIME,
        crawled_at=FIXED_TIME,
    )
    api_session.add(article)
    api_session.commit()

    detail = client.get(f"/api/v1/articles/{article.id}").json()
    assert detail["published_at"] is not None
    assert detail["crawled_at"] is not None
