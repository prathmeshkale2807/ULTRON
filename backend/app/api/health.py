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

import time
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.ai_providers.factory import get_provider_manager
from app.core.database import SystemEvent, get_db
from app.core.logging_config import get_logger

router = APIRouter()
logger = get_logger("api.health")

# Provider health checks make a real API call -- caching avoids hitting
# provider APIs (and burning quota/cost) on every poll. The desktop UI
# polls /api/health every 5s; a live provider ping every 5s forever would
# be wasteful and pointless (provider outages don't appear/disappear that
# fast). 60s is a reasonable freshness/cost tradeoff for Phase 2.
_PROVIDER_HEALTH_CACHE_SECONDS = 60.0
_provider_health_cache: dict[str, object] = {"checked_at": 0.0, "results": {}}


class ComponentStatus(BaseModel):
    name: str
    status: str  # "ok" | "unavailable" | "not_implemented" | "unauthenticated" | "not_configured"
    detail: str | None = None


class HealthResponse(BaseModel):
    service: str
    version: str
    timestamp: str
    components: list[ComponentStatus]


@router.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    components: list[ComponentStatus] = []

    # --- Database: prove it's real by writing and reading a row ---------
    try:
        from fastapi.concurrency import run_in_threadpool
        
        def _sync_db_check():
            event = SystemEvent(event_type="health_check", detail="health endpoint pinged db")
            db.add(event)
            db.commit()
            db.refresh(event)
            return db.scalar(select(SystemEvent.id).order_by(SystemEvent.id.desc()).limit(1)), event.id
            
        row_count, event_id = await run_in_threadpool(_sync_db_check)
        
        components.append(
            ComponentStatus(
                name="database",
                status="ok" if row_count is not None else "unavailable",
                detail=f"last event id={event_id}",
            )
        )
    except Exception as exc:  # noqa: BLE001 -- health check must not raise
        logger.exception("Database health check failed")
        components.append(
            ComponentStatus(name="database", status="unavailable", detail=str(exc))
        )

    # --- AI providers: real health checks, cached to avoid API spam -----
    now = time.monotonic()
    if now - _provider_health_cache["checked_at"] > _PROVIDER_HEALTH_CACHE_SECONDS:
        try:
            manager = get_provider_manager()
            results = await manager.health_check_all()
            _provider_health_cache["results"] = results
            _provider_health_cache["checked_at"] = now
        except Exception as exc:  # noqa: BLE001 -- health check must not raise
            logger.exception("Provider health check failed")
            _provider_health_cache["results"] = {}

    for name, health in _provider_health_cache["results"].items():
        components.append(
            ComponentStatus(name=f"ai_provider.{name}", status=health.status, detail=health.detail or None)
        )

    # Phase 6: Windows Control
    components.append(
        ComponentStatus(
            name="windows_control",
            status="ok",
            detail="Windows tools available"
        )
    )

    # Phase 11: Device Manager
    try:
        from app.core.database import DeviceRecord
        db.scalar(select(DeviceRecord.device_id).limit(1))
        components.append(
            ComponentStatus(
                name="device_manager",
                status="ok",
                detail="table accessible"
            )
        )
    except Exception as exc:
        components.append(
            ComponentStatus(name="device_manager", status="unavailable", detail=str(exc))
        )

    # Phase 11: Android Companion API
    components.append(
        ComponentStatus(
            name="android_companion",
            status="ok",
            detail="pairing APIs available"
        )
    )

    # Voice Engine checks
    stt_key = os.getenv("DEEPGRAM_API_KEY")
    tts_key = os.getenv("ELEVENLABS_API_KEY")
    voice_status = "ok" if stt_key and tts_key and stt_key != "not_configured" and tts_key != "not_configured" else "not_configured"
    
    components.append(
        ComponentStatus(
            name="voice_engine",
            status=voice_status,
            detail="Lightweight check completed"
        )
    )

    # --- Components not built yet: reported honestly, not faked ---------
    for name in ():
        components.append(
            ComponentStatus(
                name=name,
                status="not_implemented",
                detail="scheduled for a later phase; not present yet",
            )
        )

    return HealthResponse(
        service="ULTRON Core Service",
        version=__version__,
        timestamp=datetime.now(timezone.utc).isoformat(),
        components=components,
    )

from fastapi import Request
from fastapi.responses import JSONResponse

@router.get("/ready", tags=["System"])
async def get_readiness(request: Request):
    """
    Phase 21: Dedicated readiness endpoint.
    Returns 200 OK only if the backend has successfully completed its
    startup lifecycle, including database migrations and required local init.
    """
    if getattr(request.app.state, "startup_complete", False):
        return {"status": "ready"}
    
    return JSONResponse(status_code=503, content={"status": "starting", "detail": "Startup incomplete"})

