"""
Phase 5 Task Manager tests.

Coverage:
  - Task creation, fields, no secrets stored
  - Task ownership enforcement
  - State machine transitions (valid and invalid)
  - Priority ordering in queue
  - Concurrency: N tasks isolated, one failure doesn't kill others
  - Cancellation before execution (QUEUED → CANCELLED)
  - Cancellation during execution (cooperative token)
  - Cancellation ownership: session A cannot cancel session B's task
  - Emergency stop → queued tasks cancelled
  - Emergency stop → running tasks receive cancellation signal
  - Failed task isolation
  - Audit logging for all key events
  - API-level tests for all endpoints
  - Regression: all previous test patterns still hold (no import breakage)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session(tmp_path: Path):
    """Isolated SQLite DB per test — same pattern as conftest.py."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base

    db_file = tmp_path / "phase5_test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def manager(db_session):
    from app.tasks.manager import TaskManager

    return TaskManager(db_session)


@pytest.fixture()
def client(monkeypatch, tmp_path: Path):
    """Full FastAPI TestClient with isolated DB.

    The module-level `engine` and `SessionLocal` in app.core.database are bound
    once on first import. We must patch them directly so the FastAPI app's
    get_db() dependency uses the tmp DB, not the real one.
    """
    db_file = tmp_path / "test_ultron_p5.db"
    log_dir = tmp_path / "logs"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.ai_providers.factory import get_provider_manager

    get_provider_manager.cache_clear()

    # Patch the module-level singletons so the FastAPI app routes to our tmp DB.
    from sqlalchemy import create_engine as _make_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    import app.core.database as _db_module

    _test_engine = _make_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    _db_module.Base.metadata.create_all(bind=_test_engine)
    _test_session_local = _sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

    monkeypatch.setattr(_db_module, "engine", _test_engine)
    monkeypatch.setattr(_db_module, "SessionLocal", _test_session_local)

    from app.api import health as health_module

    health_module._provider_health_cache["checked_at"] = 0.0
    health_module._provider_health_cache["results"] = {}

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
    get_provider_manager.cache_clear()
    _test_engine.dispose()



def _local_token() -> str:
    from app.security.local_auth import get_or_create_local_token

    return get_or_create_local_token()


def _auth_headers() -> dict:
    return {"X-Ultron-Auth": _local_token()}


def _make_session(client) -> str:
    resp = client.post("/api/sessions")
    assert resp.status_code == 200
    return resp.json()["session_id"]


# ---------------------------------------------------------------------------
# Unit: Task domain models
# ---------------------------------------------------------------------------


def test_task_state_enum_values() -> None:
    from app.tasks.models import TaskState

    assert TaskState.QUEUED.value == "queued"
    assert TaskState.COMPLETED.value == "completed"
    assert TaskState.CANCELLED.value == "cancelled"
    assert TaskState.FAILED.value == "failed"


def test_task_priority_enum_values() -> None:
    from app.tasks.models import PRIORITY_WEIGHT, TaskPriority

    assert PRIORITY_WEIGHT[TaskPriority.URGENT] > PRIORITY_WEIGHT[TaskPriority.FOREGROUND]
    assert PRIORITY_WEIGHT[TaskPriority.FOREGROUND] > PRIORITY_WEIGHT[TaskPriority.NORMAL]
    assert PRIORITY_WEIGHT[TaskPriority.NORMAL] > PRIORITY_WEIGHT[TaskPriority.BACKGROUND]


def test_valid_transitions_accepted() -> None:
    from app.tasks.models import TaskState, validate_transition

    validate_transition(TaskState.QUEUED, TaskState.PLANNING)
    validate_transition(TaskState.PLANNING, TaskState.RUNNING)
    validate_transition(TaskState.RUNNING, TaskState.COMPLETED)
    validate_transition(TaskState.RUNNING, TaskState.FAILED)
    validate_transition(TaskState.RUNNING, TaskState.CANCELLED)
    validate_transition(TaskState.VERIFYING, TaskState.COMPLETED)


