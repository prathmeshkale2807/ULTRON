"""
Session lifecycle: creation, expiration, invalidation.

A session's identity/expiry lives in the `sessions` table (DB-backed,
survives restart). The session's *permission grants* deliberately do
NOT live here -- they stay in PermissionStore's in-memory table, per
its own module docstring, since a session grant is defined to never
outlive the process. Invalidating a session here also clears its
session-scoped permission grants from that in-memory table, so the two
stay consistent: an invalidated session has no lingering permissions
even within the same process lifetime.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.database import SessionRecord
from app.core.logging_config import get_logger
from app.permissions.store import PermissionStore

logger = get_logger("sessions.manager")

DEFAULT_SESSION_TTL_SECONDS = 12 * 60 * 60  # 12 hours


class SessionInfo(BaseModel):
    session_id: str
    created_at: datetime
    expires_at: datetime | None
    invalidated: bool
    valid: bool


class SessionManager:
    def __init__(self, db: DBSession) -> None:
        self.db = db

    def create(self, *, ttl_seconds: float | None = DEFAULT_SESSION_TTL_SECONDS) -> SessionInfo:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds else None
        row = SessionRecord(
            session_id=secrets.token_urlsafe(24),
            created_at=now,
            expires_at=expires_at,
            invalidated=False,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        logger.info("Session created id=%s expires_at=%s", row.session_id, expires_at)
        return self._to_info(row)

    def get(self, session_id: str) -> SessionInfo | None:
        row = self.db.get(SessionRecord, session_id)
        if row is None:
            return None
        return self._to_info(row)

    def is_valid(self, session_id: str) -> bool:
        info = self.get(session_id)
        return info is not None and info.valid

    def invalidate(self, session_id: str) -> SessionInfo | None:
        row = self.db.get(SessionRecord, session_id)
        if row is None:
            return None
        row.invalidated = True
        row.invalidated_at = datetime.now(timezone.utc)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        # Clearing session-scoped permissions is the whole point of
        # invalidation -- an invalidated session must not leave any
        # grant reachable, even within the same running process.
        PermissionStore(self.db).clear_session(session_id)
        logger.info("Session invalidated id=%s", session_id)
        return self._to_info(row)

    @staticmethod
    def _to_info(row: SessionRecord) -> SessionInfo:
        now = datetime.now(timezone.utc)
        expired = row.expires_at is not None and _as_aware(row.expires_at) < now
        return SessionInfo(
            session_id=row.session_id,
            created_at=row.created_at,
            expires_at=row.expires_at,
            invalidated=row.invalidated,
            valid=not row.invalidated and not expired,
        )


def _as_aware(dt: datetime) -> datetime:
    # SQLite loses tzinfo on round-trip; treat naive datetimes as UTC,
    # matching how every timestamp in this codebase is written.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
