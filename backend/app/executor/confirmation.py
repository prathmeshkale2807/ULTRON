"""
Confirmation System.

A ConfirmationRequest is the structured object a future desktop UI will
render as a prompt. Phase 3 builds the backend/API model only -- no
polished UI -- so the shape below is what a UI integration would bind
to directly: action, target device, reason, consequence, risk, tool.

ConfirmationBroker supports two resolution paths so both real usage and
tests are first-class:
  1. Out-of-band resolution (the real desktop-UI flow): create() returns
     a pending request; some other caller (an API endpoint) later calls
     resolve(request_id, approved). Anyone awaiting that request wakes
     up.
  2. Synchronous resolver callback (used by tests and any future
     fully-automated policy): the caller of wait_for_resolution can pass
     a callback that decides immediately instead of waiting on the
     broker.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from app.core.logging_config import get_logger
from app.tools.models import DeviceType, RiskLevel

logger = get_logger("executor.confirmation")


class ConfirmationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


class ConfirmationRequest(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    principal_id: str
    session_id: str | None = None
    task_id: str | None = None
    tool_name: str
    target_device: DeviceType
    action: str
    reason: str
    important_consequence: str
    risk: RiskLevel
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: datetime | None = None
    resolved_by: str | None = None


class ConfirmationBroker:
    def __init__(self) -> None:
        self._requests: dict[str, ConfirmationRequest] = {}
        self._events: dict[str, asyncio.Event] = {}

    def create(
        self,
        *,
        principal_id: str,
        session_id: str | None = None,
        task_id: str | None = None,
        tool_name: str,
        target_device: DeviceType,
        action: str,
        reason: str,
        important_consequence: str,
        risk: RiskLevel,
    ) -> ConfirmationRequest:
        request = ConfirmationRequest(
            principal_id=principal_id,
            session_id=session_id,
            task_id=task_id,
            tool_name=tool_name,
            target_device=target_device,
            action=action,
            reason=reason,
            important_consequence=important_consequence,
            risk=risk,
        )
        self._requests[request.id] = request
        self._events[request.id] = asyncio.Event()
        logger.info("Confirmation requested: id=%s tool=%s", request.id, tool_name)
        return request

    def resolve(
        self, request_id: str, approved: bool, *, resolved_by: str = "user"
    ) -> ConfirmationRequest:
        request = self._requests.get(request_id)
        if request is None:
            raise KeyError(f"unknown confirmation request: {request_id}")
        if request.status != ConfirmationStatus.PENDING:
            return request
        request.status = ConfirmationStatus.APPROVED if approved else ConfirmationStatus.DENIED
        request.resolved_at = datetime.now(timezone.utc)
        request.resolved_by = resolved_by
        event = self._events.get(request_id)
        if event is not None:
            event.set()
        logger.info(
            "Confirmation resolved: id=%s status=%s by=%s",
            request_id,
            request.status.value,
            resolved_by,
        )
        return request

    async def wait_for_resolution(
        self, request_id: str, *, timeout_seconds: float = 120.0
    ) -> ConfirmationRequest:
        event = self._events.get(request_id)
        request = self._requests[request_id]
        if event is None:
            return request
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            if request.status == ConfirmationStatus.PENDING:
                request.status = ConfirmationStatus.TIMED_OUT
                request.resolved_at = datetime.now(timezone.utc)
                logger.warning("Confirmation timed out: id=%s", request_id)
        return self._requests[request_id]

    def get(self, request_id: str) -> ConfirmationRequest | None:
        return self._requests.get(request_id)

    def list_pending(self) -> list[ConfirmationRequest]:
        return [r for r in self._requests.values() if r.status == ConfirmationStatus.PENDING]


_default_broker = ConfirmationBroker()


def get_confirmation_broker() -> ConfirmationBroker:
    """Process-wide default broker, so an API-resolved confirmation is
    visible to the ToolExecutor instance that's awaiting it. Tests that
    need isolation should construct their own ConfirmationBroker()."""
    return _default_broker
