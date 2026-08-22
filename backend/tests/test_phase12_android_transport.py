import pytest
import asyncio
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect
from unittest.mock import AsyncMock, MagicMock
from app.android.transport import WebSocketAndroidTransport, DeviceOfflineError, DeviceTimeoutError
from app.core.database import DeviceRecord
from app.devices.manager import DeviceAuthError

@pytest.fixture
def transport():
    t = WebSocketAndroidTransport()
    # Reset state for each test
    t.connections.clear()
    t.pending_requests.clear()
    return t

@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return ws

@pytest.mark.asyncio
async def test_connect_and_disconnect(transport, mock_ws):
    await transport.connect("dev-1", mock_ws)
    assert "dev-1" in transport.connections
    
    transport.disconnect("dev-1")
    assert "dev-1" not in transport.connections

@pytest.mark.asyncio
async def test_dispatch_fails_if_offline(transport):
    with pytest.raises(DeviceOfflineError):
        await transport.dispatch("dev-1", "action_test", {})

@pytest.mark.asyncio
async def test_dispatch_success(transport, mock_ws):
    await transport.connect("dev-1", mock_ws)
    
    # Run dispatch in a task
    dispatch_task = asyncio.create_task(transport.dispatch("dev-1", "action_test", {"foo": "bar"}))
    
    # Wait for the future to be registered
    await asyncio.sleep(0.01)
    assert len(transport.pending_requests) == 1
    req_id = list(transport.pending_requests.keys())[0]
    
    # Verify we sent a message
    assert mock_ws.send_text.called
    
    # Simulate response
    await transport.handle_response("dev-1", {
        "request_id": req_id,
        "status": "success",
        "data": {"result": 123}
    })
    
    res = await dispatch_task
    assert res == {"result": 123}
    assert len(transport.pending_requests) == 0

@pytest.mark.asyncio
async def test_dispatch_timeout(transport, mock_ws):
    await transport.connect("dev-1", mock_ws)
    with pytest.raises(DeviceTimeoutError):
        await transport.dispatch("dev-1", "action_test", {}, timeout=0.01)
    
    assert len(transport.pending_requests) == 0

@pytest.mark.asyncio
async def test_handle_response_wrong_device(transport, mock_ws):
    await transport.connect("dev-1", mock_ws)
    
    dispatch_task = asyncio.create_task(transport.dispatch("dev-1", "action_test", {}))
    await asyncio.sleep(0.01)
    req_id = list(transport.pending_requests.keys())[0]
    
    # Respond with wrong device_id
    await transport.handle_response("dev-2", {
        "request_id": req_id,
        "status": "success",
        "data": {"result": 123}
    })
    
    # Future should still be pending
    assert len(transport.pending_requests) == 1
    dispatch_task.cancel()
    
@pytest.mark.asyncio
async def test_disconnect_cancels_pending_requests(transport, mock_ws):
    await transport.connect("dev-1", mock_ws)
    
    dispatch_task = asyncio.create_task(transport.dispatch("dev-1", "action_test", {}))
    await asyncio.sleep(0.01)
    
    transport.disconnect("dev-1")
    
    with pytest.raises(DeviceOfflineError):
        await dispatch_task
    
    assert len(transport.pending_requests) == 0

@pytest.mark.asyncio
async def test_dispatch_cancellation(transport, mock_ws):
    await transport.connect("dev-1", mock_ws)
    
    dispatch_task = asyncio.create_task(transport.dispatch("dev-1", "action_test", {}))
    await asyncio.sleep(0.01)
    
    # Cancel the task
    dispatch_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await dispatch_task
        
    # Verify future is removed
    assert len(transport.pending_requests) == 0
    # Verify we sent a cancel frame (it's called asynchronously in a task, so we yield control first)
    await asyncio.sleep(0.01)
    
    # We should have two calls to send_text: the initial dispatch, and the cancel
    assert mock_ws.send_text.call_count == 2
    last_call = mock_ws.send_text.call_args[0][0]
    import json
    data = json.loads(last_call)
    assert data["action"] == "cancel_task"
