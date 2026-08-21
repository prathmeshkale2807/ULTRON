"""
Emergency Stop API surface.

activate / reset / status. Activation is deliberately left
unauthenticated -- an emergency stop is a safety-positive action and
must always be reachable, even by a caller that hasn't authenticated,
so nothing ever gates *stopping*. Reset, by contrast, re-enables
execution and is a sensitive local management operation: it requires
the local auth token and is recorded to the permission audit trail.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.permission_log import PermissionAuditLogger
from app.core.database import get_db
from app.emergency.stop import EmergencyStop, EmergencyStopStatus
from app.security.local_auth import require_local_auth

router = APIRouter(prefix="/emergency")


class ActivateRequest(BaseModel):
    reason: str = ""
    activated_by: str = "unknown"


class ResetRequest(BaseModel):
    reset_by: str = "unknown"


@router.get("/status", response_model=EmergencyStopStatus)
def status(db: Session = Depends(get_db)) -> EmergencyStopStatus:
    return EmergencyStop(db).status()


@router.post("/activate", response_model=EmergencyStopStatus)
def activate(body: ActivateRequest, db: Session = Depends(get_db)) -> EmergencyStopStatus:
    return EmergencyStop(db).activate(reason=body.reason, activated_by=body.activated_by)


@router.post("/reset", response_model=EmergencyStopStatus)
def reset(
    body: ResetRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(require_local_auth),
) -> EmergencyStopStatus:
    old_status = EmergencyStop(db).status()
    new_status = EmergencyStop(db).reset(reset_by=body.reset_by)
    PermissionAuditLogger(db).record(
        actor=body.reset_by,
        action="emergency_reset",
        old_state="engaged" if old_status.engaged else "not_engaged",
        new_state="engaged" if new_status.engaged else "not_engaged",
    )
    return new_status
