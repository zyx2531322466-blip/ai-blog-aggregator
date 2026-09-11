"""T07 受控类别管理测试。"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.enums import ArticleStatus, CategoryAction, CategoryStatus
from app.db.models import Article, Category, CategoryHistory
from app.services import category_service

CATEGORIES_URL = "/api/v1/admin/categories"


def make_category(session: Session, name: str) -> Category:
    category = Category(name=name)
    session.add(category)
    session.flush()
    return category


def make_article(session: Session, url: str, category: Category) -> Article:
    article = Article(
        title="文章",
        content="正文" * 20,
        url=url,
        primary_category_id=category.id,
        status=ArticleStatus.NORMAL,
    )
    session.add(article)
    session.flush()
    return article


# --- 服务层 -------------------------------------------------------------------


def test_default_categories_are_seeded(db_session: Session) -> None:
    categories = category_service.ensure_default_categories(db_session)

    names = [category.name for category in categories]
    assert set(names) == set(category_service.DEFAULT_CATEGORIES)
    assert len(names) == 7
    assert all(category.is_default for category in categories)
    assert all(category.status is CategoryStatus.ACTIVE for category in categories)


def test_seeding_is_idempotent_and_respects_renames(db_session: Session) -> None:
    seeded = category_service.ensure_default_categories(db_session)
    other = next(category for category in seeded if category.name == "其他")

    category_service.rename_category(db_session, other.id, "未分类区", actor="tester")
    category_service.ensure_default_categories(db_session)

    names = [category.name for category in category_service.list_categories(db_session)]
    assert len(names) == 7  # 不会因为重命名而重新补种
    assert "未分类区" in names
    assert "其他" not in names


def test_create_category_and_duplicate_conflict(db_session: Session) -> None:
    category = category_service.create_category(db_session, "区块链", actor="tester")
    assert category.name == "区块链"
    assert category.status is CategoryStatus.ACTIVE

    with pytest.raises(ApiError) as exc_info:
        category_service.create_category(db_session, "区块链", actor="tester")
    assert exc_info.value.status_code == 409


def test_rename_category_including_default(db_session: Session) -> None:
    seeded = category_service.ensure_default_categories(db_session)
    target = next(category for category in seeded if category.name == "数据库")

    renamed = category_service.rename_category(db_session, target.id, "数据存储", actor="tester")
    assert renamed.name == "数据存储"

    history = category_service.get_category_history(db_session, target.id)
    actions = [record.action for record in history]
    assert CategoryAction.CREATE in actions
    assert CategoryAction.RENAME in actions


def test_deactivate_and_activate_category(db_session: Session) -> None:
    category = category_service.create_category(db_session, "临时类别", actor="tester")

    deactivated = category_service.set_category_status(
        db_session, category.id, CategoryStatus.INACTIVE, actor="tester"
    )
    assert deactivated.status is CategoryStatus.INACTIVE
    assert category.id not in [
        item.id for item in category_service.list_categories(db_session, include_inactive=False)
    ]

    reactivated = category_service.set_category_status(
        db_session, category.id, CategoryStatus.ACTIVE, actor="tester"
    )
    assert reactivated.status is CategoryStatus.ACTIVE


def test_merge_categories_moves_articles(db_session: Session) -> None:
    source = make_category(db_session, "旧类别")
    target = make_category(db_session, "新类别")
    article = make_article(db_session, "https://example.com/a", source)
    db_session.commit()

    merged = category_service.merge_categories(db_session, source.id, target.id, actor="tester")

    assert merged.id == target.id
    db_session.refresh(article)
    assert article.primary_category_id == target.id

    db_session.refresh(source)
    assert source.status is CategoryStatus.INACTIVE

    history = db_session.scalars(
        select(CategoryHistory).where(
            CategoryHistory.category_id == source.id,
            CategoryHistory.action == CategoryAction.MERGE,
        )
    ).all()
    assert len(history) == 1
    assert history[0].target_category_id == target.id


def test_merge_into_self_is_rejected(db_session: Session) -> None:
    category = make_category(db_session, "单类别")
    db_session.commit()

    with pytest.raises(ApiError) as exc_info:
        category_service.merge_categories(db_session, category.id, category.id, actor="tester")
    assert exc_info.value.status_code == 422


# --- API 层 -------------------------------------------------------------------


def test_api_lists_seeded_categories(
    client: TestClient, admin_headers: dict[str, str], api_session: Session
) -> None:
    category_service.ensure_default_categories(api_session)

    response = client.get(CATEGORIES_URL, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["total"] == 7


def test_api_create_rename_merge_deactivate(
    client: TestClient, admin_headers: dict[str, str], api_session: Session
) -> None:
    category_service.ensure_default_categories(api_session)

    created = client.post(CATEGORIES_URL, json={"name": "游戏开发"}, headers=admin_headers)
    assert created.status_code == 201, created.text
    category_id = created.json()["id"]

    renamed = client.post(
        f"{CATEGORIES_URL}/{category_id}/rename",
        json={"new_name": "游戏工程"},
        headers=admin_headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "游戏工程"

    listing = client.get(CATEGORIES_URL, headers=admin_headers).json()
    target = next(item for item in listing["items"] if item["name"] == "Web 开发")

    merged = client.post(
        f"{CATEGORIES_URL}/{category_id}/merge",
        json={"target_category_id": target["id"]},
        headers=admin_headers,
    )
    assert merged.status_code == 200
    assert merged.json()["id"] == target["id"]

    deactivated = client.post(f"{CATEGORIES_URL}/{category_id}/deactivate", headers=admin_headers)
    assert deactivated.status_code == 200
    assert deactivated.json()["status"] == "inactive"


def test_api_rejects_empty_category_name(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.post(CATEGORIES_URL, json={"name": "   "}, headers=admin_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", CATEGORIES_URL, None),
        ("post", CATEGORIES_URL, {"name": "x"}),
        ("post", f"{CATEGORIES_URL}/cat_x/rename", {"new_name": "y"}),
        ("post", f"{CATEGORIES_URL}/cat_x/merge", {"target_category_id": "cat_y"}),
        ("post", f"{CATEGORIES_URL}/cat_x/deactivate", None),
        ("post", f"{CATEGORIES_URL}/cat_x/activate", None),
        ("get", f"{CATEGORIES_URL}/cat_x/history", None),
    ],
)
def test_category_endpoints_require_authorization(
    client: TestClient, method: str, path: str, payload: dict[str, object] | None
) -> None:
    request = getattr(client, method)
    response = request(path, json=payload) if payload is not None else request(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
