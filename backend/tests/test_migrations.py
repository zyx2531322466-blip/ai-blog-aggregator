"""T02 迁移脚本升级/回滚测试。

在临时 SQLite 上执行 ``alembic upgrade head`` 与 ``alembic downgrade base``，
验证迁移可在空数据库上成功执行且可回滚。
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {
    "articles",
    "categories",
    "category_history",
    "tags",
    "article_tags",
    "sources",
    "duplicate_relations",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _table_names(database_url: str) -> set[str]:
    engine = create_engine(database_url, future=True)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.fixture()
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"


def test_upgrade_creates_all_tables(sqlite_url: str) -> None:
    config = _alembic_config(sqlite_url)
    command.upgrade(config, "head")

    tables = _table_names(sqlite_url)
    assert EXPECTED_TABLES.issubset(tables)
    assert "alembic_version" in tables


def test_downgrade_removes_all_tables(sqlite_url: str) -> None:
    config = _alembic_config(sqlite_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    remaining = _table_names(sqlite_url)
    assert remaining.isdisjoint(EXPECTED_TABLES)


def test_migration_round_trip_is_repeatable(sqlite_url: str) -> None:
    """升级 → 回滚 → 再升级，验证迁移可重复执行。"""

    config = _alembic_config(sqlite_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    assert EXPECTED_TABLES.issubset(_table_names(sqlite_url))
