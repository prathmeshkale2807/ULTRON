"""
Permission State API surface.

Thin wrapper over PermissionStore -- grant / revoke / check, for both
session and persistent scope. Never accepts or returns anything beyond
category/tool/device/scope/session_id; there is no field here a secret
could hide in.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.permissions.models import PermissionScope, PermissionStatus
from app.permissions.store import PermissionStore
from app.tools.models import DeviceType, PermissionCategory

router = APIRouter(prefix="/permissions")


class PermissionRequest(BaseModel):
    category: PermissionCategory
    scope: PermissionScope
    session_id: str | None = None
    tool_name: str | None = None
    device: DeviceType | None = None


class PermissionCheckResponse(BaseModel):
    category: PermissionCategory
    status: PermissionStatus


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
def grant_permission(body: PermissionRequest, db: Session = Depends(get_db)) -> dict:
    store = PermissionStore(db)
    store.grant(
        body.category,
        body.scope,
        session_id=body.session_id,
        tool_name=body.tool_name,
        device=body.device,
    )
    return {"status": "granted"}


@router.post("/revoke")
def revoke_permission(body: PermissionRequest, db: Session = Depends(get_db)) -> dict:
    store = PermissionStore(db)
    store.revoke(
        body.category,
        body.scope,
        session_id=body.session_id,
        tool_name=body.tool_name,
        device=body.device,
    )
    return {"status": "revoked"}