def test_invalid_transitions_raise() -> None:
    from app.tasks.models import InvalidTransitionError, TaskState, validate_transition

    with pytest.raises(InvalidTransitionError):
        validate_transition(TaskState.COMPLETED, TaskState.RUNNING)

    with pytest.raises(InvalidTransitionError):
        validate_transition(TaskState.FAILED, TaskState.QUEUED)

    with pytest.raises(InvalidTransitionError):
        validate_transition(TaskState.QUEUED, TaskState.COMPLETED)

    with pytest.raises(InvalidTransitionError):
        validate_transition(TaskState.RUNNING, TaskState.QUEUED)


def test_terminal_states_have_no_outbound_transitions() -> None:
    from app.tasks.models import TERMINAL_STATES, VALID_TRANSITIONS, TaskState

    for state in TERMINAL_STATES:
        assert VALID_TRANSITIONS[state] == frozenset(), (
            f"{state.value} is terminal but has outbound transitions"
        )


# ---------------------------------------------------------------------------
# Unit: CancellationToken
# ---------------------------------------------------------------------------


def test_cancellation_token_initial_state() -> None:
    from app.tasks.models import CancellationToken

    token = CancellationToken()
    assert not token.is_cancel_requested()


def test_cancellation_token_request_cancel() -> None:
    from app.tasks.models import CancellationToken

    token = CancellationToken()
    token.request_cancel()
    assert token.is_cancel_requested()


def test_cancellation_token_idempotent() -> None:
    from app.tasks.models import CancellationToken

    token = CancellationToken()
    token.request_cancel()
    token.request_cancel()  # second call must not raise
    assert token.is_cancel_requested()


async def test_cancellation_token_async_wait() -> None:
    from app.tasks.models import CancellationToken

    token = CancellationToken()

    async def _cancel_after_delay():
        await asyncio.sleep(0.01)
        token.request_cancel()

    asyncio.create_task(_cancel_after_delay())
    result = await token.wait_for_cancel(timeout=2.0)
    assert result is True


async def test_cancellation_token_wait_timeout() -> None:
    from app.tasks.models import CancellationToken

    token = CancellationToken()
    result = await token.wait_for_cancel(timeout=0.01)
    assert result is False
    assert not token.is_cancel_requested()


# ---------------------------------------------------------------------------
# Unit: TaskManager — creation
# ---------------------------------------------------------------------------


def test_create_task_returns_queued_record(manager, db_session) -> None:
    from app.tasks.models import TaskState

    row = manager.create(session_id="sess-001", description="do something", actor="local")
    assert row.task_id
    assert row.state == TaskState.QUEUED.value
    assert row.session_id == "sess-001"
    assert row.description == "do something"
    assert row.priority == "normal"
    assert row.error_summary is None
    assert row.started_at is None
    assert row.completed_at is None
    assert row.cancellation_requested_at is None


def test_create_task_no_secrets_in_description(manager) -> None:
    """Even if someone puts a token-like string in description, redact_detail
    is called. At minimum, the task must be created without crashing."""
    row = manager.create(
        session_id="sess-sec",
        description="token=supersecret123",
        actor="local",
    )
    assert row.task_id
    # The stored description should not contain the literal secret value
    # (redact_detail replaces token=... patterns).
    assert "supersecret123" not in row.description


def test_create_task_writes_audit_entry(manager, db_session) -> None:
    from app.core.database import TaskAuditEntry

    row = manager.create(session_id="sess-002", description="audit test", actor="local")
    entries = db_session.query(TaskAuditEntry).filter_by(task_id=row.task_id).all()
    assert len(entries) == 1
    assert entries[0].event == "created"
    assert entries[0].actor == "local"


def test_create_task_with_custom_priority(manager) -> None:
    from app.tasks.models import TaskPriority

    row = manager.create(session_id="s", description="urgent", priority=TaskPriority.URGENT)
    assert row.priority == "urgent"


def test_create_task_tools_stored_as_json(manager) -> None:
    row = manager.create(session_id="s", description="d", tools_requested=["tool_a", "tool_b"])
    assert json.loads(row.tools_requested) == ["tool_a", "tool_b"]


