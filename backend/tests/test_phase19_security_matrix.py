import pytest
import asyncio
from app.tasks.models import TaskState
from app.tasks.worker import _execute_task
from app.core.database import TaskRecord
from app.tools.registry import get_registry
from app.tools.models import ToolDefinition, RiskLevel, PermissionCategory, ConfirmationTier, DeviceType
from app.permissions.store import PermissionStore
from app.permissions.models import PermissionScope
from app.executor.executor import ToolExecutor
from app.emergency.stop import EmergencyStop
from app.executor.confirmation import ConfirmationBroker

@pytest.fixture
def session_factory(db_session):
    return lambda: db_session


@pytest.mark.asyncio
async def test_automation_rechecks_revoked_permission(db_session, session_factory):
    # Setup tool
    registry = get_registry()
    async def mock_handler(ctx, args):
        return {"success": True}
    
    registry.register(ToolDefinition(
        name="test_auto_tool",
        description="test",
        input_schema={},
        output_schema={},
        risk_level=RiskLevel.MEDIUM,
        permission_category=PermissionCategory.SYSTEM_CONTROL,
        confirmation_tier=ConfirmationTier.AUTOMATIC,
        allowed_devices=["pc"],
        handler=mock_handler
    ))
    
    store = PermissionStore(db_session)
    
    try:
        # Grant permission
        store.grant(
            principal_id="user1",
            category=PermissionCategory.SYSTEM_CONTROL,
            scope=PermissionScope.SESSION,
            session_id="sess1"
        )
        
        # Schedule task
        import json
        row = TaskRecord(
            task_id="task_auto_1",
            principal_id="user1",
            session_id="sess1",
            state=TaskState.QUEUED.value,
            tools_requested=json.dumps([{"tool_name": "test_auto_tool"}])
        )
        db_session.add(row)
        db_session.commit()
        
        # Revoke permission before execution!
        store.revoke(
            principal_id="user1",
            category=PermissionCategory.SYSTEM_CONTROL,
            scope=PermissionScope.SESSION,
            session_id="sess1"
        )
        
        # Execute
        await _execute_task("task_auto_1", session_factory=session_factory)
        
        db_session.expire_all()
        updated = db_session.get(TaskRecord, "task_auto_1")
        # Should fail due to permission denied
        assert updated.state == TaskState.FAILED.value
        assert "permission" in updated.error_summary.lower()

    finally:
        registry.unregister("test_auto_tool")


@pytest.mark.asyncio
async def test_emergency_stop_blocks_scheduler(db_session, session_factory):
    import json
    # Enable emergency stop
    EmergencyStop(db_session).activate(activated_by="system", reason="test stop")
    
    row = TaskRecord(
        task_id="task_emg_1",
        principal_id="user1",
        state=TaskState.QUEUED.value,
        tools_requested=json.dumps([{"tool_name": "test_auto_tool"}])
    )
    db_session.add(row)
    db_session.commit()
    
    await _execute_task("task_emg_1", session_factory=session_factory)
    
    db_session.expire_all()
    updated = db_session.get(TaskRecord, "task_emg_1")
    assert updated.state == TaskState.CANCELLED.value
    assert "emergency stop engaged" in updated.error_summary.lower()

@pytest.mark.asyncio
async def test_voice_cannot_bypass_confirmation(db_session):
    registry = get_registry()
    async def mock_handler(ctx, args):
        return {"success": True}
    
    registry.register(ToolDefinition(
        name="test_voice_tool",
        description="test",
        input_schema={},
        output_schema={},
        risk_level=RiskLevel.HIGH,
        permission_category=PermissionCategory.SYSTEM_CONTROL,
        confirmation_tier=ConfirmationTier.ALWAYS_ASK,  # Voice can never bypass this
        allowed_devices=["pc"],
        handler=mock_handler
    ))
    
    store = PermissionStore(db_session)
    broker = ConfirmationBroker()
    executor = ToolExecutor(db=db_session, registry=registry, confirmation_broker=broker)
    
    try:
        # Grant permission so it doesn't fail on permissions
        store.grant(
            principal_id="user1",
            category=PermissionCategory.SYSTEM_CONTROL,
            scope=PermissionScope.SESSION,
            session_id="voice_sess"
        )
        
        # Try to execute via executor
        from app.executor.executor import ConfirmationTimeoutError
        with pytest.raises(ConfirmationTimeoutError):
            await executor.execute(
                tool_name="test_voice_tool",
                arguments={},
                target_device=DeviceType.PC,
                principal_id="user1",
                session_id="voice_sess",
                task_id="voice_task_1",
                confirmation_timeout_seconds=0.01
            )
            
    finally:
        registry.unregister("test_voice_tool")

@pytest.mark.asyncio
async def test_stale_responses_rejected():
    from fastapi import HTTPException
    from app.api.confirmations import resolve_confirmation, ResolveRequest
    from app.security.local_auth import Principal
    from app.executor.confirmation import get_confirmation_broker
    from app.tools.models import DeviceType
    
    broker = get_confirmation_broker()
    req = broker.create(
        principal_id="user1",
        session_id="sess1",
        task_id="task1",
        tool_name="some_tool",
        target_device=DeviceType.PC,
        action="test",
        reason="test",
        important_consequence="test",
        risk=RiskLevel.HIGH
    )
    
    # Try resolving via API with wrong principal
    wrong_principal = Principal(identity="wrong_user")
    with pytest.raises(HTTPException) as excinfo:
        resolve_confirmation(req.id, ResolveRequest(approved=True), principal=wrong_principal)
    assert excinfo.value.status_code == 403
    assert "not authorized" in str(excinfo.value.detail)

@pytest.mark.asyncio
async def test_wrong_android_principal_device_rejected(db_session):
    from app.devices.manager import DeviceManager, DeviceAuthError
    from app.core.database import DeviceRecord
    
    mgr = DeviceManager(db_session)
    
    db_session.add(DeviceRecord(
        device_id="dev1",
        principal_id="user1",
        name="test",
        credential_hash="test"
    ))
    db_session.commit()
    
    with pytest.raises(DeviceAuthError):
        mgr.get_device("dev1", "user2")

@pytest.mark.asyncio
async def test_browser_and_email_content_untrusted():
    from app.browser.safety import wrap_untrusted_content
    wrapped = wrap_untrusted_content("some content")
    assert "UNTRUSTED_EXTERNAL_CONTENT" in wrapped
    assert "some content" in wrapped
