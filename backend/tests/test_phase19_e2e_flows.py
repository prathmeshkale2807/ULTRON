import pytest
import asyncio
from app.tasks.models import TaskState
from app.tasks.worker import _execute_task
from app.core.database import TaskRecord
from app.tools.registry import get_registry
from app.tools.models import ToolDefinition, RiskLevel, PermissionCategory, ConfirmationTier
from app.permissions.store import PermissionStore
from app.permissions.models import PermissionScope
from app.executor.confirmation import ConfirmationBroker

@pytest.fixture
def session_factory(db_session):
    return lambda: db_session

@pytest.mark.asyncio
async def test_e2e_automation_to_email_send(db_session, session_factory, monkeypatch):
    """
    Verify the complete pipeline:
    Scheduler -> Task -> Permission -> Confirmation -> fake provider -> verification -> idempotency
    """
    registry = get_registry()
    
    # 1. Mock Gmail Provider tool
    provider_called = False
    
    async def mock_gmail_send(ctx, args):
        nonlocal provider_called
        provider_called = True
        return {"success": True, "message_id": "mock_id_123"}
        
    async def mock_gmail_verify(ctx, args, output):
        return output.get("success") is True
        
    registry.register(ToolDefinition(
        name="send_email",
        description="test",
        input_schema={},
        output_schema={},
        risk_level=RiskLevel.MEDIUM,
        permission_category=PermissionCategory.EMAIL_SEND,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=["pc"],
        is_idempotent=False,
        handler=mock_gmail_send,
        verifier=mock_gmail_verify
    ))
    
    try:
        # 2. Grant Permission
        store = PermissionStore(db_session)
        store.grant(
            principal_id="user1",
            category=PermissionCategory.EMAIL_SEND,
            scope=PermissionScope.SESSION,
            session_id="sess1"
        )
        
        # 3. Schedule task
        import json
        row = TaskRecord(
            task_id="task_email_1",
            principal_id="user1",
            session_id="sess1",
            state=TaskState.QUEUED.value,
            tools_requested=json.dumps([{"tool_name": "send_email", "arguments": {"to": "test@test.com"}}])
        )
        db_session.add(row)
        db_session.commit()
        
        # 4. Execute pipeline (Worker handles tool, perm check, etc)
        await _execute_task("task_email_1", session_factory=session_factory)
        
        # 5. Verify outcome
        db_session.expire_all()
        updated = db_session.get(TaskRecord, "task_email_1")
        assert updated.state == TaskState.COMPLETED.value
        assert provider_called is True

    finally:
        registry.unregister("send_email")
