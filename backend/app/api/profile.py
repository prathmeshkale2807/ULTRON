"""
Active Profile API surface.

GET is public (read-only). POST changes the active Safety Mode profile
-- a sensitive local management operation -- so it requires the local
auth token and is recorded to the permission audit trail.

Audit identity (Phase 4 security correction):
  The audit actor and the profile updated_by field are ALWAYS derived
  from the authenticated Principal returned by require_local_auth() --
  never from any client-supplied body field. The request model contains
  no updated_by field; callers cannot supply or spoof an audit identity.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.permission_log import PermissionAuditLogger
from app.core.database import get_db
from app.profile.manager import ProfileManager, ProfileState
from app.safety.models import SafetyMode
from app.security.local_auth import Principal, require_local_auth
from app.tools.models import ConfirmationTier, PermissionCategory

router = APIRouter(prefix="/profile")


class SetProfileRequest(BaseModel):
    """Body for profile changes.

    No updated_by / identity field: audit identity is always derived
    from the authenticated Principal, not from the request body.
    """

    mode: SafetyMode
    custom_overrides: dict[PermissionCategory, ConfirmationTier] | None = None


@router.get("", response_model=ProfileState)
def get_profile(db: Session = Depends(get_db)) -> ProfileState:
    return ProfileManager(db).get()


@router.post("", response_model=ProfileState)
def set_profile(
    body: SetProfileRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth),
) -> ProfileState:
    manager = ProfileManager(db)
    old_state = manager.get()
    # updated_by is set to the authenticated principal identity, not any
    # client-supplied value.
    new_state = manager.set(
        body.mode,
        custom_overrides=body.custom_overrides,
        updated_by=principal.identity,
    )
    PermissionAuditLogger(db).record(
        actor=principal.identity,  # authenticated identity -- never from body
        action="profile_change",
        old_state=old_state.mode.value,
        new_state=new_state.mode.value,
    )
    return new_state
