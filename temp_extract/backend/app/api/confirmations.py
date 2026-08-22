"""
Confirmation System API surface.

This is the backend model a future desktop UI binds to: list pending
confirmation requests (action / target device / reason / important
consequence / risk / tool -- exactly the structured fields the spec
requires) and resolve one. No polished UI here, just the API model.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.executor.confirmation import ConfirmationRequest, get_confirmation_broker

router = APIRouter(prefix="/confirmations")


class ResolveRequest(BaseModel):
    approved: bool
    resolved_by: str = "user"


@router.get("/pending", response_model=list[ConfirmationRequest])
def list_pending() -> list[ConfirmationRequest]:
    return get_confirmation_broker().list_pending()


@router.get("/{request_id}", response_model=ConfirmationRequest)
def get_confirmation(request_id: str) -> ConfirmationRequest:
    request = get_confirmation_broker().get(request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="unknown confirmation request")
    return request


@router.post("/{request_id}/resolve", response_model=ConfirmationRequest)
def resolve_confirmation(request_id: str, body: ResolveRequest) -> ConfirmationRequest:
    try:
        return get_confirmation_broker().resolve(
            request_id, body.approved, resolved_by=body.resolved_by
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
