import pytest
import asyncio
from typing import Any
from fastapi.websockets import WebSocket
from app.android.transport import get_transport, DeviceOfflineError
from app.android.tools import redact_notification, handle_android_get_notifications, handle_android_launch_intent, handle_android_set_brightness
from app.tools.models import ExecutionContext
from pydantic import BaseModel

class DummyContext(ExecutionContext):
    pass

@pytest.fixture
def dummy_ctx():
    return ExecutionContext(principal_id="user123", task_id="task123")

def test_notification_redaction():
    text1 = "Your OTP is 123456"
    assert "123456" not in redact_notification(text1)
    
    text2 = "card ending in 1234"
    assert "1234" not in redact_notification(text2)
    
    text3 = "Here is your verification code: 834211"
    assert "834211" not in redact_notification(text3)

@pytest.mark.asyncio
async def test_notification_sensitivity_propagation(dummy_ctx):
    transport = get_transport()
    
    # Mock transport dispatch
    async def mock_dispatch(ctx, device_id, action, payload, timeout=30.0):
        return {
            "notifications": [
                {"title": "Bank", "text": "Your OTP is 123456"}
            ]
        }
    
    original = transport.dispatch
    transport.dispatch = mock_dispatch
    
    try:
        result = await handle_android_get_notifications(dummy_ctx, {"target_device_id": "dev1"})
        notifs = result["notifications"]
        assert len(notifs) == 1
        assert "123456" not in notifs[0]["text"]
        assert notifs[0]["_sensitivity"] == "UNTRUSTED_EXTERNAL_CONTENT"
    finally:
        transport.dispatch = original

@pytest.mark.asyncio
async def test_unknown_intent_rejected_before_transport(dummy_ctx):
    transport = get_transport()
    
    dispatched = False
    async def mock_dispatch(*args, **kwargs):
        nonlocal dispatched
        dispatched = True
        return {}
        
    original = transport.dispatch
    transport.dispatch = mock_dispatch
    
    try:
        result = await handle_android_launch_intent(dummy_ctx, {
            "target_device_id": "dev1",
            "intent_name": "UNKNOWN_EVIL_INTENT"
        })
        assert result.get("status") == "error"
        assert not dispatched
    finally:
        transport.dispatch = original

@pytest.mark.asyncio
async def test_verification_without_new_task_creation(dummy_ctx):
    transport = get_transport()
    
    call_count = 0
    async def mock_dispatch(ctx, device_id, action, payload, timeout=30.0):
        nonlocal call_count
        call_count += 1
        if action == "android_set_brightness":
            return {}
        elif action == "android_get_brightness":
            return {"level": payload.get("level", 50)} if call_count == 2 else {"level": 50}
        return {}
        
    original = transport.dispatch
    transport.dispatch = mock_dispatch
    
    try:
        result = await handle_android_set_brightness(dummy_ctx, {
            "target_device_id": "dev1",
            "level": 50
        })
        assert call_count == 2
        assert result.get("status") == "success"
        assert result.get("verified") is True
    finally:
        transport.dispatch = original

@pytest.mark.asyncio
async def test_late_response_after_cancellation(dummy_ctx):
    transport = get_transport()
    
    class MockWS:
        async def send_text(self, data):
            pass
            
    ws = MockWS()
    await transport.connect("dev2", ws)
    
    task = asyncio.create_task(transport.dispatch(dummy_ctx, "dev2", "test_action", {}))
    await asyncio.sleep(0.01) # let it start
    
    # Cancel the task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
        
    # Send a late response
    # we need the request_id
    if transport.pending_requests:
        req_id = list(transport.pending_requests.keys())[0]
        await transport.handle_response("dev2", {"request_id": req_id, "status": "success", "data": {}})
    
    # Ensure it's not pending
    assert len(transport.pending_requests) == 0

