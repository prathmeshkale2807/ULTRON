"""
Task Manager — Phase 5 core.

Responsibilities:
  - Create tasks (returns a TaskRecord with state=QUEUED)
  - Enforce task ownership (session_id must match on get/cancel/pause/resume)
  - Enforce valid state transitions
  - Write task audit entries for every lifecycle event
  - Provide cancel_all_running() for emergency-stop integration
  - Never bypass SafetyGate, PermissionStore, or ToolExecutor

The Task Manager does NOT own the worker pool -- that lives in
app/tasks/worker.py. The manager is the domain/database layer; the
worker is the async execution layer. The API router submits task IDs to
the worker after the manager creates the DB record.

Priority (URGENT > FOREGROUND > NORMAL > BACKGROUND) affects scheduling
order only -- it NEVER bypasses SafetyGate or any confirmation requirement.

Ownership model (Phase 5, single-user):
  Every task is scoped to the session_id that created it. Cross-session
  access raises OwnershipError (→ HTTP 403). System tasks (session_id=None)
  are accessible only to system-level callers (the worker, emergency stop),
  not via the user-facing API.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.audit.log import redact_detail
from app.core.database import TaskAuditEntry, TaskRecord
from app.core.logging_config import get_logger
from app.tasks.audit import TaskAuditLogger
from app.tasks.models import (
    PRIORITY_WEIGHT,
    TERMINAL_STATES,
    CancellationToken,
    InvalidTransitionError,
    TaskPriority,
    TaskState,
    validate_transition,
)

logger = get_logger("tasks.manager")


class TaskNotFoundError(Exception):
    pass


class OwnershipError(Exception):
    """Raised when a caller tries to access a task owned by another session."""


class TaskManager:
    """DB-backed task lifecycle manager.

    All public methods take a `db` argument so each HTTP request or
    worker step gets its own transaction context. There is no long-lived
    state here; the DB is the source of truth.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._audit = TaskAuditLogger(db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        session_id: str | None,
        description: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        tools_requested: list[str] | None = None,
        actor: str | None = None,
    ) -> TaskRecord:
        """Create a new task in QUEUED state and write a 'created' audit event."""
        if actor is None:
            import os
            if os.getenv("ENVIRONMENT") == "test":
                actor = "local"
            else:
                raise ValueError("actor (principal_id) must be provided in production")

        task_id = secrets.token_urlsafe(24)
        safe_desc = redact_detail(description)[:2000]
        tools_json = json.dumps(tools_requested or [])[:1024]
        now = datetime.now(timezone.utc)

        row = TaskRecord(
            task_id=task_id,
            session_id=session_id,
            principal_id=actor,
            description=safe_desc,
            priority=priority.value,
            state=TaskState.QUEUED.value,
            created_at=now,
            tools_requested=tools_json,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)

        self._audit.record(
            task_id=task_id,
            event="created",
            detail=f"priority={priority.value} tools={tools_requested or []}",
            actor=actor,
        )
        logger.info("Task created task_id=%s session=%s priority=%s", task_id, session_id, priority.value)
        return row

    def get(self, task_id: str, *, session_id: str | None) -> TaskRecord:
        """Fetch a task, enforcing ownership. Raises TaskNotFoundError or OwnershipError."""
        row = self.db.get(TaskRecord, task_id)
        if row is None:
            raise TaskNotFoundError(f"task {task_id!r} not found")
        self._check_ownership(row, session_id)
        return row

    def list_tasks(self, *, session_id: str | None) -> list[TaskRecord]:
        """Return all tasks belonging to the given session, newest first."""
        rows = (
            self.db.query(TaskRecord)
            .filter(TaskRecord.session_id == session_id)
            .order_by(TaskRecord.created_at.desc())
            .all()
        )
        return rows

    def cancel(
        self,
        task_id: str,
        *,
        session_id: str | None,
        actor: str,
    ) -> TaskRecord:
        """Request cancellation of a task.

        For QUEUED/PLANNING/WAITING_FOR_PERMISSION tasks, transitions directly
        to CANCELLED. For RUNNING/PAUSED/VERIFYING tasks, sets
        cancellation_requested_at and signals the CancellationToken (via the
        global worker registry). The worker transitions to CANCELLED when it
        next checks the token.
        """
        row = self.get(task_id, session_id=session_id)
        current = TaskState(row.state)

        if current in TERMINAL_STATES:
            # Already terminal — no-op but return current state so the
            # caller gets an accurate picture.
            return row

        now = datetime.now(timezone.utc)

        # Immediately-cancellable states
        if current in {TaskState.QUEUED, TaskState.PLANNING, TaskState.WAITING_FOR_PERMISSION}:
            self._transition(row, TaskState.CANCELLED, actor=actor)
            self._audit.record(
                task_id=task_id,
                event="cancelled",
                detail=f"immediate cancel from state={current.value}",
                actor=actor,
            )
        else:
            # RUNNING / PAUSED / VERIFYING — cooperative cancel
            row.cancellation_requested_at = now
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            self._audit.record(
                task_id=task_id,
                event="cancellation_requested",
                detail=f"cooperative cancel from state={current.value}",
                actor=actor,
            )
            # Signal the token so the worker wakes up promptly.
            _signal_cancellation(task_id)

        logger.info("Task cancel requested task_id=%s from=%s actor=%s", task_id, current.value, actor)
        return row

    def pause(self, task_id: str, *, session_id: str | None, actor: str) -> TaskRecord:
        """Request a pause on a RUNNING task (cooperative between tool steps)."""
        row = self.get(task_id, session_id=session_id)
        current = TaskState(row.state)
        if current != TaskState.RUNNING:
            raise InvalidTransitionError(current, TaskState.PAUSED)
        # Signal the token with pause intent; worker will transition state.
        _signal_pause(task_id)
        self._audit.record(task_id=task_id, event="pause_requested", actor=actor)
        return row

    def resume(self, task_id: str, *, session_id: str | None, actor: str) -> TaskRecord:
        """Resume a PAUSED task."""
        row = self.get(task_id, session_id=session_id)
        current = TaskState(row.state)
        if current != TaskState.PAUSED:
            raise InvalidTransitionError(current, TaskState.RUNNING)
        self._transition(row, TaskState.RUNNING, actor=actor)
        _signal_resume(task_id)
        self._audit.record(task_id=task_id, event="resumed", actor=actor)
        return row

    def transition_state(
        self,
        task_id: str,
        new_state: TaskState,
        *,
        error_summary: str | None = None,
        actor: str = "system",
        detail: str = "",
    ) -> TaskRecord:
        """Transition a task to a new state, validating the transition.

        This is the ONLY method that should write to task.state -- never
        set it directly from outside. Called by the worker and API layer.
        """
        row = self.db.get(TaskRecord, task_id)
        if row is None:
            raise TaskNotFoundError(f"task {task_id!r} not found")
        self._transition(row, new_state, error_summary=error_summary, actor=actor)
        if detail:
            self._audit.record(task_id=task_id, event=f"state_{new_state.value}", detail=detail, actor=actor)
        return row

    def cancel_all_running(self, *, reason: str = "emergency_stop", actor: str = "system") -> int:
        """Signal cancellation for all non-terminal tasks.

        Called by the emergency-stop activate path. Returns the number of
        tasks signalled. Does NOT directly set state -- the worker
        transitions to CANCELLED when it checks the token.
        """
        active_states = [s.value for s in TaskState if s not in TERMINAL_STATES]
        rows = (
            self.db.query(TaskRecord)
            .filter(TaskRecord.state.in_(active_states))
            .all()
        )
        now = datetime.now(timezone.utc)
        count = 0
        for row in rows:
            current = TaskState(row.state)
            if current in {TaskState.QUEUED, TaskState.PLANNING, TaskState.WAITING_FOR_PERMISSION}:
                self._transition(row, TaskState.CANCELLED, actor=actor)
            else:
                row.cancellation_requested_at = now
                self.db.add(row)
                _signal_cancellation(row.task_id)
            self._audit.record(
                task_id=row.task_id,
                event="emergency_stop",
                detail=f"reason={reason}",
                actor=actor,
            )
            count += 1
        if rows:
            self.db.commit()
        logger.warning("Emergency stop: signalled cancellation for %d tasks", count)
        return count

    def get_audit_history(self, task_id: str, *, session_id: str | None) -> list[TaskAuditEntry]:
        """Return audit history for a task (ownership-gated)."""
        self.get(task_id, session_id=session_id)  # ownership check
        return (
            self.db.query(TaskAuditEntry)
            .filter(TaskAuditEntry.task_id == task_id)
            .order_by(TaskAuditEntry.timestamp.asc())
            .all()
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_ownership(self, row: TaskRecord, session_id: str | None) -> None:
        """Raise OwnershipError if the task does not belong to session_id."""
        if row.session_id != session_id:
            raise OwnershipError(
                f"task {row.task_id!r} belongs to a different session"
            )

    def _transition(
        self,
        row: TaskRecord,
        new_state: TaskState,
        *,
        error_summary: str | None = None,
        actor: str = "system",
    ) -> None:
        current = TaskState(row.state)
        validate_transition(current, new_state)  # raises InvalidTransitionError if illegal

        now = datetime.now(timezone.utc)
        row.state = new_state.value

        if new_state == TaskState.RUNNING and row.started_at is None:
            row.started_at = now
        if new_state in TERMINAL_STATES:
            row.completed_at = now
            
        # Phase 8: Clean up browser context on explicit cancellation (task cancel, emergency stop)
        if new_state == TaskState.CANCELLED:
            if row.session_id:
                try:
                    import asyncio
                    from app.browser.manager import get_browser_manager
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(get_browser_manager().close_session(row.session_id))
                    except RuntimeError:
                        pass # No event loop in this thread, skip cleanup (for synchronous tests)
                except Exception:
                    pass

        if error_summary is not None:
            row.error_summary = redact_detail(error_summary)[:512]

        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)

        self._audit.record(
            task_id=row.task_id,
            event="state_change",
            detail=f"{current.value}→{new_state.value}",
            actor=actor,
        )


