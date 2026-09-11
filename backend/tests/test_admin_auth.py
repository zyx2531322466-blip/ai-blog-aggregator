"""T03 维护者访问控制基础设施测试。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import AdminPrincipal, authenticate_admin_token, require_admin
from tests.conftest import TEST_ADMIN_ACTOR, TEST_ADMIN_TOKEN, build_test_settings


def test_authenticate_admin_token_unit() -> None:
    settings = build_test_settings()

    assert authenticate_admin_token(None, settings) is None
    assert authenticate_admin_token("", settings) is None
    assert authenticate_admin_token("wrong-token", settings) is None
    assert authenticate_admin_token(TEST_ADMIN_TOKEN, settings) == AdminPrincipal(
        actor=TEST_ADMIN_ACTOR
    )


def test_authenticate_admin_token_with_empty_configured_token() -> None:
    settings = Settings(admin_token="", admin_actor="admin")
    assert authenticate_admin_token("anything", settings) is None


def test_admin_endpoint_rejects_missing_token(client: TestClient) -> None:
    response = client.get("/api/v1/admin/ping")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHORIZED"
    assert body["error"]["message"]


def test_admin_endpoint_rejects_wrong_token(client: TestClient) -> None:
    response = client.get("/api/v1/admin/ping", headers={"Authorization": "Bearer not-the-token"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_admin_endpoint_rejects_malformed_authorization(client: TestClient) -> None:
    response = client.get("/api/v1/admin/ping", headers={"Authorization": TEST_ADMIN_TOKEN})
    assert response.status_code == 401


def test_admin_endpoint_accepts_valid_token(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/admin/ping", headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "actor": TEST_ADMIN_ACTOR}


def test_public_infra_endpoint_stays_anonymous(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_public_routes_are_not_affected_by_admin_dependency(
    api_app: FastAPI, admin_headers: dict[str, str]
) -> None:
    """访问控制只作用于挂载了依赖的路由，不影响匿名浏览类路由。"""

    @api_app.get("/api/v1/public-probe")
    def public_probe() -> dict[str, bool]:
        return {"public": True}

    with TestClient(api_app) as test_client:
        # 匿名可访问公共探针
        assert test_client.get("/api/v1/public-probe").status_code == 200
        # 维护者接口仍需令牌
        assert test_client.get("/api/v1/admin/ping").status_code == 401
        assert test_client.get("/api/v1/admin/ping", headers=admin_headers).status_code == 200


def test_unknown_route_uses_unified_error_format(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_openapi_documents_bearer_security(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    security_schemes = schema["components"]["securitySchemes"]
    assert any(
        scheme.get("type") == "http" and scheme.get("scheme") == "bearer"
        for scheme in security_schemes.values()
    )
    assert require_admin is not None