# ---------------------------------------------------------------------------
# Unit: TaskManager — get / ownership
# ---------------------------------------------------------------------------


def test_get_task_own_session(manager) -> None:
    row = manager.create(session_id="sess-A", description="mine")
    fetched = manager.get(row.task_id, session_id="sess-A")
    assert fetched.task_id == row.task_id


def test_get_task_wrong_session_raises_ownership_error(manager) -> None:
    from app.tasks.manager import OwnershipError

    row = manager.create(session_id="sess-A", description="mine")
    with pytest.raises(OwnershipError):
        manager.get(row.task_id, session_id="sess-B")


def test_get_nonexistent_task_raises_not_found(manager) -> None:
    from app.tasks.manager import TaskNotFoundError

    with pytest.raises(TaskNotFoundError):
        manager.get("no-such-id", session_id="sess-A")


def test_list_tasks_returns_own_session_only(manager) -> None:
    manager.create(session_id="sess-A", description="task A1")
    manager.create(session_id="sess-A", description="task A2")
    manager.create(session_id="sess-B", description="task B1")

    rows_a = manager.list_tasks(session_id="sess-A")
    rows_b = manager.list_tasks(session_id="sess-B")
    assert len(rows_a) == 2
    assert len(rows_b) == 1
    assert all(r.session_id == "sess-A" for r in rows_a)


# ---------------------------------------------------------------------------
# Unit: TaskManager — state transitions
# ---------------------------------------------------------------------------


def test_transition_state_valid(manager) -> None:
    from app.tasks.models import TaskState

    row = manager.create(session_id="s", description="d")
    result = manager.transition_state(row.task_id, TaskState.PLANNING, actor="worker")
    assert result.state == TaskState.PLANNING.value


def test_transition_state_invalid_raises(manager) -> None:
    from app.tasks.models import InvalidTransitionError, TaskState

    row = manager.create(session_id="s", description="d")
    with pytest.raises(InvalidTransitionError):
        manager.transition_state(row.task_id, TaskState.COMPLETED, actor="worker")


def test_transition_to_running_sets_started_at(manager) -> None:
    from app.tasks.models import TaskState

    row = manager.create(session_id="s", description="d")
    manager.transition_state(row.task_id, TaskState.PLANNING, actor="worker")
    result = manager.transition_state(row.task_id, TaskState.RUNNING, actor="worker")
    assert result.started_at is not None


def test_transition_to_completed_sets_completed_at(manager) -> None:
    from app.tasks.models import TaskState

    row = manager.create(session_id="s", description="d")
    manager.transition_state(row.task_id, TaskState.PLANNING)
    manager.transition_state(row.task_id, TaskState.RUNNING)
    manager.transition_state(row.task_id, TaskState.VERIFYING)
    result = manager.transition_state(row.task_id, TaskState.COMPLETED)
    assert result.completed_at is not None


def test_transition_sets_error_summary_on_failure(manager) -> None:
    from app.tasks.models import TaskState

    row = manager.create(session_id="s", description="d")
    manager.transition_state(row.task_id, TaskState.PLANNING)
    manager.transition_state(row.task_id, TaskState.RUNNING)
    result = manager.transition_state(
        row.task_id, TaskState.FAILED, error_summary="handler crashed"
    )
    assert result.error_summary is not None
    assert "handler crashed" in result.error_summary


def test_terminal_state_cannot_transition_further(manager) -> None:
    from app.tasks.models import InvalidTransitionError, TaskState

    row = manager.create(session_id="s", description="d")
    manager.transition_state(row.task_id, TaskState.CANCELLED)
    with pytest.raises(InvalidTransitionError):
        manager.transition_state(row.task_id, TaskState.RUNNING)


# ---------------------------------------------------------------------------
# Unit: Cancellation
# ---------------------------------------------------------------------------


