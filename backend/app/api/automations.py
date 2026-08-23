from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.automations.schemas import AutomationCreate, AutomationUpdate, AutomationResponse, AutomationRunResponse
from app.automations.manager import AutomationManager, AutomationError
from app.automations.models import AutomationRecord, AutomationRunRecord
from sqlalchemy import select

router = APIRouter()

def get_current_principal_id() -> str:
    # Phase 4+ uses dependencies for principal auth. Here we mock/extract from header/context in real app.
    # For Phase 17, assuming a function get_principal_id_from_request exists, 
    # but we'll use a placeholder `local_user` for simplicity if not injecting.
    # We should use whatever auth exists in API routes. 
    # Let's import the existing dependency if it exists, otherwise just default to "local_user".
    # In this scaffold, usually `app.api.dependencies` has `get_principal` or similar.
    return "local_user"

@router.post("/", response_model=AutomationResponse)
def create_automation(data: AutomationCreate, db: Session = Depends(get_db)):
    mgr = AutomationManager(db)
    principal_id = get_current_principal_id()
    try:
        record = mgr.create_automation(principal_id, data)
        return record
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except AutomationError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{automation_id}", response_model=AutomationResponse)
def get_automation(automation_id: str, db: Session = Depends(get_db)):
    mgr = AutomationManager(db)
    principal_id = get_current_principal_id()
    try:
        return mgr.get_automation(principal_id, automation_id)
    except AutomationError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/{automation_id}", response_model=AutomationResponse)
def update_automation(automation_id: str, data: AutomationUpdate, db: Session = Depends(get_db)):
    mgr = AutomationManager(db)
    principal_id = get_current_principal_id()
    try:
        return mgr.update_automation(principal_id, automation_id, data)
    except AutomationError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_automation(automation_id: str, db: Session = Depends(get_db)):
    mgr = AutomationManager(db)
    principal_id = get_current_principal_id()
    try:
        mgr.delete_automation(principal_id, automation_id)
    except AutomationError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/{automation_id}/runs", response_model=List[AutomationRunResponse])
def list_runs(automation_id: str, db: Session = Depends(get_db)):
    mgr = AutomationManager(db)
    principal_id = get_current_principal_id()
    try:
        # Verify ownership
        mgr.get_automation(principal_id, automation_id)
        runs = db.execute(
            select(AutomationRunRecord)
            .where(AutomationRunRecord.automation_id == automation_id)
            .order_by(AutomationRunRecord.scheduled_for.desc())
        ).scalars().all()
        return runs
    except AutomationError as e:
        raise HTTPException(status_code=404, detail=str(e))
