import pytest
from app.android.automation import (
    dump_ui, resolve_target, tap_allowlisted_target, swipe_allowlisted_target, press_keycode,
    StaleTargetError, SecurityError
)
import app.android.automation as aut_mod

def test_dump_ui():
    res = dump_ui("device1")
    assert "snapshot_id" in res
    assert "tree" in res
    assert res["tree"]["package_name"] == "com.android.calculator2"

def test_resolve_target_success():
    res = dump_ui("device1")
    snapshot_id = res["snapshot_id"]
    
    node = resolve_target("device1", snapshot_id, "com.android.calculator2:id/digit_1", "com.android.calculator2")
    assert node["text"] == "1"

def test_stale_target_rejection_package_mismatch(monkeypatch):
    res = dump_ui("device1")
    snapshot_id = res["snapshot_id"]
    
    monkeypatch.setattr(aut_mod, "get_active_app_info", lambda did: {
        "package_name": "com.android.settings",
        "activity_name": "Settings"
    })
    
    with pytest.raises(StaleTargetError, match="Active package mismatch"):
        resolve_target("device1", snapshot_id, "com.android.calculator2:id/digit_1", "com.android.calculator2")
        
def test_device_ownership_protection():
    res = dump_ui("device1")
    snapshot_id = res["snapshot_id"]
    
    with pytest.raises(SecurityError, match="Device mismatch"):
        resolve_target("device2", snapshot_id, "com.android.calculator2:id/digit_1", "com.android.calculator2")

def test_keycode_allowlist():
    assert press_keycode("device1", "HOME") == True
    
    with pytest.raises(SecurityError, match="not in the allowlist"):
        press_keycode("device1", "POWER")
