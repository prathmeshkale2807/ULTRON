import uuid
from typing import Any
from datetime import datetime, timezone

# Snapshot storage: maps snapshot_id to its UI tree state.
_snapshots: dict[str, dict[str, Any]] = {}

def get_active_app_info(device_id: str) -> dict[str, str]:
    return {
        "package_name": "com.android.calculator2",
        "activity_name": "com.android.calculator2.Calculator"
    }

class AutomationError(Exception):
    pass

class StaleTargetError(AutomationError):
    pass

class SecurityError(AutomationError):
    pass

def dump_ui(device_id: str) -> dict[str, Any]:
    # Mocks `adb shell uiautomator dump`
    app_info = get_active_app_info(device_id)
    tree = {
        "package_name": app_info["package_name"],
        "activity_name": app_info["activity_name"],
        "nodes": [
            {"resource_id": "com.android.calculator2:id/digit_1", "text": "1", "bounds": "[100,100][200,200]"}
        ]
    }
    
    snapshot_id = str(uuid.uuid4())
    _snapshots[snapshot_id] = {
        "timestamp": datetime.now(timezone.utc),
        "tree": tree,
        "package_name": tree["package_name"],
        "activity_name": tree["activity_name"],
        "device_id": device_id
    }
    return {
        "snapshot_id": snapshot_id,
        "tree": tree
    }

def resolve_target(device_id: str, snapshot_id: str, resource_id: str, expected_package: str) -> dict[str, Any]:
    if snapshot_id not in _snapshots:
        raise StaleTargetError("Snapshot not found or expired.")
        
    snapshot = _snapshots[snapshot_id]
    
    if snapshot["device_id"] != device_id:
        raise SecurityError("Device mismatch.")
    
    active = get_active_app_info(device_id)
    if active["package_name"] != expected_package:
        raise StaleTargetError(f"Active package mismatch. Expected {expected_package}, got {active['package_name']}")
        
    nodes = {n.get("resource_id"): n for n in snapshot["tree"]["nodes"]}
    if resource_id not in nodes:
        raise StaleTargetError("Resource ID no longer exists in the active window.")
        
    # Check sensitive bounds/fields here if applicable
    return nodes[resource_id]

def tap_allowlisted_target(device_id: str, snapshot_id: str, resource_id: str, expected_package: str) -> bool:
    node = resolve_target(device_id, snapshot_id, resource_id, expected_package)
    # Execute semantic tap (e.g. adb shell input tap x y)
    return True

def swipe_allowlisted_target(device_id: str, snapshot_id: str, resource_id: str, expected_package: str) -> bool:
    node = resolve_target(device_id, snapshot_id, resource_id, expected_package)
    return True

ALLOWED_KEYCODES = ["HOME", "BACK", "VOLUME_UP", "VOLUME_DOWN"]

def press_keycode(device_id: str, keycode: str) -> bool:
    if keycode.upper() not in ALLOWED_KEYCODES:
        raise SecurityError(f"Keycode {keycode} is not in the allowlist.")
    # Execute adb shell input keyevent
    return True