def test_cancel_queued_task_transitions_to_cancelled(manager) -> None:
    from app.tasks.models import TaskState

    row = manager.create(session_id="sess-X", description="cancel me")
    result = manager.cancel(row.task_id, session_id="sess-X", actor="local")
    assert result.state == TaskState.CANCELLED.value


def test_cancel_already_terminal_task_is_noop(manager) -> None:
    from app.tasks.models import TaskState

    row = manager.create(session_id="sess-X", description="done")
    manager.transition_state(row.task_id, TaskState.PLANNING)
    manager.transition_state(row.task_id, TaskState.RUNNING)
    manager.transition_state(row.task_id, TaskState.VERIFYING)
    manager.transition_state(row.task_id, TaskState.COMPLETED)

    # Cancel of a completed task should return the task without error.
    result = manager.cancel(row.task_id, session_id="sess-X", actor="local")
    assert result.state == TaskState.COMPLETED.value


def test_cancel_wrong_session_raises_ownership_error(manager) -> None:
    from app.tasks.manager import OwnershipError

    row = manager.create(session_id="sess-A", description="d")
    with pytest.raises(OwnershipError):
        manager.cancel(row.task_id, session_id="sess-B", actor="local")


def test_cancel_running_task_sets_cancellation_requested_at(manager) -> None:
    from app.tasks.models import TaskState

    row = manager.create(session_id="sess-Y", description="running task")
    manager.transition_state(row.task_id, TaskState.PLANNING)
    manager.transition_state(row.task_id, TaskState.RUNNING)
    result = manager.cancel(row.task_id, session_id="sess-Y", actor="local")
    # State stays RUNNING (cooperative cancel) but timestamp is set.
    assert result.cancellation_requested_at is not None


def test_cancel_running_task_signals_cancellation_token(manager, db_session) -> None:
    from app.tasks.manager import CancellationToken, register_token
    from app.tasks.models import TaskState

    row = manager.create(session_id="sess-Z", description="signal test")
    manager.transition_state(row.task_id, TaskState.PLANNING)
    manager.transition_state(row.task_id, TaskState.RUNNING)

    token = CancellationToken()
    register_token(row.task_id, token)
    assert not token.is_cancel_requested()

    manager.cancel(row.task_id, session_id="sess-Z", actor="local")
    assert token.is_cancel_requested()


# ---------------------------------------------------------------------------
# Unit: cancel_all_running (emergency stop)
# ---------------------------------------------------------------------------


def test_cancel_all_running_cancels_queued_tasks(manager) -> None:
    from app.tasks.models import TaskState

    t1 = manager.create(session_id="s", description="t1")
    t2 = manager.create(session_id="s", description="t2")

    count = manager.cancel_all_running(reason="emergency_stop")
    assert count == 2

    r1 = manager.get(t1.task_id, session_id="s")
    r2 = manager.get(t2.task_id, session_id="s")
    assert r1.state == TaskState.CANCELLED.value
    assert r2.state == TaskState.CANCELLED.value


def test_cancel_all_running_signals_running_task_token(manager) -> None:
    from app.tasks.manager import CancellationToken, register_token
    from app.tasks.models import TaskState

    row = manager.create(session_id="s", description="running")
    manager.transition_state(row.task_id, TaskState.PLANNING)
    manager.transition_state(row.task_id, TaskState.RUNNING)

    token = CancellationToken()
    register_token(row.task_id, token)

    manager.cancel_all_running(reason="emergency_stop")
    assert token.is_cancel_requested()


def test_cancel_all_running_does_not_touch_terminal_tasks(manager) -> None:
    from app.tasks.models import TaskState

    row = manager.create(session_id="s", description="done")
    manager.transition_state(row.task_id, TaskState.PLANNING)
    manager.transition_state(row.task_id, TaskState.RUNNING)
    manager.transition_state(row.task_id, TaskState.VERIFYING)
    manager.transition_state(row.task_id, TaskState.COMPLETED)

    count = manager.cancel_all_running()
    assert count == 0


