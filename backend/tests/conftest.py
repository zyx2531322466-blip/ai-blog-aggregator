"""pytest 公共夹具。

测试一律使用内存 SQLite，不依赖外部数据库，也不依赖真实网络。
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db import models  # noqa: F401  （注册模型）
from app.db.base import Base
from app.db.session import get_db

BACKEND_DIR = Path(__file__).resolve().parents[1]

TEST_ADMIN_TOKEN = "test-admin-token"
TEST_ADMIN_ACTOR = "test-admin"


def build_test_settings(**overrides: object) -> Settings:
    """构造测试用配置（不读取真实环境变量中的令牌）。"""

    defaults: dict[str, object] = {
        "environment": "test",
        "admin_token": TEST_ADMIN_TOKEN,
        "admin_actor": TEST_ADMIN_ACTOR,
        "database_url": "sqlite+pysqlite:///:memory:",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _memory_engine() -> Engine:
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )


@pytest.fixture()
def engine() -> Iterator[Engine]:
    """内存 SQLite 引擎（同一连接，保证表在会话间可见）。"""

    engine = _memory_engine()
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """会话工厂。"""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """每个用例独立会话，结束后回滚，避免用例间相互污染。"""

    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def api_settings() -> Settings:
    """API 集成测试使用的配置。"""

    return build_test_settings()


@pytest.fixture()
def api_session(engine: Engine) -> Iterator[Session]:
    """API 集成测试共享的会话（与覆盖后的 get_db 使用同一引擎）。"""

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def api_app(engine: Engine, api_settings: Settings) -> FastAPI:
    """挂载了 v1 路由，并将配置/数据库依赖指向测试资源的应用实例。"""

    from app.main import create_app

    application = create_app(api_settings)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _override_get_db() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[get_settings] = lambda: api_settings
    application.dependency_overrides[get_db] = _override_get_db
    return application


@pytest.fixture()
def client(api_app: FastAPI) -> Iterator[TestClient]:
    """匿名客户端。"""

    with TestClient(api_app) as test_client:
        yield test_client


@pytest.fixture()
def admin_headers() -> dict[str, str]:
    """携带有效维护者令牌的请求头。"""

    return {"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}
