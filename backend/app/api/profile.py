"""
Active Profile API surface.

GET is public (read-only, mirrors /emergency/status). POST changes the
active Safety Mode profile -- a sensitive local management operation --
so it requires the local auth token and is recorded to the permission
audit trail.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.permission_log import PermissionAuditLogger
from app.core.database import get_db
from app.profile.manager import ProfileManager, ProfileState
from app.safety.models import SafetyMode
from app.security.local_auth import require_local_auth
from app.tools.models import ConfirmationTier, PermissionCategory

router = APIRouter(prefix="/profile")


class SetProfileRequest(BaseModel):
    mode: SafetyMode
    custom_overrides: dict[PermissionCategory, ConfirmationTier] | None = None
    updated_by: str = "unknown"


@router.get("", response_model=ProfileState)
def get_profile(db: Session = Depends(get_db)) -> ProfileState:
    return ProfileManager(db).get()


@router.post("", response_model=ProfileState)
def set_profile(
    body: SetProfileRequest,
    db: Session = Depends(get_db),
    _auth: str = Depends(require_local_auth),
) -> ProfileState:
    manager = ProfileManager(db)
    old_state = manager.get()
    new_state = manager.set(
        body.mode, custom_overrides=body.custom_overrides, updated_by=body.updated_by
    )
    PermissionAuditLogger(db).record(
        actor=body.updated_by,
        action="profile_change",
        old_state=old_state.mode.value,
        new_state=new_state.mode.value,
    )
    return new_state
