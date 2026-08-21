"""
Session Lifecycle API surface.

Create a session, look up its status, and invalidate it (which also
clears any session-scoped permission grants -- see SessionManager).
Creation/lookup are unauthenticated (a session is how a caller
*establishes* identity for later session-scoped permission checks, not
a sensitive operation in itself); invalidation is likewise left open
since a caller invalidating its own session is self-limiting, not
privilege-escalating.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.sessions.manager import SessionInfo, SessionManager

router = APIRouter(prefix="/sessions")


@router.post("", response_model=SessionInfo)
def create_session(
    ttl_seconds: float | None = None, db: Session = Depends(get_db)
) -> SessionInfo:
    kwargs = {} if ttl_seconds is None else {"ttl_seconds": ttl_seconds}
    return SessionManager(db).create(**kwargs)


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
