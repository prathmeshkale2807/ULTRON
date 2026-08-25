import uuid
from typing import Any
import asyncio
from datetime import datetime, timezone

# We mock actual pywinauto/UIAutomation for the test environment
# In a real implementation this would bind to UIA.

# Snapshot storage: maps snapshot_id to its UI tree state.
# A real implementation would persist or bound this.
_snapshots: dict[str, dict[str, Any]] = {}

def is_sensitive_control(control: dict[str, Any]) -> bool:
    """Heuristic for sensitive UI fields like passwords, OTPs."""
    name = control.get("name", "").lower()
    auto_id = control.get("automation_id", "").lower()
    control_type = control.get("control_type", "")
    
    if control.get("is_password", False):
        return True
        
    sensitive_keywords = ["password", "otp", "cvv", "credit card", "pin", "credential"]
    for keyword in sensitive_keywords:
        if keyword in name or keyword in auto_id:
            return True
            
    # UAC or Permission dialogs
    if control_type == "Window" and "User Account Control" in control.get("title", ""):
        return True
        
    return False

def get_ui_tree() -> dict[str, Any]:
    """Mocks fetching the current active window's UI tree."""
    # In tests, we will monkeypatch this function
    return {
        "window_title": "Calculator",
        "application_name": "CalculatorApp",
        "controls": []
    }

def get_active_window_info() -> dict[str, str]:
    # Mock
    return {
        "window_title": "Calculator",
        "application_name": "CalculatorApp"
    }

class AutomationError(Exception):
    pass

class StaleTargetError(AutomationError):
    pass

class SecurityError(AutomationError):
    pass

def generate_snapshot() -> dict[str, Any]:
    tree = get_ui_tree()
    snapshot_id = str(uuid.uuid4())
    _snapshots[snapshot_id] = {
        "timestamp": datetime.now(timezone.utc),
        "tree": tree,
        "window_title": tree.get("window_title"),
        "application_name": tree.get("application_name")
    }
    return {
        "snapshot_id": snapshot_id,
        "window_title": tree.get("window_title"),
        "application_name": tree.get("application_name"),
        "controls": tree.get("controls")
    }

def resolve_target(snapshot_id: str, control_id: str, expected_app: str, expected_window: str) -> dict[str, Any]:
    # 1. Verify snapshot exists
    if snapshot_id not in _snapshots:
        raise StaleTargetError("Snapshot not found or expired.")
    
    snapshot = _snapshots[snapshot_id]
    
    # 2. Verify active window hasn't changed
    active = get_active_window_info()
    if active.get("application_name") != expected_app or active.get("window_title") != expected_window:
        raise StaleTargetError(f"Active window mismatch. Expected {expected_app}:{expected_window}, got {active.get('application_name')}:{active.get('window_title')}")
        
    # 3. Verify target control exists in the live tree (we mock this by just checking the snapshot for now,
    # but a real implementation would re-verify the live node).
    tree = get_ui_tree()
    live_controls = {c["control_id"]: c for c in tree.get("controls", [])}
    
    if control_id not in live_controls:
        raise StaleTargetError("Control ID no longer exists in the active window.")
        
    control = live_controls[control_id]
    
    if is_sensitive_control(control):
        raise SecurityError("Target control is marked as sensitive. Automation blocked.")
        
    return control

def click_control(snapshot_id: str, control_id: str, expected_app: str, expected_window: str) -> bool:
    control = resolve_target(snapshot_id, control_id, expected_app, expected_window)
    # Perform actual semantic click via pywinauto/UIA
    return True

def select_control(snapshot_id: str, control_id: str, expected_app: str, expected_window: str) -> bool:
    control = resolve_target(snapshot_id, control_id, expected_app, expected_window)
    # Perform actual semantic select
    return True

# Focus window allowlist
ALLOWED_FOCUS_APPS = ["calculatorapp", "notepad", "chrome", "msedge"]

def focus_window(application_name: str, window_title: str) -> bool:
    if application_name.lower() not in ALLOWED_FOCUS_APPS:
        raise SecurityError(f"Application {application_name} is not in the focus allowlist.")
    # Perform focus
    return True
