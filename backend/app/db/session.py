"""数据库引擎与会话管理。

默认使用 SQLite（本地开发/测试零依赖），生产通过 ``APP_DATABASE_URL``
注入 PostgreSQL（Docker Compose 已配置）。
"""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine(database_url: str, **engine_kwargs: object) -> Engine:
    """按数据库 URL 构建 Engine，并为 SQLite 做必要适配。"""

    connect_args: dict[str, object] = dict(engine_kwargs.pop("connect_args", {}) or {})
    if database_url.startswith("sqlite"):
        connect_args.setdefault("check_same_thread", False)
        _ensure_sqlite_parent_dir(database_url)
    return create_engine(database_url, connect_args=connect_args, future=True, **engine_kwargs)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """构建与会话工厂。"""

    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    """确保 SQLite 文件所在目录存在，避免首次连接报错。"""

    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    raw_path = database_url[len(prefix) :]
    if raw_path in ("", ":memory:") or raw_path.startswith(":memory:"):
        return
    Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """返回进程级默认 Engine（懒加载）。"""

    global _engine
    if _engine is None:
        _engine = build_engine(get_settings().database_url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """返回进程级默认会话工厂（懒加载）。"""

    global _session_factory
    if _session_factory is None:
        _session_factory = build_session_factory(get_engine())
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：提供请求级数据库会话。"""

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """在开发环境按模型创建表（生产使用 Alembic 迁移）。"""

    from app.db import models  # noqa: F401  （确保模型已注册到 metadata）
    from app.db.base import Base

    Base.metadata.create_all(get_engine())