def test_cancel_all_running_writes_emergency_stop_audit_events(manager, db_session) -> None:
    from app.core.database import TaskAuditEntry

    row = manager.create(session_id="s", description="d")
    manager.cancel_all_running(reason="test_stop")

    entries = (
        db_session.query(TaskAuditEntry)
        .filter_by(task_id=row.task_id, event="emergency_stop")
        .all()
    )
    assert len(entries) == 1
    assert "test_stop" in entries[0].detail


# ---------------------------------------------------------------------------
# Unit: Audit history
# ---------------------------------------------------------------------------


def test_get_audit_history_returns_events_in_order(manager, db_session) -> None:
    from app.tasks.models import TaskState

    row = manager.create(session_id="sess-H", description="history test")
    manager.transition_state(row.task_id, TaskState.PLANNING)
    manager.transition_state(row.task_id, TaskState.RUNNING)

    history = manager.get_audit_history(row.task_id, session_id="sess-H")
    events = [e.event for e in history]
    assert "created" in events
    assert "state_change" in events


def test_get_audit_history_wrong_session_raises_ownership_error(manager) -> None:
    from app.tasks.manager import OwnershipError

    row = manager.create(session_id="sess-A", description="d")
    with pytest.raises(OwnershipError):
        manager.get_audit_history(row.task_id, session_id="sess-B")


# ---------------------------------------------------------------------------
# Unit: Failed task isolation
# ---------------------------------------------------------------------------


def test_failed_task_does_not_affect_other_tasks(manager) -> None:
    from app.tasks.models import TaskState

    good = manager.create(session_id="s", description="good task")
    bad = manager.create(session_id="s", description="failing task")

    # Fail the bad task
    manager.transition_state(bad.task_id, TaskState.PLANNING)
    manager.transition_state(bad.task_id, TaskState.RUNNING)
    manager.transition_state(bad.task_id, TaskState.FAILED, error_summary="crash")

    # Good task is unaffected
    good_row = manager.get(good.task_id, session_id="s")
    assert good_row.state == TaskState.QUEUED.value


# ---------------------------------------------------------------------------
# Async: Worker integration (light)
# ---------------------------------------------------------------------------


async def test_task_worker_starts_and_stops() -> None:
    from app.tasks.worker import TaskWorker

    worker = TaskWorker(max_concurrent=2)
    await worker.start()
    assert worker._running
    await worker.stop()
    assert not worker._running


async def test_task_worker_completes_simple_task(tmp_path: Path) -> None:
    """End-to-end: create a task with no tools, submit to worker, verify COMPLETED."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base, TaskRecord
    from app.tasks.manager import TaskManager
    from app.tasks.models import TaskState
    from app.tasks.worker import TaskWorker

    db_file = tmp_path / "worker_test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    db = Session()
    manager = TaskManager(db)
    row = manager.create(session_id="sess-W", description="empty task")
    task_id = row.task_id
    db.close()

    # Inject the test session factory so worker never touches real DB.
    worker = TaskWorker(max_concurrent=1, session_factory=Session)
    await worker.start()
    await worker.submit(task_id)
    await asyncio.sleep(0.5)
    await worker.stop()

    db2 = Session()
    try:
        final = db2.get(TaskRecord, task_id)
        assert final is not None
        assert final.state == TaskState.COMPLETED.value
    finally:
        db2.close()
        engine.dispose()


async def test_worker_cancels_task_when_token_is_set(tmp_path: Path) -> None:
    """Worker checks CancellationToken between steps → transitions to CANCELLED."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base, TaskRecord
    from app.tasks import manager as mgr_module
    from app.tasks.manager import TaskManager
    from app.tasks.models import CancellationToken, TaskState
    from app.tasks.worker import TaskWorker

    db_file = tmp_path / "cancel_test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    db = Session()
    manager = TaskManager(db)
    row = manager.create(session_id="s", description="d", tools_requested=["mock_tool"])
    task_id = row.task_id
    db.close()

    # Pre-register a cancelled token — worker will see it on first step.
    token = CancellationToken()
    token.request_cancel()
    mgr_module.register_token(task_id, token)

    worker = TaskWorker(max_concurrent=1, session_factory=Session)
    await worker.start()
    await worker.submit(task_id)
    await asyncio.sleep(0.5)
    await worker.stop()

    db2 = Session()
    try:
        final = db2.get(TaskRecord, task_id)
        # CANCELLED (token caught before first step).
        assert final.state == TaskState.CANCELLED.value
    finally:
        db2.close()
        engine.dispose()


