import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from app.android.tools import (
    handle_android_send_sms,
    handle_android_get_location,
    handle_android_open_app,
    handle_android_set_volume,
    handle_android_get_device_status,
    ALLOWED_APPS
)
from app.android.transport import TransportError
from app.tools.models import ExecutionContext

@pytest.fixture
def mock_transport():
    with patch("app.android.tools.get_transport") as get_trans:
        mock = AsyncMock()
        get_trans.return_value = mock
        yield mock

@pytest.fixture
def mock_ctx():
    return ExecutionContext(
        principal_id="principal-1",
        session_id="session-1",
        task_id=None
    )

@pytest.mark.asyncio
async def test_android_get_location(mock_transport, mock_ctx):
    mock_transport.dispatch.return_value = {"lat": 1.0, "lon": 2.0}
    res = await handle_android_get_location(mock_ctx, {"target_device_id": "dev-1"})
    assert res == {"lat": 1.0, "lon": 2.0}
    mock_transport.dispatch.assert_called_once_with(mock_ctx, "dev-1", "android_get_location", {})

@pytest.mark.asyncio
async def test_android_send_sms(mock_transport, mock_ctx):
    mock_transport.dispatch.return_value = {"success": True}
    res = await handle_android_send_sms(mock_ctx, {
        "target_device_id": "dev-1",
        "phone_number": "123",
        "message": "test msg"
    })
    assert res == {"success": True}
    mock_transport.dispatch.assert_called_once_with(mock_ctx, "dev-1", "android_send_sms", {
        "recipient": "123",
        "message": "test msg"
    })

@pytest.mark.asyncio
async def test_android_open_app_allowed(mock_transport, mock_ctx):
    mock_transport.dispatch.return_value = {"success": True}
    res = await handle_android_open_app(mock_ctx, {
        "target_device_id": "dev-1",
        "package_name": "com.android.settings"
    })
    assert res == {"success": True}
    mock_transport.dispatch.assert_called_once_with(mock_ctx, "dev-1", "android_open_app", {"package_name": "com.android.settings"})

@pytest.mark.asyncio
async def test_android_open_app_rejected(mock_transport, mock_ctx):
    res = await handle_android_open_app(mock_ctx, {
        "target_device_id": "dev-1",
        "package_name": "com.evil.app"
    })
    assert res.get("status") == "error"
    assert "not in the allowlist" in res.get("error", "")
    assert not mock_transport.dispatch.called

@pytest.mark.asyncio
async def test_android_set_volume_bounds(mock_transport, mock_ctx):
    res = await handle_android_set_volume(mock_ctx, {
        "target_device_id": "dev-1",
        "level": 150
    })
    assert res.get("status") == "error"
    assert not mock_transport.dispatch.called

    res = await handle_android_set_volume(mock_ctx, {
        "target_device_id": "dev-1",
        "level": -10
    })
    assert res.get("status") == "error"
    assert not mock_transport.dispatch.called

@pytest.mark.asyncio
async def test_android_transport_error_returns_status(mock_transport, mock_ctx):
    mock_transport.dispatch.side_effect = TransportError("Timeout")
    res = await handle_android_get_device_status(mock_ctx, {"target_device_id": "dev-1"})
    assert res == {"status": "error", "error": "Timeout"}
