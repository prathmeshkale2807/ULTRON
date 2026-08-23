from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.automations.schemas import AutomationCreate, AutomationUpdate, AutomationResponse, AutomationRunResponse
from app.automations.manager import AutomationManager, AutomationError
from app.automations.models import AutomationRecord, AutomationRunRecord
from sqlalchemy import select
from app.security.local_auth import Principal, require_local_auth

router = APIRouter()

@router.post("/", response_model=AutomationResponse)
def create_automation(
    data: AutomationCreate, 
    db: Session = Depends(get_db), 
    principal: Principal = Depends(require_local_auth)
):
    mgr = AutomationManager(db)
    try:
        record = mgr.create_automation(principal.identity, data)
        return record
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except AutomationError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{automation_id}", response_model=AutomationResponse)
def get_automation(
    automation_id: str, 
    db: Session = Depends(get_db), 
    principal: Principal = Depends(require_local_auth)
):
    mgr = AutomationManager(db)
    try:
        return mgr.get_automation(principal.identity, automation_id)
    except AutomationError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/{automation_id}", response_model=AutomationResponse)
def update_automation(
    automation_id: str, 
    data: AutomationUpdate, 
    db: Session = Depends(get_db), 
    principal: Principal = Depends(require_local_auth)
):
    mgr = AutomationManager(db)
    try:
        return mgr.update_automation(principal.identity, automation_id, data)
    except AutomationError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_automation(
    automation_id: str, 
    db: Session = Depends(get_db), 
    principal: Principal = Depends(require_local_auth)
):
    mgr = AutomationManager(db)
    try:
        mgr.delete_automation(principal.identity, automation_id)
    except AutomationError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/{automation_id}/runs", response_model=List[AutomationRunResponse])
def list_runs(
    automation_id: str, 
    db: Session = Depends(get_db), 
    principal: Principal = Depends(require_local_auth)
):
    mgr = AutomationManager(db)
    try:
        # Verify ownership
        mgr.get_automation(principal.identity, automation_id)
        runs = db.execute(
            select(AutomationRunRecord)
            .where(AutomationRunRecord.automation_id == automation_id)
            .order_by(AutomationRunRecord.scheduled_for.desc())
        ).scalars().all()
        return runs
    except AutomationError as e:
        raise HTTPException(status_code=404, detail=str(e))
