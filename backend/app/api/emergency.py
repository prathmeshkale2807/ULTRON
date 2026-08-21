"""
Emergency Stop API surface.

activate / reset / status only. The actual global keyboard/voice kill
switch is a later phase; this is the backend interface it will call.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.emergency.stop import EmergencyStop, EmergencyStopStatus

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
def reset(body: ResetRequest, db: Session = Depends(get_db)) -> EmergencyStopStatus:
    return EmergencyStop(db).reset(reset_by=body.reset_by)
