"""T04 主题与来源配置管理测试。"""

import pytest
from fastapi.testclient import TestClient

SOURCES_URL = "/api/v1/admin/sources"


def focus_area_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "示例 AI 博客",
        "site_url": "https://ai.example.com",
        "description": "聚焦人工智能技术",
        "focus_area_name": "人工智能",
        "focus_area_description": "机器学习与深度学习相关内容",
        "keywords": ["机器学习", "深度学习"],
        "exclude_keywords": ["广告", "招聘"],
        "example_urls": ["https://ai.example.com/post/1"],
        "counter_example_urls": ["https://ai.example.com/ad"],
        "list_type": "whitelist",
    }
    payload.update(overrides)
    return payload


def test_create_focus_area_source(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.post(SOURCES_URL, json=focus_area_payload(), headers=admin_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"].startswith("source_")
    assert body["focus_area_name"] == "人工智能"
    assert body["keywords"] == ["机器学习", "深度学习"]
    assert body["example_urls"] == ["https://ai.example.com/post/1"]
    assert body["list_type"] == "whitelist"
    # 未指定权重时与其他来源默认相等
    assert body["weight"] == 1.0
    assert body["is_active"] is True


def test_create_source_rejects_blank_name(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.post(SOURCES_URL, json=focus_area_payload(name="   "), headers=admin_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_whitelist_without_focus_area_is_rejected(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.post(
        SOURCES_URL,
        json=focus_area_payload(keywords=[], example_urls=[]),
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_source_rejects_invalid_weight(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.post(SOURCES_URL, json=focus_area_payload(weight=0), headers=admin_headers)
    assert response.status_code == 422


def test_blacklist_site_can_be_configured_and_viewed(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    black_payload = {
        "name": "垃圾站",
        "site_url": "https://spam.example",
        "list_type": "blacklist",
    }
    created = client.post(SOURCES_URL, json=black_payload, headers=admin_headers)
    assert created.status_code == 201, created.text

    blocked = client.get(
        SOURCES_URL, params={"list_type": "blacklist"}, headers=admin_headers
    ).json()
    assert blocked["total"] == 1
    assert blocked["items"][0]["site_url"].startswith("https://spam.example")

    whitelist = client.get(
        SOURCES_URL, params={"list_type": "whitelist"}, headers=admin_headers
    ).json()
    assert whitelist["total"] == 0


def test_weight_can_be_overridden_and_updated(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    created = client.post(
        SOURCES_URL, json=focus_area_payload(weight=3.5), headers=admin_headers
    ).json()
    assert created["weight"] == 3.5

    updated = client.patch(
        f"{SOURCES_URL}/{created['id']}", json={"weight": 8}, headers=admin_headers
    )
    assert updated.status_code == 200
    assert updated.json()["weight"] == 8.0


def test_edit_focus_area_fields(client: TestClient, admin_headers: dict[str, str]) -> None:
    created = client.post(SOURCES_URL, json=focus_area_payload(), headers=admin_headers).json()

    response = client.patch(
        f"{SOURCES_URL}/{created['id']}",
        json={
            "focus_area_description": "更新后的领域描述",
            "keywords": ["神经网络"],
            "exclude_keywords": ["推广"],
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["focus_area_description"] == "更新后的领域描述"
    assert body["keywords"] == ["神经网络"]
    assert body["exclude_keywords"] == ["推广"]


def test_edit_to_blacklist_requires_no_focus_area(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    created = client.post(SOURCES_URL, json=focus_area_payload(), headers=admin_headers).json()
    response = client.patch(
        f"{SOURCES_URL}/{created['id']}", json={"list_type": "blacklist"}, headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["list_type"] == "blacklist"


def test_duplicate_site_url_is_conflict(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert (
        client.post(SOURCES_URL, json=focus_area_payload(), headers=admin_headers).status_code
        == 201
    )
    duplicate = client.post(SOURCES_URL, json=focus_area_payload(), headers=admin_headers)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CONFLICT"


def test_source_detail_not_found(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get(f"{SOURCES_URL}/source_missing", headers=admin_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_sources_list_and_detail_round_trip(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    created = client.post(SOURCES_URL, json=focus_area_payload(), headers=admin_headers).json()

    listing = client.get(SOURCES_URL, headers=admin_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    detail = client.get(f"{SOURCES_URL}/{created['id']}", headers=admin_headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == created["id"]


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", SOURCES_URL, focus_area_payload()),
        ("get", SOURCES_URL, None),
        ("get", f"{SOURCES_URL}/source_x", None),
        ("patch", f"{SOURCES_URL}/source_x", {"weight": 2}),
    ],
)
def test_all_source_admin_endpoints_require_authorization(
    client: TestClient, method: str, path: str, payload: dict[str, object] | None
) -> None:
    request = getattr(client, method)
    response = request(path, json=payload) if payload is not None else request(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_unauthorized_write_does_not_persist(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    client.post(SOURCES_URL, json=focus_area_payload())  # 未授权
    assert client.get(SOURCES_URL, headers=admin_headers).json()["total"] == 0
