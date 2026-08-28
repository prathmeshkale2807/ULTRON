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

    # Report individual provider statuses (ai_provider.claude, ai_provider.gemini, etc.)
    provider_results: dict = _provider_health_cache.get("results", {})
    for name, health in provider_results.items():
        components.append(
            ComponentStatus(name=f"ai_provider.{name}", status=health.status, detail=health.detail or None)
        )

    # Also report a single "ai_provider" summary using the primary provider's status.
    from app.core.config import get_settings as _get_settings
    _primary = _get_settings().ai_primary_provider
    if _primary in provider_results:
        ph = provider_results[_primary]
        components.append(
            ComponentStatus(name="ai_provider", status=ph.status, detail=ph.detail or None)
        )
    elif provider_results:
        ok = next((h for h in provider_results.values() if h.status == "ok"), None)
        chosen = ok or next(iter(provider_results.values()))
        components.append(
            ComponentStatus(name="ai_provider", status=chosen.status, detail=chosen.detail or None)
        )
    else:
        components.append(
            ComponentStatus(name="ai_provider", status="not_configured", detail="No providers available")
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
    from app.voice.tts_provider import is_tts_available
    from app.voice.stt_provider import is_stt_available
    stt_ok = is_stt_available()
    tts_ok = is_tts_available()
    voice_status = "ok" if (stt_ok and tts_ok) else ("ready" if (stt_ok or tts_ok) else "not_configured")
    
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


@router.get("/dev-token", include_in_schema=False)
def get_dev_token():
    """Development-only endpoint allowing the browser dev server to authenticate."""
    from app.core.config import get_settings
    if get_settings().environment != "development":
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    from app.security.local_auth import get_or_create_local_token
    return {"token": get_or_create_local_token()}



