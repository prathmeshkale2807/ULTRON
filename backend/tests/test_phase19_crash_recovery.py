import pytest
import asyncio
from app.tasks.models import TaskState
from app.tasks.worker import _execute_task
from app.core.database import TaskRecord
from app.tools.registry import get_registry
from app.tools.models import ToolDefinition, RiskLevel, PermissionCategory, ConfirmationTier

@pytest.fixture
def session_factory(db_session):
    return lambda: db_session

@pytest.fixture(autouse=True)
def setup_tools(db_session):
    registry = get_registry()
    
    # Idempotent tool
    async def mock_idempotent(ctx, args):
        if args.get("fail"):
            raise Exception("Idempotent fail")
        return {"success": True}
        
    registry.register(ToolDefinition(
        name="test_idempotent",
        description="test",
        input_schema={"type": "object", "properties": {"fail": {"type": "boolean"}}},
        output_schema={},
        risk_level=RiskLevel.LOW,
        permission_category=PermissionCategory.OTHER,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=["pc"],
        is_idempotent=True,
        handler=mock_idempotent
    ))
    
    # Non-idempotent tool
    async def mock_non_idempotent(ctx, args):
        if args.get("fail"):
            raise Exception("Non-idempotent fail")
        return {"success": True}
        
    registry.register(ToolDefinition(
        name="test_non_idempotent",
        description="test",
        input_schema={"type": "object", "properties": {"fail": {"type": "boolean"}}},
        output_schema={},
        risk_level=RiskLevel.LOW,
        permission_category=PermissionCategory.OTHER,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=["pc"],
        is_idempotent=False,
        handler=mock_non_idempotent
    ))
    
    yield
    registry.unregister("test_idempotent")
    registry.unregister("test_non_idempotent")


@pytest.mark.asyncio
async def test_idempotent_failure_marks_failed(db_session, session_factory, monkeypatch):
    import json
    row = TaskRecord(
        task_id="task_idemp_1",
        principal_id="test_user",
        state=TaskState.QUEUED.value,
        tools_requested=json.dumps([{"tool_name": "test_idempotent", "arguments": {"fail": True}}])
    )
    db_session.add(row)
    db_session.commit()
    
    from app.executor.executor import ToolExecutor, ToolExecutionResult
    async def mock_execute(*args, **kwargs):
        return ToolExecutionResult(success=False, stage="execution", error="Idempotent fail")
    monkeypatch.setattr(ToolExecutor, "execute", mock_execute)
    
    await _execute_task("task_idemp_1", session_factory=session_factory)
    
    db_session.expire_all()
    updated = db_session.get(TaskRecord, "task_idemp_1")
    assert updated.state == TaskState.FAILED.value


@pytest.mark.asyncio
async def test_non_idempotent_failure_marks_needs_reconciliation(db_session, session_factory, monkeypatch):
    import json
    row = TaskRecord(
        task_id="task_non_idemp_1",
        principal_id="test_user",
        state=TaskState.QUEUED.value,
        tools_requested=json.dumps([{"tool_name": "test_non_idempotent", "arguments": {"fail": True}}])
    )
    db_session.add(row)
    db_session.commit()
    
    from app.executor.executor import ToolExecutor, ToolExecutionResult
    async def mock_execute(*args, **kwargs):
        return ToolExecutionResult(success=False, stage="execution", error="Non-idempotent fail")
    monkeypatch.setattr(ToolExecutor, "execute", mock_execute)
    
    await _execute_task("task_non_idemp_1", session_factory=session_factory)
    
    db_session.expire_all()
    updated = db_session.get(TaskRecord, "task_non_idemp_1")
    assert updated.state == TaskState.NEEDS_RECONCILIATION.value


@pytest.mark.asyncio
async def test_crash_during_execution_defaults_to_needs_reconciliation(db_session, session_factory, monkeypatch):
    import json
    row = TaskRecord(
        task_id="task_crash_1",
        principal_id="test_user",
        state=TaskState.QUEUED.value,
        tools_requested=json.dumps([{"tool_name": "test_non_idempotent", "arguments": {"fail": False}}])
    )
    db_session.add(row)
    db_session.commit()
    
    # Monkeypatch the executor to throw a hard exception, simulating a crash
    from app.executor.executor import ToolExecutor
    async def crash_execute(*args, **kwargs):
        raise RuntimeError("simulated hard crash")
        
    monkeypatch.setattr(ToolExecutor, "execute", crash_execute)
    
    await _execute_task("task_crash_1", session_factory=session_factory)
    
    db_session.expire_all()
    updated = db_session.get(TaskRecord, "task_crash_1")
    assert updated.state == TaskState.NEEDS_RECONCILIATION.value
    assert "simulated hard crash" in updated.error_summary
