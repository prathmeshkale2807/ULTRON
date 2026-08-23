"""
Session Lifecycle API surface.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.sessions.manager import DEFAULT_SESSION_TTL_SECONDS, SessionInfo, SessionManager
from app.security.local_auth import Principal, require_local_auth

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _clamp_ttl(ttl_seconds: float | None) -> float:
    if ttl_seconds is None or ttl_seconds > DEFAULT_SESSION_TTL_SECONDS:
        return DEFAULT_SESSION_TTL_SECONDS
    return ttl_seconds


@router.post("", response_model=SessionInfo)
def create_session(
    ttl_seconds: float | None = None, 
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth)
) -> SessionInfo:
    return SessionManager(db).create(principal.identity, ttl_seconds=_clamp_ttl(ttl_seconds))


@router.get("/{session_id}", response_model=SessionInfo)
def get_session(
    session_id: str, 
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth)
) -> SessionInfo:
    mgr = SessionManager(db)
    # Validate ownership
    if not mgr.is_valid(session_id, principal.identity):
        raise HTTPException(status_code=403, detail="not authorized to view this session")
        
    info = mgr.get(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    return info


@router.post("/{session_id}/invalidate", response_model=SessionInfo)
def invalidate_session(
    session_id: str, 
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth)
) -> SessionInfo:
    mgr = SessionManager(db)
    # Validate ownership
    if not mgr.is_valid(session_id, principal.identity):
        raise HTTPException(status_code=403, detail="not authorized to invalidate this session")
        
    info = mgr.invalidate(session_id)
    if info is None:
        raise HTTPException(status_code=404, detail="unknown session_id")
    return info
