"""
Database foundation for ULTRON.

Phase 1 scope: a working SQLite connection, a declarative base, and a
session dependency for FastAPI routes. Real tables (devices, tasks,
memory, audit log) get added as each owning phase lands -- Phase 1 only
proves the database layer itself works end-to-end via one real table
(SystemEvent) exercised by the health-check endpoint.

Migrations: schema changes are owned exclusively by Alembic (see
backend/alembic/ + alembic.ini). `Base.metadata.create_all()` is never
used to stand up the app's real database -- only the test suite uses it,
against an isolated temp DB, so tests don't depend on Alembic being run.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings

settings = get_settings()
settings.ensure_data_dirs()

# check_same_thread=False is safe here because FastAPI's dependency
# system hands each request its own Session from SessionLocal.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class SystemEvent(Base):
    """Minimal real table for Phase 1: proves writes/reads work.

    Later phases replace ad-hoc use of this table with proper
    AuditLog / TaskRecord / Device / MemoryEntry models -- this one
    exists only to give the health check something real to verify.
    """

    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


def schema_is_current() -> bool:
    """True if the DB is migrated to the latest Alembic revision.

    Read-only check -- never creates or alters anything. App startup
    uses this to warn (not auto-fix) when 'alembic upgrade head' hasn't
    been run.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect

    backend_dir = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    script = ScriptDirectory.from_config(alembic_cfg)
    head_revision = script.get_current_head()

    inspector = inspect(engine)
    if "alembic_version" not in inspector.get_table_names():
        return False

    with engine.connect() as conn:
        row = conn.exec_driver_sql("SELECT version_num FROM alembic_version").fetchone()
    current_revision = row[0] if row else None

    return current_revision == head_revision


def create_all_for_tests() -> None:
    """Test-only helper. Production schema is owned by Alembic migrations
    (see backend/alembic/) -- this exists solely so the test suite can
    stand up an isolated temp SQLite DB without running migrations."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
