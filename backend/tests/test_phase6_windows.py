"""
Tests for Phase 6 -- Windows PC Control.
"""

import pytest
import os
import json
from unittest.mock import patch, MagicMock

from app.tools.registry import get_registry
from app.tools.models import DeviceType, RiskLevel, PermissionCategory, ConfirmationTier
from app.windows.safety import get_allowed_executable
from app.windows.applications import open_application, close_application, list_running_applications
from app.windows.system import get_system_info, get_active_window
from app.windows.screenshot import take_screenshot
from app.windows.tools import register_windows_tools
from app.executor.executor import ToolExecutor
from app.permissions.models import PermissionScope
from app.executor.confirmation import get_confirmation_broker
from app.core.database import AuditLogEntry

# Ensure tools are registered for tests
@pytest.fixture(autouse=True)
def register_tools():
    registry = get_registry()
    register_windows_tools(registry)
    yield
    # No need to unregister since tests run in their own process/state often, 
    # but get_registry() returns a singleton, so it's idempotent.

def test_application_allowlist():
    """Test the strict dictionary allowlist."""
    assert get_allowed_executable("notepad") == "notepad.exe"
    assert get_allowed_executable(" NOTEPAD ") == "notepad.exe" # Trims and lowercases
    assert get_allowed_executable("cmd.exe") is None
    assert get_allowed_executable("powershell") is None
    assert get_allowed_executable("C:\\Windows\\System32\\cmd.exe") is None

@patch("subprocess.Popen")
def test_open_allowed_application(mock_popen):
    """Test opening an allowed application uses shell=False."""
    mock_popen.return_value.pid = 1234
    
    result = open_application("notepad")
    assert result["success"] is True
    assert result["pid"] == 1234
    
    # Prove no shell injection
    mock_popen.assert_called_once_with(["notepad.exe"], shell=False)

@patch("subprocess.Popen")
def test_open_blocked_application(mock_popen):
    """Test arbitrary executable path rejection."""
    result = open_application("C:\\malicious.exe")
    assert result["success"] is False
    assert "not in the allowlist" in result["error"]
    
    mock_popen.assert_not_called()

@patch("psutil.process_iter")
def test_close_allowed_application(mock_process_iter):
    """Test closing an allowed application gracefully."""
    mock_proc = MagicMock()
    mock_proc.info = {"pid": 1234, "name": "notepad.exe"}
    mock_process_iter.return_value = [mock_proc]
    
    result = close_application("notepad")
    
    assert result["success"] is True
    assert "Closed 1 instances" in result["message"]
    mock_proc.terminate.assert_called_once()

@patch("psutil.process_iter")
def test_close_blocked_application(mock_process_iter):
    """Test closing a blocked application is rejected."""
    result = close_application("explorer")
    assert result["success"] is False
    assert "not in the allowlist" in result["error"]
    mock_process_iter.assert_not_called()

@patch("psutil.process_iter")
def test_list_running_applications(mock_process_iter):
    mock_proc1 = MagicMock(); mock_proc1.info = {"pid": 1, "name": "System"}
    mock_proc2 = MagicMock(); mock_proc2.info = {"pid": 2, "name": "svchost.exe"}
    mock_process_iter.return_value = [mock_proc1, mock_proc2]
    
    result = list_running_applications()
    assert result["success"] is True
    assert result["count"] == 2
    assert result["processes"][0]["name"] == "svchost.exe"

@patch("psutil.cpu_percent", return_value=15.0)
@patch("psutil.virtual_memory")
def test_system_info(mock_vm, mock_cpu):
    mock_vm.return_value.total = 16 * (1024**3)
    mock_vm.return_value.percent = 50.0
    
    result = get_system_info()
    assert result["success"] is True
    assert result["cpu_percent"] == 15.0
    assert result["ram_total_gb"] == 16.0
    assert result["ram_percent"] == 50.0

@patch("ctypes.windll.user32.GetForegroundWindow", return_value=123)
@patch("ctypes.windll.user32.GetWindowTextLengthW", return_value=4)
@patch("ctypes.windll.user32.GetWindowTextW")
def test_get_active_window(mock_get_text, mock_len, mock_hwnd):
    # ctypes buffer manipulation is tricky to mock perfectly, 
    # but we can test the success path basic logic
    def side_effect(hwnd, buff, length):
        buff.value = "Test"
    mock_get_text.side_effect = side_effect
    
    result = get_active_window()
    assert result["success"] is True
    assert result["title"] == "Test"

