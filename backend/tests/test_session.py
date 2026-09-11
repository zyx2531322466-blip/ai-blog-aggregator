"""T02 会话/引擎构建的单元测试（存储基础设施）。"""

from pathlib import Path

from sqlalchemy import inspect

from app.db import models  # noqa: F401  （注册模型）
from app.db.base import Base
from app.db.session import (
    build_engine,
    build_session_factory,
    get_db,
    init_db,
)


def test_build_engine_creates_sqlite_parent_directory(tmp_path: Path) -> None:
    db_file = tmp_path / "nested" / "app.db"
    engine = build_engine(f"sqlite:///{db_file.as_posix()}")
    try:
        assert db_file.parent.exists()
        with engine.connect() as connection:
            assert connection.exec_driver_sql("select 1").scalar() == 1
    finally:
        engine.dispose()


def test_build_engine_supports_in_memory() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        assert "sources" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_build_session_factory_yields_working_session(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    factory = build_session_factory(engine)
    try:
        Base.metadata.create_all(engine)
        with factory() as session:
            assert session.is_active
    finally:
        engine.dispose()


def test_get_db_yields_and_closes_session(monkeypatch, tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{(tmp_path / 'y.db').as_posix()}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.db.session.get_session_factory", lambda: build_session_factory(engine))

    generator = get_db()
    session = next(generator)
    assert session.is_active
    generator.close()
    engine.dispose()


def test_init_db_creates_tables(monkeypatch, tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{(tmp_path / 'z.db').as_posix()}")
    monkeypatch.setattr("app.db.session.get_engine", lambda: engine)
    try:
        init_db()
        tables = set(inspect(engine).get_table_names())
        assert {"articles", "categories", "sources", "tags", "duplicate_relations"} <= tables
    finally:
        engine.dispose()