async def test_worker_one_failure_does_not_kill_other_tasks(tmp_path: Path) -> None:
    """A bad task_id fails silently while a good task still completes."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base, TaskRecord
    from app.tasks.manager import TaskManager
    from app.tasks.models import TaskState
    from app.tasks.worker import TaskWorker

    db_file = tmp_path / "isolation_test.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    db = Session()
    manager = TaskManager(db)
    good = manager.create(session_id="s", description="good task")
    good_task_id = good.task_id
    db.close()

    worker = TaskWorker(max_concurrent=2, session_factory=Session)
    await worker.start()
    await worker.submit("nonexistent-task-id-xyz")
    await worker.submit(good_task_id)
    await asyncio.sleep(0.5)
    await worker.stop()

    db2 = Session()
    try:
        final_good = db2.get(TaskRecord, good_task_id)
        assert final_good is not None
        assert final_good.state == TaskState.COMPLETED.value
    finally:
        db2.close()
        engine.dispose()



# ---------------------------------------------------------------------------
# API-level tests
# ---------------------------------------------------------------------------


def test_api_create_task_returns_201_style_200(client) -> None:
    session_id = _make_session(client)
    resp = client.post(
        "/api/tasks",
        json={"description": "api task", "session_id": session_id},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "queued"
    assert data["session_id"] == session_id
    assert data["task_id"]


def test_api_create_task_requires_auth(client) -> None:
    session_id = _make_session(client)
    resp = client.post(
        "/api/tasks",
        json={"description": "no auth", "session_id": session_id},
    )
    assert resp.status_code == 401


def test_api_create_task_requires_valid_session(client) -> None:
    resp = client.post(
        "/api/tasks",
        json={"description": "bad session", "session_id": "does-not-exist"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 400


def test_api_get_task_own_session(client) -> None:
    session_id = _make_session(client)
    create_resp = client.post(
        "/api/tasks",
        json={"description": "get me", "session_id": session_id},
        headers=_auth_headers(),
    )
    task_id = create_resp.json()["task_id"]

    resp = client.get(
        f"/api/tasks/{task_id}",
        params={"session_id": session_id},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["task_id"] == task_id


def test_api_get_task_wrong_session_is_403(client) -> None:
    session_a = _make_session(client)
    session_b = _make_session(client)
    create_resp = client.post(
        "/api/tasks",
        json={"description": "mine", "session_id": session_a},
        headers=_auth_headers(),
    )
    task_id = create_resp.json()["task_id"]

    resp = client.get(
        f"/api/tasks/{task_id}",
        params={"session_id": session_b},
        headers=_auth_headers(),
    )
    assert resp.status_code == 403


def test_api_list_tasks_returns_own_session_only(client) -> None:
    session_a = _make_session(client)
    session_b = _make_session(client)

    client.post(
        "/api/tasks",
        json={"description": "A1", "session_id": session_a},
        headers=_auth_headers(),
    )
    client.post(
        "/api/tasks",
        json={"description": "B1", "session_id": session_b},
        headers=_auth_headers(),
    )

    resp_a = client.get("/api/tasks", params={"session_id": session_a}, headers=_auth_headers())
    assert resp_a.status_code == 200
    tasks_a = resp_a.json()
    assert len(tasks_a) == 1
    assert tasks_a[0]["session_id"] == session_a


def test_api_cancel_task_transitions_to_cancelled(client) -> None:
    session_id = _make_session(client)
    create_resp = client.post(
        "/api/tasks",
        json={"description": "cancel me", "session_id": session_id},
        headers=_auth_headers(),
    )
    task_id = create_resp.json()["task_id"]

    # Cancel immediately (task is QUEUED or already completed by worker).
    resp = client.post(
        f"/api/tasks/{task_id}/cancel",
        params={"session_id": session_id},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    # State is CANCELLED (from QUEUED) or COMPLETED (if worker was faster).
    assert resp.json()["state"] in {"cancelled", "completed"}


def test_api_cancel_task_wrong_session_is_403(client) -> None:
    session_a = _make_session(client)
    session_b = _make_session(client)
    create_resp = client.post(
        "/api/tasks",
        json={"description": "mine", "session_id": session_a},
        headers=_auth_headers(),
    )
    task_id = create_resp.json()["task_id"]

    resp = client.post(
        f"/api/tasks/{task_id}/cancel",
        params={"session_id": session_b},
        headers=_auth_headers(),
    )
    assert resp.status_code == 403


def test_api_task_history_returns_audit_events(client) -> None:
    session_id = _make_session(client)
    create_resp = client.post(
        "/api/tasks",
        json={"description": "history", "session_id": session_id},
        headers=_auth_headers(),
    )
    task_id = create_resp.json()["task_id"]

    resp = client.get(
        f"/api/tasks/{task_id}/history",
        params={"session_id": session_id},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    events = [e["event"] for e in resp.json()]
    assert "created" in events


def test_api_task_history_wrong_session_is_403(client) -> None:
    session_a = _make_session(client)
    session_b = _make_session(client)
    create_resp = client.post(
        "/api/tasks",
        json={"description": "d", "session_id": session_a},
        headers=_auth_headers(),
    )
    task_id = create_resp.json()["task_id"]

    resp = client.get(
        f"/api/tasks/{task_id}/history",
        params={"session_id": session_b},
        headers=_auth_headers(),
    )
    assert resp.status_code == 403


def test_api_emergency_stop_cancels_queued_tasks(client) -> None:
    """Activating emergency stop via the API must cancel all active tasks."""
    session_id = _make_session(client)

    # Create two tasks.
    r1 = client.post(
        "/api/tasks",
        json={"description": "task 1", "session_id": session_id},
        headers=_auth_headers(),
    ).json()
    r2 = client.post(
        "/api/tasks",
        json={"description": "task 2", "session_id": session_id},
        headers=_auth_headers(),
    ).json()

    # Activate emergency stop.
    stop_resp = client.post("/api/emergency/activate", json={"reason": "test stop"})
    assert stop_resp.json()["engaged"] is True

    # Tasks that were QUEUED should now be CANCELLED or COMPLETED (if worker was faster).
    for task_id in [r1["task_id"], r2["task_id"]]:
        task_resp = client.get(
            f"/api/tasks/{task_id}",
            params={"session_id": session_id},
            headers=_auth_headers(),
        )
        assert task_resp.json()["state"] in {"cancelled", "completed"}

    # Reset for teardown.
    client.post("/api/emergency/reset", json={}, headers=_auth_headers())


def test_api_task_pause_non_running_returns_409(client) -> None:
    """Pausing a QUEUED task (not yet RUNNING) must return 409 Conflict."""
    import time

    session_id = _make_session(client)
    create_resp = client.post(
        "/api/tasks",
        json={"description": "pause me", "session_id": session_id},
        headers=_auth_headers(),
    )
    task_id = create_resp.json()["task_id"]

    # Cancel it first so it won't be picked up by the worker.
    client.post(
        f"/api/tasks/{task_id}/cancel",
        params={"session_id": session_id},
        headers=_auth_headers(),
    )

    # Now try to pause the cancelled task.
    resp = client.post(
        f"/api/tasks/{task_id}/pause",
        params={"session_id": session_id},
        headers=_auth_headers(),
    )
    assert resp.status_code == 409


def test_api_get_nonexistent_task_is_404(client) -> None:
    session_id = _make_session(client)
    resp = client.get(
        "/api/tasks/does-not-exist",
        params={"session_id": session_id},
        headers=_auth_headers(),
    )
    assert resp.status_code == 404
