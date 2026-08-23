"""
Task domain models for Phase 5.

Defines:
  TaskState      -- the full lifecycle state machine
  TaskPriority   -- scheduling priority (never bypasses SafetyGate)
  CancellationToken -- cooperative cancellation primitive
  InvalidTransitionError -- raised on illegal state transitions

State machine (terminal states have no outbound edges):

    QUEUED
      → PLANNING, CANCELLED

    PLANNING
      → WAITING_FOR_PERMISSION, RUNNING, FAILED, CANCELLED

    WAITING_FOR_PERMISSION
      → PLANNING, RUNNING, FAILED, CANCELLED

    RUNNING
      → PAUSED, VERIFYING, COMPLETED, FAILED, CANCELLED

    PAUSED
      → RUNNING, CANCELLED, FAILED

    VERIFYING
      → COMPLETED, FAILED, CANCELLED

    COMPLETED  (terminal)
    FAILED     (terminal)
    CANCELLED  (terminal)

Priority ordering (higher number = higher scheduling priority):
    BACKGROUND < NORMAL < FOREGROUND < URGENT
"""

from __future__ import annotations

import asyncio
import threading
from enum import Enum


class TaskState(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    WAITING_FOR_PERMISSION = "waiting_for_permission"
    RUNNING = "running"
    PAUSED = "paused"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_RECONCILIATION = "needs_reconciliation"


class TaskPriority(str, Enum):
    BACKGROUND = "background"
    NORMAL = "normal"
    FOREGROUND = "foreground"
    URGENT = "urgent"


# Numeric weight for priority ordering in the queue.
PRIORITY_WEIGHT: dict[TaskPriority, int] = {
    TaskPriority.BACKGROUND: 0,
    TaskPriority.NORMAL: 1,
    TaskPriority.FOREGROUND: 2,
    TaskPriority.URGENT: 3,
}

# Terminal states — no transitions out.
TERMINAL_STATES: frozenset[TaskState] = frozenset(
    {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.NEEDS_RECONCILIATION}
)

# Allowed transitions: source → set of legal targets.
VALID_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.QUEUED: frozenset({TaskState.PLANNING, TaskState.CANCELLED}),
    TaskState.PLANNING: frozenset(
        {
            TaskState.WAITING_FOR_PERMISSION,
            TaskState.RUNNING,
            TaskState.FAILED,
            TaskState.CANCELLED,
            TaskState.NEEDS_RECONCILIATION,
        }
    ),
    TaskState.WAITING_FOR_PERMISSION: frozenset(
        {TaskState.PLANNING, TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.RUNNING: frozenset(
        {
            TaskState.PAUSED,
            TaskState.VERIFYING,
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
            TaskState.NEEDS_RECONCILIATION,
        }
    ),
    TaskState.PAUSED: frozenset({TaskState.RUNNING, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.VERIFYING: frozenset(
        {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.NEEDS_RECONCILIATION}
    ),
    # Terminal — empty sets, but keep them in the dict for exhaustive lookup.
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
    TaskState.NEEDS_RECONCILIATION: frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not permitted by the state machine."""

    def __init__(self, from_state: TaskState, to_state: TaskState) -> None:
        super().__init__(
            f"Invalid task state transition: {from_state.value!r} → {to_state.value!r}"
        )
        self.from_state = from_state
        self.to_state = to_state


def validate_transition(from_state: TaskState, to_state: TaskState) -> None:
    """Raise InvalidTransitionError if the transition is not in VALID_TRANSITIONS."""
    allowed = VALID_TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed:
        raise InvalidTransitionError(from_state, to_state)


class CancellationToken:
    """Cooperative cancellation primitive.

    Workers check `is_cancel_requested()` between stages (not inside a
    handler's execution -- we never kill a running coroutine mid-flight).
    Both an asyncio.Event (for async waiters) and a threading.Event (for
    any future sync worker threads) are maintained.

    Usage:
        # In the task owner / API handler:
        token.request_cancel()

        # In the worker, between tool steps:
        if token.is_cancel_requested():
            raise asyncio.CancelledError(...)

        # Or await cancellation:
        await token.wait_for_cancel(timeout=5.0)
    """

    def __init__(self) -> None:
        self._async_event: asyncio.Event | None = None
        self._sync_event = threading.Event()
        self._requested = False

    def _get_async_event(self) -> asyncio.Event:
        # Lazily created because the event must be created inside a running
        # event loop; the token itself may be created before one exists.
        if self._async_event is None:
            self._async_event = asyncio.Event()
        return self._async_event

    def request_cancel(self) -> None:
        """Signal that cancellation has been requested. Idempotent."""
        self._requested = True
        self._sync_event.set()
        # Try to set the async event if a loop is running.
        try:
            self._get_async_event().set()
        except RuntimeError:
            pass  # no running event loop -- sync_event is already set

    def is_cancel_requested(self) -> bool:
        """Returns True if cancellation has been requested."""
        return self._requested

    async def wait_for_cancel(self, *, timeout: float | None = None) -> bool:
        """Async wait until cancellation is requested or timeout expires.
        Returns True if cancellation was requested, False if timeout."""
        try:
            await asyncio.wait_for(self._get_async_event().wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return self._requested
