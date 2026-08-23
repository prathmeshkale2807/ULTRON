"""
Shared fixtures for Phase 3 (Tool Registry + Safety Gate) tests.

`db_session` deliberately does NOT go through app.core.database's
module-level `engine`/`SessionLocal` singletons -- those are bound once,
at first import, to whichever DATABASE_URL happened to be active then
(see tests/test_health.py's fixture, which works around the same thing
via monkeypatch + cache-clearing before first import). Phase 3's own
components (PermissionStore, AuditLogger, EmergencyStop, ToolExecutor)
all take a plain SQLAlchemy Session as a constructor argument, so tests
here build a fully independent temp-file SQLite engine per test instead
-- true isolation, no dependence on import order or which test file
pytest happens to collect first.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import app.automations.models
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture()
def db_session(tmp_path: Path):
    from app.core.database import Base
    import app.automations.models  # import here, after any env setup

    db_file = tmp_path / f"phase3_test_{id(tmp_path)}.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session: Session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
import os
os.environ['ENVIRONMENT'] = 'test'

