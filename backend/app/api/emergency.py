"""
Emergency Stop API surface.

activate / reset / status.

Activation is deliberately left UNAUTHENTICATED -- an emergency stop
is a safety-positive action and must always be reachable, even by a
caller that has not authenticated, so nothing ever gates *stopping*.
The audit identity for activation is therefore "unauthenticated" -- a
fixed server-side label, not a client-supplied value.

Reset, by contrast, re-enables execution and is a sensitive local
management operation: it requires the local auth token, and the audit
identity is the authenticated Principal -- never a client-supplied
reset_by field.

Audit identity (Phase 4 security correction):
  Reset audit actor is ALWAYS derived from the authenticated Principal
  returned by require_local_auth(). Activation audit identity is the
  fixed server-side constant "unauthenticated". Neither is sourced from
  any request body field. The request models contain no identity fields;
  callers cannot supply or spoof an audit identity.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.permission_log import PermissionAuditLogger
from app.core.database import get_db
from app.emergency.stop import EmergencyStop, EmergencyStopStatus
from app.security.local_auth import Principal, require_local_auth
from app.security.sanitize import normalize_actor

router = APIRouter(prefix="/emergency")

# Fixed audit identity for unauthenticated operations (activation).
# Server-derived constant -- not from the request body.
_UNAUTHENTICATED_PRINCIPAL = "unauthenticated"


class ActivateRequest(BaseModel):
    """Body for emergency-stop activation.

    Only the stop reason is accepted from the caller -- no identity
    field. The reason is sanitized as defense-in-depth to prevent log
    injection via a malicious reason string. Audit identity is always
    the fixed server-side label "unauthenticated".
    """

    reason: str = ""


class ResetRequest(BaseModel):
    """Body for emergency-stop reset.

    No identity field: audit identity is always derived from the
    authenticated Principal, not from the request body.
    """

    pass  # no caller-supplied fields; all identity comes from the token


@router.get("/status", response_model=EmergencyStopStatus)
def status(db: Session = Depends(get_db)) -> EmergencyStopStatus:
    return EmergencyStop(db).status()


@router.post("/activate", response_model=EmergencyStopStatus)
def activate(body: ActivateRequest, db: Session = Depends(get_db)) -> EmergencyStopStatus:
    # Sanitize reason as defense-in-depth against log injection.
    safe_reason = normalize_actor(body.reason) if body.reason else ""
    result = EmergencyStop(db).activate(
        reason=safe_reason,
        activated_by=_UNAUTHENTICATED_PRINCIPAL,
    )
    # Signal cancellation for all active tasks. Import is lazy to avoid
    # circular imports between api.emergency and tasks.manager.
    try:
        from app.tasks.manager import TaskManager as _TaskManager

        _TaskManager(db).cancel_all_running(reason=safe_reason or "emergency_stop", actor="emergency_stop")
    except Exception:  # noqa: BLE001
        # Never let task-cancellation failure prevent the emergency stop itself
        # from being reported as activated.
        pass
    return result


@router.post("/reset", response_model=EmergencyStopStatus)
def reset(
    body: ResetRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth),
) -> EmergencyStopStatus:
    old_status = EmergencyStop(db).status()
    # reset_by is derived from the authenticated principal -- not the body.
    new_status = EmergencyStop(db).reset(reset_by=principal.identity)
    PermissionAuditLogger(db).record(
        actor=principal.identity,  # authenticated identity -- never from body
        action="emergency_reset",
        old_state="engaged" if old_status.engaged else "not_engaged",
        new_state="engaged" if new_status.engaged else "not_engaged",
    )
    return new_status
