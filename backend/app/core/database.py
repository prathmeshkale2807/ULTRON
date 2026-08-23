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

from sqlalchemy import Boolean, DateTime, Integer, String, Float, create_engine
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


class PermissionRecord(Base):
    """Persistent (not session-scoped) permission grants/denials.

    Only ever stores a category/device/tool name and a granted flag --
    see app/permissions/store.py's module docstring for why secrets can
    never land in this table even by accident. Session-scoped grants are
    intentionally NOT stored here (see app/permissions/store.py); they
    live in-memory for the life of the process, since a session grant is
    defined to not outlive it.
    """

    __tablename__ = "permission_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    # Optional narrowing: a persistent grant/denial can be scoped to one
    # tool name and/or one device type; NULL means "the whole category".
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device: Mapped[str | None] = mapped_column(String(32), nullable=True)
    granted: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class AuditLogEntry(Base):
    """Append-only record of every tool-decision the Safety Gate and
    Executor make. Never holds API keys, passwords, tokens, or other
    secrets -- see app/audit/log.py's redaction helper, which is the
    only code path permitted to write rows into this table."""

    __tablename__ = "audit_log_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    requested_action: Mapped[str] = mapped_column(String(256))
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    risk_level: Mapped[str] = mapped_column(String(16))
    permission_result: Mapped[str] = mapped_column(String(32))
    confirmation_result: Mapped[str] = mapped_column(String(32))
    execution_result: Mapped[str] = mapped_column(String(32))
    verification_result: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(String(1024), default="")


class EmergencyStopRecord(Base):
    """Singleton row (id=1) holding current emergency-stop state. A real
    table (not a process-memory flag) so the engaged state survives a
    backend restart -- an engaged stop must never silently clear itself
    just because the process was restarted."""

    __tablename__ = "emergency_stop_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    engaged: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(512), default="")
    activated_by: Mapped[str] = mapped_column(String(128), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class ActiveProfileRecord(Base):
    """Singleton row (id=1) holding the persisted active Safety Mode
    profile (Safe/Balanced/Trusted/Custom) and, for Custom, the
    per-category confirmation-tier override map as a JSON string.
    A real table (not process memory) so the active profile survives a
    backend restart -- restarting must never silently reset the user
    back to Balanced without them choosing that."""

    __tablename__ = "active_profile_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default="balanced")
    custom_overrides: Mapped[str] = mapped_column(String(2048), default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_by: Mapped[str] = mapped_column(String(128), default="")


class SessionRecord(Base):
    """A ULTRON session's lifecycle metadata. Session-scoped permission
    grants themselves stay in PermissionStore's in-memory table (see
    app/permissions/store.py) -- this row is only the session's
    identity/expiry/invalidation state, which the session-scoped
    permission checks are gated against at the API layer."""

    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invalidated: Mapped[bool] = mapped_column(Boolean, default=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PermissionAuditEntry(Base):
    """Append-only history of permission/profile/emergency-reset
    *management* decisions -- distinct from AuditLogEntry, which
    records tool-call decisions. Never holds API keys, passwords,
    tokens, or other secrets: only short state labels and identifiers
    are ever written here (see app/audit/permission_log.py)."""

    __tablename__ = "permission_audit_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    actor: Mapped[str] = mapped_column(String(128), default="unknown")
    action: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device: Mapped[str | None] = mapped_column(String(32), nullable=True)
    old_state: Mapped[str] = mapped_column(String(64), default="")
    new_state: Mapped[str] = mapped_column(String(64), default="")


class TaskRecord(Base):
    """One row per submitted task.

    A task is a unit of work submitted to the Task Manager. It has a
    full lifecycle (QUEUED → ... → COMPLETED/FAILED/CANCELLED) and is
    owned by the session that created it. Every state change that matters
    for safety or audit also writes a TaskAuditEntry.

    Never stores secrets -- description and error_summary are redacted
    before write. tools_requested and progress_metadata are JSON blobs
    of safe identifiers only.
    """

    __tablename__ = "task_records"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    principal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), default="")
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    state: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    error_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tools_requested: Mapped[str] = mapped_column(String(1024), default="[]")
    verification_status: Mapped[str] = mapped_column(String(32), default="not_required")
    progress_metadata: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class TaskAuditEntry(Base):
    """Append-only log of task lifecycle events.

    Distinct from AuditLogEntry (which records individual tool-call
    pipeline decisions) and PermissionAuditEntry (which records
    permission management changes). This table records task-level events:
    created, state changes, cancellation, emergency-stop influence, etc.

    Never holds secrets -- `detail` is bounded and redacted before write.
    """

    __tablename__ = "task_audit_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    event: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(String(512), default="")
    actor: Mapped[str] = mapped_column(String(128), default="system")



class ConversationRecord(Base):
    """A multi-turn conversation session."""
    __tablename__ = "conversation_records"

    conversation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    state: Mapped[str] = mapped_column(String(32), default="idle")
    active_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active_plan_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pending_confirmation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class MessageRecord(Base):
    """A single turn in a conversation."""
    __tablename__ = "message_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user, assistant, system, tool
    content: Mapped[str] = mapped_column(String(4096), default="")
    metadata_json: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class MemoryRecord(Base):
    """Long-term personal user memory."""
    __tablename__ = "long_term_memories"

    memory_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128), index=True)  # Authenticated user/owner
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Provenance/Session scope
    
    memory_type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(String(4096))
    normalized_content: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    
    importance: Mapped[float] = mapped_column(Float, default=1.0)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    
    sensitivity: Mapped[str] = mapped_column(String(32), default="INTERNAL")
    source_type: Mapped[str] = mapped_column(String(32), default="USER_DIRECT")
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, default=1)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)



class IdempotencyRecord(Base):
    """Crash-safe idempotency for destructive actions like email_send.

    Written BEFORE the external API call (status='pending'), updated to
    'completed' or 'failed' after. On process restart, a 'pending' record
    means the previous attempt's outcome is unknown -- the handler must
    check the provider (e.g. Gmail sent folder) before retrying.
    """
    __tablename__ = "idempotency_keys"

    idempotency_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128), index=True)
    tool_name: Mapped[str] = mapped_column(String(128), default="")
    request_fingerprint: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    provider_message_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class DevicePairingCode(Base):
    """Phase 11: One-time, short-lived code for pairing an Android device.
    Owned by a principal_id. Once used, the code is consumed to mint a credential."""
    __tablename__ = "device_pairing_codes"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    device_name_hint: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class DeviceRecord(Base):
    """Phase 11: Registered Android devices.
    Contains the credential hash and tracks the status/last heartbeat.
    All operations must verify principal ownership."""
    __tablename__ = "device_records"

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(128), default="Android Device")
    device_type: Mapped[str] = mapped_column(String(32), default="ANDROID")
    credential_hash: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default="PAIRED")
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

# Import specific models to ensure Base metadata contains them for Alembic


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


def create_all_for_tests(bind=None) -> None:
    """Test-only helper. Production schema is owned by Alembic migrations
    (see backend/alembic/) -- this exists solely so the test suite can
    stand up an isolated temp SQLite DB without running migrations.

    Pass `bind` (an Engine) to target a specific test database rather than
    the module-level singleton engine. This is required when the calling
    fixture creates its own isolated engine after monkeypatching DATABASE_URL.
    """
    target = bind if bind is not None else engine
    Base.metadata.create_all(bind=target)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
