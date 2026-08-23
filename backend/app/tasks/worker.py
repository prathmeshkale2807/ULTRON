"""
Task Worker — bounded async execution pool for Phase 5.

Architecture:
  - One asyncio.PriorityQueue holds (priority_weight, submit_time, task_id) tuples.
    Higher priority → lower weight number (min-heap) → dequeued first.
  - One asyncio.Semaphore bounds concurrency to MAX_CONCURRENT_TASKS.
  - Each running task gets an isolated asyncio Task; one failure does NOT
    propagate to sibling tasks.
  - Before dequeuing each task, the worker checks EmergencyStop. If engaged,
    queued tasks won't start (they were already cancelled by
    TaskManager.cancel_all_running() via the emergency stop API route).
  - CancellationToken is created per running task, registered in the
    manager's registry, and checked between tool steps.
  - Pause: worker watches a pause_event; on set, transitions to PAUSED and
    waits on resume_event before continuing.

The worker is started once at application startup (FastAPI lifespan) and
stopped gracefully on shutdown. All DB access uses short-lived sessions
from a session_factory, not a shared long-lived session.

The session_factory is injectable so tests can supply an isolated in-memory
DB without the worker touching the real database file.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from app.executor.executor import ToolExecutionError
from typing import Any

from app.core.logging_config import get_logger
from app.tasks.models import (
    PRIORITY_WEIGHT,
    CancellationToken,
    TaskPriority,
    TaskState,
)

logger = get_logger("tasks.worker")

MAX_CONCURRENT_TASKS = 4

# Type alias for a zero-argument callable that returns an SQLAlchemy Session.
SessionFactory = Callable[[], Any]


class TaskWorker:
    """Process-wide async worker pool.

    Parameters
    ----------
    max_concurrent:
        Maximum number of tasks that may run simultaneously.
    session_factory:
        Zero-argument callable that returns a fresh SQLAlchemy Session.
        Defaults to the application's shared SessionLocal, but tests supply
        their own factory so no real DB file is touched.
    """

    def __init__(
        self,
        max_concurrent: int = MAX_CONCURRENT_TASKS,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._session_factory = session_factory  # None → resolved lazily at first use
        self._queue: asyncio.PriorityQueue[tuple[int, float, str]] = asyncio.PriorityQueue()
        self._semaphore: asyncio.Semaphore | None = None
        self._running = False
        self._dispatcher_task: asyncio.Task[None] | None = None

    def _get_session_factory(self) -> SessionFactory:
        if self._session_factory is not None:
            return self._session_factory
        # Lazy import so the module is importable even before the app engine
        # is fully initialised (e.g. during test collection).
        from app.core.database import SessionLocal

        return SessionLocal

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._dispatcher_task = asyncio.create_task(
            self._dispatch_loop(), name="task_worker_dispatcher"
        )
        logger.info("TaskWorker started (max_concurrent=%d)", self._max_concurrent)

    async def stop(self) -> None:
        self._running = False
        if self._dispatcher_task and not self._dispatcher_task.done():
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
        logger.info("TaskWorker stopped")

    async def submit(self, task_id: str, priority: TaskPriority = TaskPriority.NORMAL) -> None:
        """Enqueue a task_id for execution. Higher priority = dequeued sooner."""
        # PriorityQueue is a min-heap; negate weight so URGENT (3) → -3 sorts first.
        weight = -PRIORITY_WEIGHT[priority]
        await self._queue.put((weight, time.monotonic(), task_id))
        logger.info(
            "Task submitted to worker task_id=%s priority=%s", task_id, priority.value
        )

    async def _dispatch_loop(self) -> None:
        """Main dispatcher: dequeue tasks and launch them as isolated asyncio tasks."""
        while self._running:
            try:
                try:
                    _weight, _ts, task_id = await asyncio.wait_for(
                        self._queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # Check emergency stop BEFORE acquiring the semaphore.
                if _is_emergency_stop_engaged(self._get_session_factory()):
                    logger.warning(
                        "Emergency stop engaged; skipping task_id=%s "
                        "(already cancelled by cancel_all_running).",
                        task_id,
                    )
                    self._queue.task_done()
                    continue

                assert self._semaphore is not None
                await self._semaphore.acquire()
                asyncio.create_task(
                    self._run_task_isolated(task_id),
                    name=f"task_{task_id[:8]}",
                )
                self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                logger.exception("Unexpected error in task dispatch loop")

    async def _run_task_isolated(self, task_id: str) -> None:
        """Run a single task; always releases the semaphore on exit."""
        assert self._semaphore is not None
        try:
            await _execute_task(task_id, session_factory=self._get_session_factory())
        except Exception:  # noqa: BLE001
            logger.exception("Unhandled exception while running task_id=%s", task_id)
        finally:
            self._semaphore.release()


# ---------------------------------------------------------------------------
# Task execution logic
# ---------------------------------------------------------------------------


async def _execute_task(task_id: str, *, session_factory: SessionFactory) -> None:
    """Drive a task through its lifecycle, using the provided session_factory."""
    import json

    from app.core.database import TaskRecord
    from app.tasks import manager as mgr_module
    from app.tasks.models import CancellationToken

    db = session_factory()
    try:
        row = db.get(TaskRecord, task_id)
        if row is None:
            logger.error("Worker: task_id=%s not found in DB", task_id)
            return

        current_state = TaskState(row.state)
        if current_state not in {TaskState.QUEUED, TaskState.PLANNING}:
            logger.info(
                "Worker: task_id=%s already in state=%s, skipping", task_id, row.state
            )
            return

        manager = mgr_module.TaskManager(db)

        token = mgr_module.get_token(task_id)
        if token is None:
            token = CancellationToken()
            mgr_module.register_token(task_id, token)
        
        pause_event, resume_event = mgr_module.register_pause_resume_events(task_id)

        try:
            if current_state == TaskState.QUEUED:
                manager.transition_state(task_id, TaskState.PLANNING, actor="worker")
            manager.transition_state(task_id, TaskState.RUNNING, actor="worker")
            
            db.expire(row)
            row = db.get(TaskRecord, task_id)
            tools_requested: list[str] = json.loads(row.tools_requested or "[]")

            for step in tools_requested:
                if isinstance(step, str):
                    tool_name = step
                    arguments = {}
                else:
                    tool_name = step.get("tool_name")
                    arguments = step.get("arguments", {})

                if token.is_cancel_requested():
                    manager.transition_state(task_id, TaskState.CANCELLED, actor="worker")
                    return

                if pause_event.is_set():
                    pause_event.clear()
                    manager.transition_state(task_id, TaskState.PAUSED, actor="worker")
                    await resume_event.wait()
                    resume_event.clear()
                    manager.transition_state(task_id, TaskState.RUNNING, actor="worker")

                if _is_emergency_stop_engaged_db(db):
                    manager.transition_state(
                        task_id,
                        TaskState.CANCELLED,
                        error_summary="cancelled: emergency stop engaged",
                        actor="worker",
                    )
                    return

                mgr_module.TaskAuditLogger(db).record(
                    task_id=task_id,
                    event="tool_step",
                    detail=f"tool={tool_name}",
                    actor="worker",
                )
                logger.info("Task step executing: task_id=%s tool=%s args=%s", task_id, tool_name, arguments)

                from app.executor.executor import ToolExecutor, ToolExecutionError
                from app.tools.registry import get_registry
                registry = get_registry()
                executor = ToolExecutor(db=db, registry=registry)
                
                from app.tools.models import DeviceType
                target_device_str = step.get("target_device") if isinstance(step, dict) else None
                device = DeviceType(target_device_str) if target_device_str else DeviceType.PC
                
                # Check idempotency
                is_idempotent = True
                try:
                    tool_def = registry.get(tool_name)
                    is_idempotent = tool_def.is_idempotent
                except Exception:
                    pass
                
                result = await executor.execute(
                    tool_name=tool_name,
                    arguments=arguments,
                    target_device=device,
                    principal_id=row.principal_id,
                    session_id=row.session_id,
                    task_id=task_id,
                )
                
                if not result.success:
                    fail_state = TaskState.FAILED if is_idempotent else TaskState.NEEDS_RECONCILIATION
                    manager.transition_state(
                        task_id, 
                        fail_state, 
                        error_summary=f"Step {tool_name} failed: {result.error}",
                        actor="worker"
                    )
                    return

            # All steps done
            manager.transition_state(task_id, TaskState.VERIFYING, actor="worker")
            manager.transition_state(task_id, TaskState.COMPLETED, actor="worker")

        except asyncio.CancelledError:
            _safe_transition(manager, task_id, TaskState.CANCELLED)
            raise
        except ToolExecutionError as exc:
            logger.warning("Task rejected task_id=%s: %s", task_id, exc)
            _safe_transition(manager, task_id, TaskState.FAILED, error_summary=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Task failed task_id=%s", task_id)
            # Default to NEEDS_RECONCILIATION for unknown crash during execution
            _safe_transition(manager, task_id, TaskState.NEEDS_RECONCILIATION, error_summary=str(exc))
        finally:
            mgr_module.unregister_token(task_id)

    finally:
        db.close()


def _safe_transition(
    manager: Any,
    task_id: str,
    state: TaskState,
    error_summary: str | None = None,
) -> None:
    try:
        manager.transition_state(task_id, state, error_summary=error_summary, actor="worker")
    except Exception:  # noqa: BLE001
        pass


def _is_emergency_stop_engaged(session_factory: SessionFactory) -> bool:
    from app.emergency.stop import EmergencyStop

    db = session_factory()
    try:
        return EmergencyStop(db).is_engaged()
    except Exception:  # noqa: BLE001
        return False
    finally:
        db.close()


def _is_emergency_stop_engaged_db(db: Any) -> bool:
    from app.emergency.stop import EmergencyStop

    try:
        return EmergencyStop(db).is_engaged()
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_worker: TaskWorker | None = None


def get_task_worker() -> TaskWorker:
    global _worker
    if _worker is None:
        _worker = TaskWorker()
    return _worker


def reset_task_worker() -> None:
    global _worker
    _worker = None
