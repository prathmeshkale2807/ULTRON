"""
Permission State API surface.

Thin wrapper over PermissionStore -- grant / revoke / check, for both
session and persistent scope. Never accepts or returns anything beyond
category/tool/device/scope/session_id; there is no field here a secret
could hide in.

Phase 4: grant/revoke are sensitive local management operations, so
they require the local auth token (see app/security/local_auth.py) and
are recorded to the permission audit trail (see
app/audit/permission_log.py). A session-scoped request against an
unknown/expired/invalidated session is rejected rather than silently
falling back to persistent-only behavior, so callers can't accidentally
rely on a dead session.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.permission_log import PermissionAuditLogger
from app.core.database import get_db
from app.permissions.models import PermissionScope, PermissionStatus
from app.permissions.store import PermissionStore
from app.security.local_auth import require_local_auth
from app.sessions.manager import SessionManager
from app.tools.models import DeviceType, PermissionCategory

router = APIRouter(prefix="/permissions")


class PermissionRequest(BaseModel):
    category: PermissionCategory
    scope: PermissionScope
    session_id: str | None = None
    tool_name: str | None = None
    device: DeviceType | None = None
    actor: str = "unknown"


class PermissionCheckResponse(BaseModel):
    category: PermissionCategory
    status: PermissionStatus


def _require_valid_session_if_scoped(body: PermissionRequest, db: Session) -> None:
    if body.scope != PermissionScope.SESSION:
        return
    if not body.session_id or not SessionManager(db).is_valid(body.session_id):
        raise HTTPException(status_code=400, detail="unknown, expired, or invalidated session_id")


@router.get("/check", response_model=PermissionCheckResponse)
def check_permission(
    category: PermissionCategory,
    session_id: str | None = None,
    tool_name: str | None = None,
    device: DeviceType | None = None,
    db: Session = Depends(get_db),
) -> PermissionCheckResponse:
    store = PermissionStore(db)
    status = store.check(category, session_id=session_id, tool_name=tool_name, device=device)
    return PermissionCheckResponse(category=category, status=status)


@router.post("/grant")
def grant_permission(
    body: PermissionRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(require_local_auth),
) -> dict:
    _require_valid_session_if_scoped(body, db)
    store = PermissionStore(db)
    old_status = store.check(
        body.category, session_id=body.session_id, tool_name=body.tool_name, device=body.device
    )
    store.grant(
        body.category,
        body.scope,
        session_id=body.session_id,
        tool_name=body.tool_name,
        device=body.device,
    )
    PermissionAuditLogger(db).record(
        actor=body.actor,
        action="grant",
        category=body.category.value,
        tool_name=body.tool_name,
        device=body.device.value if body.device else None,
        old_state=old_status.value,
        new_state=PermissionStatus.GRANTED.value,
    )
    return {"status": "granted"}


@router.post("/revoke")
def revoke_permission(
    body: PermissionRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(require_local_auth),
) -> dict:
    _require_valid_session_if_scoped(body, db)
    store = PermissionStore(db)
    old_status = store.check(
        body.category, session_id=body.session_id, tool_name=body.tool_name, device=body.device
    )
    store.revoke(
        body.category,
        body.scope,
        session_id=body.session_id,
        tool_name=body.tool_name,
        device=body.device,
    )
    PermissionAuditLogger(db).record(
        actor=body.actor,
        action="revoke",
        category=body.category.value,
        tool_name=body.tool_name,
        device=body.device.value if body.device else None,
        old_state=old_status.value,
        new_state=PermissionStatus.DENIED.value,
    )
    return {"status": "revoked"}
