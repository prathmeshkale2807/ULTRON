"""
Verifies the Alembic migration path for real: runs `alembic upgrade head`
against an isolated temp SQLite DB and checks the resulting schema matches
what the app expects (system_events table with the right columns) --
this is the thing Phase 1 actually claims ("migrations work"), so it's the
thing under test, not just presence of a migration file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


@pytest.fixture()
def temp_db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'migration_test.db'}"


def _alembic_config(database_url: str) -> Config:
    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def test_upgrade_head_creates_expected_schema(temp_db_url):
    cfg = _alembic_config(temp_db_url)
    command.upgrade(cfg, "head")

    engine = create_engine(temp_db_url)
    inspector = inspect(engine)

    assert "system_events" in inspector.get_table_names()
    columns = {c["name"] for c in inspector.get_columns("system_events")}
    assert columns == {"id", "event_type", "detail", "created_at"}

    assert "alembic_version" in inspector.get_table_names()


def test_downgrade_removes_table(temp_db_url):
    cfg = _alembic_config(temp_db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(temp_db_url)
    inspector = inspect(engine)
    assert "system_events" not in inspector.get_table_names()


def test_schema_is_current_reflects_real_migration_state(monkeypatch, temp_db_url, tmp_path):
    monkeypatch.setenv("DATABASE_URL", temp_db_url)
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))

    from app.core.config import get_settings

    get_settings.cache_clear()

    # Re-import database module against the patched settings/engine.
    import importlib

    import app.core.database as database_module

    importlib.reload(database_module)

    assert database_module.schema_is_current() is False

    cfg = _alembic_config(temp_db_url)
    command.upgrade(cfg, "head")

    importlib.reload(database_module)
    assert database_module.schema_is_current() is True

    get_settings.cache_clear()
