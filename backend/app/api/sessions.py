"""
Session Lifecycle API surface.

Create a session, look up its status, and invalidate it (which also
clears any session-scoped permission grants -- see SessionManager).
Creation/lookup are unauthenticated (a session is how a caller
*establishes* identity for later session-scoped permission checks, not
a sensitive operation in itself); invalidation is likewise left open
since a caller invalidating its own session is self-limiting, not
privilege-escalating.

TTL clamping (Issue 2 fix):
  Any caller-supplied ttl_seconds is silently clamped to
  [0, DEFAULT_SESSION_TTL_SECONDS]. Omitting ttl_seconds uses the same
  default cap. This prevents unauthenticated callers from creating
  never-expiring sessions (DB exhaustion / permission-persistence DoS)
  while still allowing the normal 12-hour lifespan the Tauri UI needs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.sessions.manager import DEFAULT_SESSION_TTL_SECONDS, SessionInfo, SessionManager

router = APIRouter(prefix="/sessions")


def _clamp_ttl(ttl_seconds: float | None) -> float:
    """Return a ttl_seconds value that is safe to pass to SessionManager.

    None (omitted) and any value above the cap both collapse to
    DEFAULT_SESSION_TTL_SECONDS. Values <= 0 are left as-is so tests
    can still create immediately-expired sessions (they're harmless --
    an expired session is already treated as invalid everywhere)."""
    if ttl_seconds is None or ttl_seconds > DEFAULT_SESSION_TTL_SECONDS:
        return DEFAULT_SESSION_TTL_SECONDS
    return ttl_seconds


@router.post("", response_model=SessionInfo)
def create_session(
    ttl_seconds: float | None = None, db: Session = Depends(get_db)
) -> SessionInfo:
    return SessionManager(db).create(ttl_seconds=_clamp_ttl(ttl_seconds))


@router.get("/{session_id}", response_model=SessionInfo)
def get_session(session_id: str, db: Session = Depends(get_db)) -> SessionInfo:
    info = SessionManager(db).get(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    return info


@router.post("/{session_id}/invalidate", response_model=SessionInfo)
def invalidate_session(session_id: str, db: Session = Depends(get_db)) -> SessionInfo:
    info = SessionManager(db).invalidate(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    return info
