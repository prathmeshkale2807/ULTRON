"""
Health-check endpoint.

This is intentionally the first real, end-to-end vertical slice of
ULTRON: request comes in over HTTP, the API layer talks to the real
SQLite database (writes one event row, reads it back), and returns a
real status payload. Nothing here is mocked.

Later phases extend this same endpoint's response shape to report on
the Device Manager, AI Provider Manager, and Voice Engine -- Phase 1
only has the database and the service itself to report on, so that's
all this returns.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.core.database import SystemEvent, get_db
from app.core.logging_config import get_logger

router = APIRouter()
logger = get_logger("api.health")


class ComponentStatus(BaseModel):
    name: str
    status: str  # "ok" | "unavailable" | "not_implemented"
    detail: str | None = None


class HealthResponse(BaseModel):
    service: str
    version: str
    timestamp: str
    components: list[ComponentStatus]


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    components: list[ComponentStatus] = []

    # --- Database: prove it's real by writing and reading a row ---------
    try:
        event = SystemEvent(event_type="health_check", detail="health endpoint pinged db")
        db.add(event)
        db.commit()
        db.refresh(event)

        row_count = db.scalar(select(SystemEvent.id).order_by(SystemEvent.id.desc()).limit(1))
        components.append(
            ComponentStatus(
                name="database",
                status="ok" if row_count is not None else "unavailable",
                detail=f"last event id={event.id}",
            )
        )
    except Exception as exc:  # noqa: BLE001 -- health check must not raise
        logger.exception("Database health check failed")
        components.append(
            ComponentStatus(name="database", status="unavailable", detail=str(exc))
        )

    # --- Components not built yet: reported honestly, not faked ---------
    for name in (
        "ai_provider_manager",
        "device_manager",
        "voice_engine",
        "android_companion",
        "windows_control",
    ):
        components.append(
            ComponentStatus(
                name=name,
                status="not_implemented",
                detail="scheduled for a later phase; not present in Phase 1",
            )
        )

    return HealthResponse(
        service="ULTRON Core Service",
        version=__version__,
        timestamp=datetime.now(timezone.utc).isoformat(),
        components=components,
    )
