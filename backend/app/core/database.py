"""
Database foundation for ULTRON.

Phase 1 scope: a working SQLite connection, a declarative base, and a
session dependency for FastAPI routes. Real tables (devices, tasks,
memory, audit log) get added as each owning phase lands -- Phase 1 only
proves the database layer itself works end-to-end via one real table
(SystemEvent) exercised by the health-check endpoint.

Migrations: Alembic is introduced in the phase that first needs a schema
change against real user data (Phase 5, Task Manager). Phase 1 uses
`Base.metadata.create_all()` since there's no data yet to migrate.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone

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


def init_db() -> None:
    """Create tables that don't exist yet. Idempotent."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
