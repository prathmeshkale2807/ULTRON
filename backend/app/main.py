"""
ULTRON Core Service -- entrypoint.

Phase 1 scope only: start a FastAPI app, wire up logging + the database,
expose /api/health, and allow the local desktop UI (Tauri, running on
localhost) to talk to it over CORS-permitted local origins.

Run with:
    uvicorn app.main:app --host 127.0.0.1 --port 8756 --reload

Nothing in this file talks to Windows, Android, an AI provider, or the
microphone -- those are separate agents/services added in later phases,
each behind the Tool Registry and Permission Manager once those exist
(Phase 3+). Phase 1 is infrastructure only, by design.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import api_router
from app.core.config import get_settings
from app.core.database import schema_is_current
from app.core.logging_config import configure_logging, get_logger

settings = get_settings()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import sys
    configure_logging()
    logger.info("ULTRON Core Service starting (environment=%s)", settings.environment)
    
    settings.ensure_data_dirs()
    
    import os
    if os.environ.get("ENVIRONMENT") != "test":
        from app.core.database import run_migrations
        try:
            run_migrations()
        except Exception as e:
            logger.critical("Failed to migrate database: %s", e)
            sys.exit(1)
            
        if not schema_is_current():
            logger.critical("Database schema is still out of date after migration attempt. Failing closed.")
            sys.exit(1)
        else:
            logger.info("Database schema up to date at %s", settings.database_url)
    else:
        logger.info("Test environment detected, skipping automatic migrations.")

    # Set readiness state globally (simple flag for the ready endpoint)
    app.state.startup_complete = True

    # Register Windows Tools (Phase 6)
    from app.windows.tools import register_windows_tools
    from app.tools.registry import get_registry
    register_windows_tools(get_registry())

    # Register Email and Calendar Tools (Phase 10)
    from app.tools.email import EMAIL_TOOLS
    from app.tools.calendar import CALENDAR_TOOLS
    for tool in EMAIL_TOOLS:
        get_registry().register(tool, replace=True)
    for tool in CALENDAR_TOOLS:
        get_registry().register(tool, replace=True)

    # Register Android Tools (Phase 11)
    from app.android.tools import ANDROID_TOOLS
    for tool in ANDROID_TOOLS:
        get_registry().register(tool, replace=True)

    # Register Automations Tool (Phase 17)
    from app.automations.tools import AUTOMATION_TOOLS
    for tool in AUTOMATION_TOOLS:
        get_registry().register(tool, replace=True)

    # Start the automations scheduler (Phase 17)
    from app.automations.scheduler import scheduler_engine
    scheduler_engine.start()
    logger.info("Scheduler engine started")

    # Start the task worker pool (Phase 5).
    from app.tasks.worker import get_task_worker

    worker = get_task_worker()
    await worker.start()
    logger.info("Task worker pool started")

    yield

    # Graceful shutdown: stop accepting new tasks and drain.
    await scheduler_engine.stop()
    logger.info("Scheduler engine stopped")
    
    await worker.stop()
    from app.tasks.worker import reset_task_worker
    reset_task_worker()
    logger.info("ULTRON Core Service shutting down")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    lifespan=lifespan,
)

# Local-only CORS: the Tauri desktop shell runs on a local dev origin.
# No external origins are permitted -- this service is not meant to be
# reachable from the public internet in Phase 1 (Remote Mode is deferred).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",  # Tauri dev server default
        "tauri://localhost",  # Tauri production webview origin
        "http://localhost:5173",  # Vite dev server fallback
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "running", "docs": "/docs"}