# ---------------------------------------------------------------------------
# Process-wide cancellation / pause signal registry
# ---------------------------------------------------------------------------
# Maps task_id → CancellationToken so the worker and manager can share
# signals without circular imports. Populated by the worker when a task
# starts running; cleared when the task reaches a terminal state.

_cancellation_tokens: dict[str, CancellationToken] = {}
_pause_events: dict[str, asyncio.Event] = {}
_resume_events: dict[str, asyncio.Event] = {}

import asyncio  # noqa: E402 -- intentional: avoid top-level asyncio at module import time


def register_token(task_id: str, token: CancellationToken) -> None:
    _cancellation_tokens[task_id] = token


def unregister_token(task_id: str) -> None:
    _cancellation_tokens.pop(task_id, None)
    _pause_events.pop(task_id, None)
    _resume_events.pop(task_id, None)


def get_token(task_id: str) -> CancellationToken | None:
    return _cancellation_tokens.get(task_id)


def _signal_cancellation(task_id: str) -> None:
    token = _cancellation_tokens.get(task_id)
    if token is not None:
        token.request_cancel()


def _signal_pause(task_id: str) -> None:
    evt = _pause_events.get(task_id)
    if evt is not None:
        evt.set()


def _signal_resume(task_id: str) -> None:
    evt = _resume_events.get(task_id)
    if evt is not None:
        evt.set()


def register_pause_resume_events(task_id: str) -> tuple[asyncio.Event, asyncio.Event]:
    """Create and register pause/resume events for a task. Returns (pause_event, resume_event)."""
    pe = asyncio.Event()
    re = asyncio.Event()
    _pause_events[task_id] = pe
    _resume_events[task_id] = re
    return pe, re

_volatile_tool_results: dict[str, list[dict]] = {}
