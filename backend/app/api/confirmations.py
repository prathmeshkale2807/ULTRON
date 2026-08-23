"""
Confirmation System API surface.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.executor.confirmation import ConfirmationRequest, get_confirmation_broker
from app.security.local_auth import Principal, require_local_auth

router = APIRouter(prefix="/confirmations", tags=["confirmations"])

class ResolveRequest(BaseModel):
    approved: bool
    resolved_by: str = "user"

@router.get("/pending", response_model=list[ConfirmationRequest])
def list_pending(principal: Principal = Depends(require_local_auth)) -> list[ConfirmationRequest]:
    pending = get_confirmation_broker().list_pending()
    return [req for req in pending if req.principal_id == principal.identity]

@router.get("/{request_id}", response_model=ConfirmationRequest)
def get_confirmation(request_id: str, principal: Principal = Depends(require_local_auth)) -> ConfirmationRequest:
    request = get_confirmation_broker().get(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="unknown confirmation request")
    if request.principal_id != principal.identity:
        raise HTTPException(status_code=403, detail="not authorized to view this confirmation request")
    return request

@router.post("/{request_id}/resolve", response_model=ConfirmationRequest)
def resolve_confirmation(
    request_id: str, 
    body: ResolveRequest, 
    principal: Principal = Depends(require_local_auth)
) -> ConfirmationRequest:
    broker = get_confirmation_broker()
    request = broker.get(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="unknown confirmation request")
    if request.principal_id != principal.identity:
        raise HTTPException(status_code=403, detail="not authorized to resolve this confirmation request")
        
    try:
        return broker.resolve(request_id, body.approved, resolved_by=body.resolved_by)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
