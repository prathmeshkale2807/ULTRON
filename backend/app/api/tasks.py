"""
Task Manager API — Phase 5.

All endpoints require local auth (Principal). Ownership is enforced by
TaskManager: a session can only see/cancel its own tasks.

Endpoints:
  POST   /api/tasks                          — create task
  GET    /api/tasks                          — list tasks for session
  GET    /api/tasks/{task_id}                — get task (ownership)
  POST   /api/tasks/{task_id}/cancel         — cancel task (ownership)
  POST   /api/tasks/{task_id}/pause          — pause running task (ownership)
  POST   /api/tasks/{task_id}/resume         — resume paused task (ownership)
  GET    /api/tasks/{task_id}/history        — audit history (ownership)
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import TaskAuditEntry, TaskRecord, get_db
from app.security.local_auth import Principal, require_local_auth
from app.sessions.manager import SessionManager
from app.tasks.manager import OwnershipError, TaskManager, TaskNotFoundError
from app.tasks.models import InvalidTransitionError, TaskPriority, TaskState
from app.tasks.worker import get_task_worker

router = APIRouter(prefix="/tasks")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateTaskRequest(BaseModel):
    description: str = Field(max_length=2000)
    priority: TaskPriority = TaskPriority.NORMAL
    tools_requested: list[str] = Field(default_factory=list, max_length=32)
    # session_id is required so the task has an owner
    session_id: str = Field(min_length=1, max_length=64)


class TaskResponse(BaseModel):
    task_id: str
    session_id: str | None
    description: str
    priority: str
    state: str
    error_summary: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancellation_requested_at: datetime | None
    tools_requested: list[str]
    verification_status: str
    progress_metadata: str | None

    @classmethod
    def from_record(cls, row: TaskRecord) -> "TaskResponse":
        import json

        return cls(
            task_id=row.task_id,
            session_id=row.session_id,
            description=row.description,
            priority=row.priority,
            state=row.state,
            error_summary=row.error_summary,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            cancellation_requested_at=row.cancellation_requested_at,
            tools_requested=json.loads(row.tools_requested or "[]"),
            verification_status=row.verification_status,
            progress_metadata=row.progress_metadata,
        )


class TaskAuditResponse(BaseModel):
    id: int
    timestamp: datetime
    task_id: str
    event: str
    detail: str
    actor: str

    @classmethod
    def from_entry(cls, e: TaskAuditEntry) -> "TaskAuditResponse":
        return cls(
            id=e.id,
            timestamp=e.timestamp,
            task_id=e.task_id,
            event=e.event,
            detail=e.detail,
            actor=e.actor,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_valid_session(session_id: str, db: Session, principal_id: str) -> None:
    """Raise 400 if the session_id is unknown or expired."""
    if not SessionManager(db).is_valid(session_id, principal_id):
        raise HTTPException(
            status_code=400,
            detail="unknown, expired, or invalidated session_id",
        )


def _handle_task_errors(task_id: str):
    """Context manager-like helper; we use try/except inline for clarity."""
    pass  # errors raised inline below


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=TaskResponse)
async def create_task(
    body: CreateTaskRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth),
) -> TaskResponse:
    """Create a new task in QUEUED state and submit it to the worker pool."""
    from fastapi.concurrency import run_in_threadpool

    def _sync_create():
        _require_valid_session(body.session_id, db, principal.identity)
        manager = TaskManager(db)
        return manager.create(
            session_id=body.session_id,
            description=body.description,
            priority=body.priority,
            tools_requested=body.tools_requested,
            actor=principal.identity,
        )

    row = await run_in_threadpool(_sync_create)
    # Submit to worker asynchronously - non-blocking.
    worker = get_task_worker()
    await worker.submit(row.task_id, body.priority)
    return TaskResponse.from_record(row)


@router.get("", response_model=list[TaskResponse])
def list_tasks(
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth),
) -> list[TaskResponse]:
    """List all tasks for the given session."""
    manager = TaskManager(db)
    rows = manager.list_tasks(session_id=session_id, principal_id=principal.identity)
    return [TaskResponse.from_record(r) for r in rows]


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth),
) -> TaskResponse:
    manager = TaskManager(db)
    try:
        row = manager.get(task_id, session_id=session_id, principal_id=principal.identity)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="task not found")
    except OwnershipError:
        raise HTTPException(status_code=403, detail="access denied")
    return TaskResponse.from_record(row)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
def cancel_task(
    task_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth),
) -> TaskResponse:
    manager = TaskManager(db)
    try:
        row = manager.cancel(task_id, session_id=session_id, principal_id=principal.identity, actor=principal.identity)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="task not found")
    except OwnershipError:
        raise HTTPException(status_code=403, detail="access denied")
    return TaskResponse.from_record(row)


@router.post("/{task_id}/pause", response_model=TaskResponse)
def pause_task(
    task_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth),
) -> TaskResponse:
    manager = TaskManager(db)
    try:
        row = manager.pause(task_id, session_id=session_id, principal_id=principal.identity, actor=principal.identity)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="task not found")
    except OwnershipError:
        raise HTTPException(status_code=403, detail="access denied")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return TaskResponse.from_record(row)


@router.post("/{task_id}/resume", response_model=TaskResponse)
def resume_task(
    task_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth),
) -> TaskResponse:
    manager = TaskManager(db)
    try:
        row = manager.resume(task_id, session_id=session_id, principal_id=principal.identity, actor=principal.identity)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="task not found")
    except OwnershipError:
        raise HTTPException(status_code=403, detail="access denied")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return TaskResponse.from_record(row)


@router.get("/{task_id}/history", response_model=list[TaskAuditResponse])
def get_task_history(
    task_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_local_auth),
) -> list[TaskAuditResponse]:
    manager = TaskManager(db)
    try:
        rows = manager.get_audit_history(task_id, session_id=session_id, principal_id=principal.identity)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail="task not found")
    except OwnershipError:
        raise HTTPException(status_code=403, detail="access denied")
    return [TaskAuditResponse.from_entry(r) for r in rows]