@patch("PIL.ImageGrab.grab")
def test_take_screenshot(mock_grab, tmp_path):
    mock_img = MagicMock()
    mock_img.width = 1920
    mock_img.height = 1080
    mock_grab.return_value = mock_img
    
    with patch("tempfile.gettempdir", return_value=str(tmp_path)):
        result = take_screenshot()
        
    assert result["success"] is True
    assert result["width"] == 1920
    assert "filepath" in result
    mock_img.save.assert_called_once()

# =====================================================================
# ToolExecutor Integration Tests
# =====================================================================

# =====================================================================
# ToolExecutor Integration Tests
# =====================================================================

@pytest.mark.asyncio
async def test_tool_executor_rejects_arbitrary_shell(db_session):
    executor = ToolExecutor(registry=get_registry(), db=db_session)
    executor.permission_store.grant(PermissionCategory.PC_PROCESS_CONTROL, PermissionScope.PERSISTENT)
    
    async def approve(req):
        executor.confirmation_broker.resolve(req.id, approved=True)
        return True
        
    result = await executor.execute(
        "windows_open_application",
        {"app_name": "cmd.exe /c echo hacked"},
        target_device=DeviceType.PC,
        session_id="test_session",
        confirmation_callback=approve
    )
    # The executor considers verification failed if the verifier returns False.
    # The handler returns {"success": False, ...}, causing the verifier to return False.
    assert result.success is False

@pytest.mark.asyncio
async def test_screenshot_requires_confirmation(db_session):
    """Screenshots are ALWAYS_ASK, requiring human confirmation."""
    executor = ToolExecutor(registry=get_registry(), db=db_session)
    executor.permission_store.grant(PermissionCategory.PC_SCREEN_CAPTURE, PermissionScope.PERSISTENT)
    
    # Background execution without confirmation broker pre-approved should fail or timeout
    import app.executor.executor as exec_mod
    with pytest.raises(exec_mod.ConfirmationTimeoutError):
        await executor.execute(
            "windows_take_screenshot",
            {},
            target_device=DeviceType.PC,
            session_id="test_session",
            confirmation_timeout_seconds=0.1
        )

@pytest.mark.asyncio
async def test_missing_permission_rejected(db_session):
    executor = ToolExecutor(registry=get_registry(), db=db_session)
    # Explicitly clear permission
    executor.permission_store.revoke(PermissionCategory.PC_PROCESS_CONTROL, PermissionScope.PERSISTENT)
    
    import app.executor.executor as exec_mod
    with pytest.raises(exec_mod.PermissionDeniedError):
        await executor.execute(
            "windows_open_application",
            {"app_name": "notepad"},
            target_device=DeviceType.PC,
            session_id="test_session"
        )

@pytest.mark.asyncio
async def test_audit_logging_windows(db_session):
    executor = ToolExecutor(registry=get_registry(), db=db_session)
    executor.permission_store.grant(PermissionCategory.PC_READ, PermissionScope.PERSISTENT)
    
    async def approve(req):
        executor.confirmation_broker.resolve(req.id, approved=True)
        return True
        
    await executor.execute(
        "windows_get_system_info",
        {},
        target_device=DeviceType.PC,
        session_id="test_session",
        confirmation_callback=approve
    )
    
    # Check audit log
    logs = db_session.query(AuditLogEntry).all()
    assert len(logs) > 0
    assert logs[-1].tool_name == "windows_get_system_info"

@pytest.mark.asyncio
async def test_wrong_device_rejected(db_session):
    executor = ToolExecutor(registry=get_registry(), db=db_session)
    async def approve(req):
        executor.confirmation_broker.resolve(req.id, approved=True)
        return True
        
    import app.executor.executor as exec_mod
    with pytest.raises(exec_mod.DeviceValidationError):
        await executor.execute(
            "windows_get_system_info",
            {},
            target_device=DeviceType.ANDROID, # Windows tools are PC only
            session_id="test_session",
            confirmation_callback=approve
        )

@pytest.mark.asyncio
async def test_verification_engine_close_app(db_session):
    executor = ToolExecutor(registry=get_registry(), db=db_session)
    executor.permission_store.grant(PermissionCategory.PC_PROCESS_CONTROL, PermissionScope.PERSISTENT)
    
    async def approve(req):
        executor.confirmation_broker.resolve(req.id, approved=True)
        return True
        
    from unittest.mock import AsyncMock
    tool_def = executor.registry.get("windows_close_application")
    
    with patch("app.windows.applications.close_application") as mock_close, \
         patch.object(tool_def, "verifier", new_callable=AsyncMock) as mock_verify:
         
         mock_close.return_value = {"success": True, "message": "Closed"}
         mock_verify.return_value = True # Simulate verification success
         result = await executor.execute(
            "windows_close_application",
            {"app_name": "notepad"},
            target_device=DeviceType.PC,
            session_id="test_session",
            confirmation_callback=approve
        )
         
         assert result.success is True
