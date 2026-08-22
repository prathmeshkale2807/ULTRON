from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import DevicePairingCode, DeviceRecord
from app.devices.manager import DeviceManager, DeviceAuthError
from app.executor.executor import ToolExecutor, DeviceValidationError, PermissionDeniedError, EmergencyStopEngagedError
from app.tools.registry import get_registry
from app.tools.models import DeviceType, RiskLevel, PermissionCategory, ConfirmationTier
from app.safety.models import SafetyMode
from app.permissions.store import PermissionStore

def test_generate_and_pair_device(db_session: Session):
    manager = DeviceManager(db_session)
    # 1. Generate code
    record = manager.generate_pairing_code("test_user_1", "Test Pixel")
    assert len(record.code) == 6
    assert record.principal_id == "test_user_1"
    
    # 2. Pair device
    device_id, credential = manager.pair_device(record.code, "Test Pixel")
    assert device_id
    assert credential
    
    # 3. Check DB
    device = db_session.get(DeviceRecord, device_id)
    assert device.principal_id == "test_user_1"
    assert device.name == "Test Pixel"
    assert device.status == "PAIRED"
    assert device.credential_hash != credential  # should be hashed
    
    # 4. Code reuse rejection
    with pytest.raises(DeviceAuthError, match="Invalid pairing code"):
        manager.pair_device(record.code, "Hacker Device")

def test_pairing_code_expiration(db_session: Session):
    manager = DeviceManager(db_session)
    record = manager.generate_pairing_code("test_user_1", "Test Pixel")
    
    # Simulate expiration in DB
    record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    
    with pytest.raises(DeviceAuthError, match="Pairing code expired"):
        manager.pair_device(record.code, "Test Pixel")

def test_heartbeat_authentication_and_status(db_session: Session):
    manager = DeviceManager(db_session)
    record = manager.generate_pairing_code("test_user_1", "Test Pixel")
    device_id, credential = manager.pair_device(record.code, "Test Pixel")
    
    # Valid heartbeat
    manager.heartbeat(device_id, credential)
    device = manager.get_device(device_id, "test_user_1")
    assert manager.get_computed_status(device) == "ONLINE"
        
    # Stale heartbeat (offline)
    device.last_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=10)
    db_session.commit()
    device = manager.get_device(device_id, "test_user_1")
    assert manager.get_computed_status(device) == "OFFLINE"
        
    # Invalid credential
    with pytest.raises(DeviceAuthError, match="Invalid credential"):
        manager.heartbeat(device_id, "wrong_cred")
        
    # Revoked device
    manager.revoke_device(device_id, "test_user_1")
    with pytest.raises(DeviceAuthError, match="Device revoked"):
        manager.heartbeat(device_id, credential)

from app.permissions.models import PermissionScope
from app.android.tools import ANDROID_TOOLS

@pytest.mark.asyncio
async def test_android_tool_execution(db_session: Session):
    manager = DeviceManager(db_session)
    record = manager.generate_pairing_code("test_user_1", "Test Pixel")
    device_id, credential = manager.pair_device(record.code, "Test Pixel")
    
    registry = get_registry()
    for tool in ANDROID_TOOLS:
        registry.register(tool, replace=True)
        
    executor = ToolExecutor(db=db_session, registry=registry)
    PermissionStore(db_session).grant(PermissionCategory.ANDROID_SMS_SEND, PermissionScope.SESSION, session_id="test_user_1_session")
    PermissionStore(db_session).grant(PermissionCategory.ANDROID_LOCATION_READ, PermissionScope.SESSION, session_id="test_user_1_session")
    
    # 1. Target device mismatch (try to run Android tool with target=PC)
    with pytest.raises(DeviceValidationError):
        await executor.execute(
            "android_get_location",
            arguments={"target_device_id": device_id},
            target_device=DeviceType.PC,
            session_id="test_user_1_session",
            principal_id="test_user_1"
        )
        
    # 2. Ownership mismatch (try to run with another user's device)
    record2 = manager.generate_pairing_code("other_user", "Other Pixel")
    other_device_id, _ = manager.pair_device(record2.code, "Other Pixel")
    with pytest.raises(DeviceValidationError, match="Android device not found or ownership mismatch"):
        await executor.execute(
            "android_get_location",
            arguments={"target_device_id": other_device_id},
            target_device=DeviceType.ANDROID,
            session_id="test_user_1_session",
            principal_id="test_user_1"
        )

    # 3. Missing target_device_id (caught by schema validation first)
    from app.executor.executor import SchemaValidationError
    with pytest.raises(SchemaValidationError, match="required property"):
        await executor.execute(
            "android_get_location",
            arguments={},
            target_device=DeviceType.ANDROID,
            session_id="test_user_1_session",
            principal_id="test_user_1"
        )
        
    # 4. Valid execution (No fake success)
    res = await executor.execute(
        "android_get_location",
        arguments={"target_device_id": device_id},
        target_device=DeviceType.ANDROID,
        session_id="test_user_1_session",
        principal_id="test_user_1",
        confirmation_callback=lambda _: True  # auto-confirm for test
    )
    assert res.success
    output = res.output
    assert output["status"] == "error"
    assert "DEVICE_OFFLINE" in output["error"]
    
@pytest.mark.asyncio
async def test_android_permissions_and_emergency_stop(db_session: Session):
    manager = DeviceManager(db_session)
    record = manager.generate_pairing_code("test_user_1", "Test Pixel")
    device_id, _ = manager.pair_device(record.code, "Test Pixel")
    
    registry = get_registry()
    for tool in ANDROID_TOOLS:
        registry.register(tool, replace=True)
        
    executor = ToolExecutor(db=db_session, registry=registry)
    
    # 1. No permissions
    with pytest.raises(PermissionDeniedError):
        await executor.execute(
            "android_send_sms",
            arguments={"target_device_id": device_id, "phone_number": "123", "message": "hello"},
            target_device=DeviceType.ANDROID,
            session_id="test5_session",
            principal_id="test_user_1"
        )
        
    # 2. Grant SMS permission
    PermissionStore(db_session).grant(PermissionCategory.ANDROID_SMS_SEND, PermissionScope.SESSION, session_id="test5_session")
    
    res = await executor.execute(
        "android_send_sms",
        arguments={"target_device_id": device_id, "phone_number": "123", "message": "hello"},
        target_device=DeviceType.ANDROID,
        session_id="test5_session",
        principal_id="test_user_1",
        confirmation_callback=lambda _: True
    )
    assert not res.success
    assert "verification did not establish success" in res.error
    
    # 3. Emergency Stop
    from app.emergency.stop import EmergencyStop
    EmergencyStop(db_session).activate(reason="test", activated_by="test_user_1")
    
    with pytest.raises(EmergencyStopEngagedError):
        await executor.execute(
            "android_send_sms",
            arguments={"target_device_id": device_id, "phone_number": "123", "message": "hello"},
            target_device=DeviceType.ANDROID,
            session_id="test5_session",
            principal_id="test_user_1",
            confirmation_callback=lambda _: True
        )
