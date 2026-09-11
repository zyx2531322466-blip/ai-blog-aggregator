"""T12 未分类兜底与重新归类能力测试。"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ArticleStatus, CategoryStatus
from app.db.models import Article, Category
from app.services import category_service, classifier_service

ARTICLES_URL = "/api/v1/articles"


def make_article(session: Session, *, title: str, content: str, url: str) -> Article:
    article = Article(title=title, content=content, url=url, status=ArticleStatus.PENDING)
    session.add(article)
    session.flush()
    return article


def test_unmatched_article_falls_back_to_other(db_session: Session) -> None:
    category_service.ensure_default_categories(db_session)
    make_article(db_session, title="随手记事", content="今天天气不错。", url="https://x/1")
    db_session.commit()

    results = classifier_service.classify_pending_articles(db_session)

    assert len(results) == 1
    result = results[0]
    assert result.used_fallback is True
    assert result.article.status is ArticleStatus.UNCATEGORIZED
    assert result.article.primary_category is not None
    assert result.article.primary_category.name == "其他"


def test_fallback_category_is_created_when_missing(db_session: Session) -> None:
    article = make_article(db_session, title="无类别体系", content="任意内容", url="https://x/1")
    db_session.commit()

    result = classifier_service.classify_article(db_session, article, fallback=True)

    assert result.used_fallback is True
    assert result.article.primary_category.name == "其他"
    created = db_session.scalars(select(Category).where(Category.name == "其他")).one()
    assert created.status is CategoryStatus.ACTIVE


def test_uncategorized_article_is_visible_via_query_api(
    client: TestClient, api_session: Session
) -> None:
    category_service.ensure_default_categories(api_session)
    make_article(api_session, title="无法归类", content="随便写点什么。", url="https://x/1")
    api_session.commit()
    classifier_service.classify_pending_articles(api_session)

    response = client.get(ARTICLES_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "uncategorized"
    assert body["items"][0]["primary_category"]["name"] == "其他"


def test_reclassify_uncategorized_article(
    client: TestClient, admin_headers: dict[str, str], api_session: Session
) -> None:
    category_service.ensure_default_categories(api_session)
    article = make_article(
        api_session, title="无法归类", content="随便写点什么。", url="https://x/1"
    )
    api_session.commit()
    classifier_service.classify_pending_articles(api_session)
    target = category_service.find_category_by_name(api_session, "数据库")

    response = client.post(
        f"/api/v1/admin/articles/{article.id}/category",
        json={"category_id": target.id},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "normal"
    assert body["primary_category"]["name"] == "数据库"

    # 查询结果同步更新
    filtered = client.get(ARTICLES_URL, params={"category": "数据库"}).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["id"] == article.id


def test_reclassify_requires_authorization(client: TestClient, api_session: Session) -> None:
    article = make_article(api_session, title="无法归类", content="内容", url="https://x/1")
    api_session.commit()

    response = client.post(
        f"/api/v1/admin/articles/{article.id}/category", json={"category_id": "cat_x"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_reclassify_unknown_article_returns_404(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/admin/articles/article_missing/category",
        json={"category_id": "cat_x"},
        headers=admin_headers,
    )
    assert response.status_code == 404


def test_reclassify_into_inactive_category_is_rejected(
    client: TestClient, admin_headers: dict[str, str], api_session: Session
) -> None:
    category_service.ensure_default_categories(api_session)
    article = make_article(api_session, title="文章", content="内容", url="https://x/1")
    api_session.commit()

    target = category_service.find_category_by_name(api_session, "安全")
    category_service.set_category_status(
        api_session, target.id, CategoryStatus.INACTIVE, actor="tester"
    )

    response = client.post(
        f"/api/v1/admin/articles/{article.id}/category",
        json={"category_id": target.id},
        headers=admin_headers,
    )
    assert response.status_code == 422


def test_reclassify_rejects_empty_category_id(
    client: TestClient, admin_headers: dict[str, str], api_session: Session
) -> None:
    article = make_article(api_session, title="文章", content="内容", url="https://x/1")
    api_session.commit()

    response = client.post(
        f"/api/v1/admin/articles/{article.id}/category",
        json={"category_id": ""},
        headers=admin_headers,
    )
    assert response.status_code == 422
